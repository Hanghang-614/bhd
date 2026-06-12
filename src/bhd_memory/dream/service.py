from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ..memory import MemoryService
from ..repository import ensure_source_app, ensure_workspace
from ..storage import ArtifactStore, StoredArtifact
from ..utils import (
    clean_text,
    guess_mime,
    json_dumps,
    json_loads,
    new_id,
    now_iso,
    rough_token_count,
    sha256_text,
)
from .adapters import (
    ClaudeCodeTranscriptAdapter,
    CodexTranscriptAdapter,
    ExternalSession,
    GenericPathTranscriptAdapter,
    JsonlTranscriptAdapter,
    RawTurn,
)


class DreamService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        memory_service: MemoryService,
        store: ArtifactStore | None = None,
    ) -> None:
        self.conn = conn
        self.memory_service = memory_service
        self.store = store or ArtifactStore()

    def scan(
        self,
        *,
        paths: list[str] | None = None,
        auto_commit: bool = False,
    ) -> dict[str, Any]:
        adapters: list[JsonlTranscriptAdapter]
        if paths:
            adapters = [GenericPathTranscriptAdapter(paths)]
        else:
            adapters = [ClaudeCodeTranscriptAdapter(), CodexTranscriptAdapter()]

        scanned: list[dict[str, Any]] = []
        for adapter in adapters:
            if not adapter.detect():
                scanned.append(
                    {
                        "source": adapter.source_name,
                        "detected": False,
                        "sessions": [],
                    }
                )
                continue
            source_id = self._ensure_adapter_source(adapter)
            cursor = self._load_sync_cursor(source_id, adapter)
            adapter_cursor = dict(cursor)
            if auto_commit:
                adapter_cursor["_include_unchanged"] = True
            adapter_sessions = []
            for external in adapter.list_sessions(adapter_cursor):
                unchanged = bool(external.metadata.get("cursor_unchanged"))
                existing_session_id = self._find_session_id(source_id, external.external_session_id)
                if unchanged and existing_session_id:
                    session = self._scan_session_result(
                        existing_session_id,
                        source_id=source_id,
                        external=external,
                        adapter=adapter,
                        inserted_turns=0,
                        skipped=True,
                    )
                else:
                    session = self._persist_session(external, adapter, source_id=source_id)
                self._record_cursor_file(cursor, external)
                self._save_sync_cursor(source_id, adapter, cursor)
                if auto_commit:
                    session["archive"] = self.commit_session(session["id"], reason="scan_auto_commit")
                adapter_sessions.append(session)
            skipped_sessions = len(adapter_cursor.get("_skipped_paths", []))
            if not adapter_sessions:
                self._save_sync_cursor(source_id, adapter, cursor)
            scanned.append(
                {
                    "source": adapter.source_name,
                    "detected": True,
                    "sessions": adapter_sessions,
                    "skipped_sessions": skipped_sessions,
                }
            )
        return {"scanned": scanned}

    def list_sessions(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        clauses = []
        params: list[Any] = []
        if status:
            clauses.append("cs.status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"""
            SELECT cs.*, sa.name AS source_name, ws.name AS workspace_name,
                   COUNT(ct.id) AS turn_count
            FROM conversation_session cs
            JOIN source_app sa ON sa.id = cs.source_app_id
            LEFT JOIN workspace ws ON ws.id = cs.workspace_id
            LEFT JOIN conversation_turn ct ON ct.session_id = cs.id
            {where}
            GROUP BY cs.id
            ORDER BY cs.updated_at DESC
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()
        return [self._session_dict(row) for row in rows]

    def get_session(self, session_id: str, *, include_turns: bool = False) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT cs.*, sa.name AS source_name, ws.name AS workspace_name
            FROM conversation_session cs
            JOIN source_app sa ON sa.id = cs.source_app_id
            LEFT JOIN workspace ws ON ws.id = cs.workspace_id
            WHERE cs.id = ?
            """,
            (session_id,),
        ).fetchone()
        if not row:
            return None
        session = self._session_dict(row)
        if include_turns:
            turns = self.conn.execute(
                "SELECT * FROM conversation_turn WHERE session_id = ? ORDER BY created_at, external_turn_id",
                (session_id,),
            ).fetchall()
            session["turns"] = [dict(turn) for turn in turns]
        return session

    def get_archive(self, session_id: str, archive_no: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT sa.*
            FROM session_archive sa
            WHERE sa.session_id = ? AND sa.archive_no = ?
            """,
            (session_id, archive_no),
        ).fetchone()
        if not row:
            return None
        archive = dict(row)
        archive["metadata"] = json_loads(archive.pop("metadata_json", None))
        archive["turns"] = []
        raw_uri = archive.get("raw_uri")
        if raw_uri and Path(raw_uri).exists():
            archive["turns"] = [
                json.loads(line)
                for line in Path(raw_uri).read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        return archive

    def sweep_idle(self, *, idle_seconds: int = 1800, limit: int = 50) -> dict[str, Any]:
        cutoff = (datetime.now(UTC) - timedelta(seconds=idle_seconds)).replace(microsecond=0).isoformat()
        rows = self.conn.execute(
            """
            SELECT id
            FROM conversation_session
            WHERE status = 'active' AND updated_at <= ?
            ORDER BY updated_at
            LIMIT ?
            """,
            (cutoff, limit),
        ).fetchall()
        committed: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        for row in rows:
            try:
                committed.append(self.commit_session(row["id"], reason="idle_sweep"))
            except Exception as exc:
                failed.append({"session_id": row["id"], "error": str(exc)})
        return {
            "idle_seconds": idle_seconds,
            "cutoff": cutoff,
            "committed": committed,
            "failed": failed,
        }

    def commit_session(self, session_id: str, *, reason: str = "manual") -> dict[str, Any]:
        session = self.get_session(session_id)
        if not session:
            raise KeyError(f"session not found: {session_id}")
        turns = self.conn.execute(
            "SELECT * FROM conversation_turn WHERE session_id = ? ORDER BY created_at, external_turn_id",
            (session_id,),
        ).fetchall()
        if not turns:
            raise ValueError("cannot commit a session without turns")

        turns_hash = sha256_text(
            "\n".join(f"{turn['id']}:{turn['hash']}" for turn in turns)
        )
        latest = self.conn.execute(
            """
            SELECT * FROM session_archive
            WHERE session_id = ?
            ORDER BY archive_no DESC
            LIMIT 1
            """,
            (session_id,),
        ).fetchone()
        if latest and json_loads(latest["metadata_json"]).get("turns_hash") == turns_hash:
            return {
                **dict(latest),
                "metadata": json_loads(latest["metadata_json"]),
                "created": False,
                "memories": [],
            }

        archive_no = int(latest["archive_no"]) + 1 if latest else 1
        archive_lines = [
            json.dumps(
                {
                    "id": turn["id"],
                    "role": turn["role"],
                    "content": turn["content"],
                    "created_at": turn["created_at"],
                    "raw_ref": turn["raw_ref"],
                },
                ensure_ascii=False,
            )
            for turn in turns
        ]
        stored = self.store.write_jsonl(
            "session_archives",
            f"{session_id}-archive-{archive_no}.jsonl",
            archive_lines,
        )
        artifact_id = self._insert_raw_artifact(
            source_app_id=session["source_app_id"],
            kind="session_archive",
            stored=stored,
            mime="application/jsonl",
            metadata={"session_id": session_id, "archive_no": archive_no},
        )
        l0, l1 = summarize_turns([dict(turn) for turn in turns])
        archive_id = new_id("arc")
        ts = now_iso()
        self.conn.execute(
            """
            INSERT INTO session_archive(
              id, session_id, archive_no, raw_artifact_id, raw_uri, l0_abstract,
              l1_overview, committed_at, commit_reason, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                archive_id,
                session_id,
                archive_no,
                artifact_id,
                stored.uri,
                l0,
                l1,
                ts,
                reason,
                json_dumps({"turns_hash": turns_hash, "turn_count": len(turns)}),
            ),
        )
        self.conn.execute(
            "UPDATE conversation_session SET status = 'committed', updated_at = ? WHERE id = ?",
            (ts, session_id),
        )
        self.conn.commit()
        memories = self.memory_service.extract_from_archive(archive_id, actor="dream")
        row = self.conn.execute("SELECT * FROM session_archive WHERE id = ?", (archive_id,)).fetchone()
        return {
            **dict(row),
            "metadata": json_loads(row["metadata_json"]),
            "created": True,
            "memories": memories,
        }

    def _persist_session(
        self,
        external: ExternalSession,
        adapter: JsonlTranscriptAdapter,
        *,
        source_id: str | None = None,
    ) -> dict[str, Any]:
        source_id = source_id or self._ensure_adapter_source(adapter)
        stored = self.store.copy_file("transcripts", external.path)
        artifact_id = self._insert_raw_artifact(
            source_app_id=source_id,
            kind="transcript",
            stored=stored,
            mime=guess_mime(external.path, "application/jsonl"),
            metadata={"external_session_id": external.external_session_id, **external.metadata},
        )
        turns = adapter.read_turns(external, {})
        project_path = external.project_path or self._detect_project_path(turns)
        workspace_id = ensure_workspace(self.conn, root_path=project_path) if project_path else ensure_workspace(
            self.conn, name="Default"
        )
        repo = self._detect_repo(project_path)
        existing = self.conn.execute(
            """
            SELECT id FROM conversation_session
            WHERE source_app_id = ? AND external_session_id = ?
            """,
            (source_id, external.external_session_id),
        ).fetchone()
        ts = now_iso()
        if existing:
            session_id = existing["id"]
            self.conn.execute(
                """
                UPDATE conversation_session
                SET workspace_id = ?, project_path = ?, repo = ?, ended_at = ?,
                    metadata_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    workspace_id,
                    project_path,
                    repo,
                    external.ended_at,
                    json_dumps({**external.metadata, "artifact_id": artifact_id}),
                    ts,
                    session_id,
                ),
            )
        else:
            session_id = new_id("ses")
            self.conn.execute(
                """
                INSERT INTO conversation_session(
                  id, source_app_id, workspace_id, external_session_id, project_path, repo,
                  started_at, ended_at, status, metadata_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                """,
                (
                    session_id,
                    source_id,
                    workspace_id,
                    external.external_session_id,
                    project_path,
                    repo,
                    external.started_at,
                    external.ended_at,
                    json_dumps({**external.metadata, "artifact_id": artifact_id}),
                    ts,
                ),
            )
        inserted_turns = self._persist_turns(session_id, turns, artifact_id)
        if inserted_turns:
            self.conn.execute(
                "UPDATE conversation_session SET status = 'active', updated_at = ? WHERE id = ?",
                (ts, session_id),
            )
        self.conn.commit()
        return {
            "id": session_id,
            "source_app_id": source_id,
            "source": adapter.source_name,
            "external_session_id": external.external_session_id,
            "path": str(external.path),
            "turn_count": len(turns),
            "inserted_turns": inserted_turns,
            "workspace_id": workspace_id,
            "project_path": project_path,
            "repo": repo,
        }

    def _ensure_adapter_source(self, adapter: JsonlTranscriptAdapter) -> str:
        return ensure_source_app(
            self.conn,
            name=adapter.source_name,
            app_type=adapter.source_type,
            config={"adapter": adapter.__class__.__name__},
        )

    def _find_session_id(self, source_id: str, external_session_id: str) -> str | None:
        row = self.conn.execute(
            """
            SELECT id
            FROM conversation_session
            WHERE source_app_id = ? AND external_session_id = ?
            """,
            (source_id, external_session_id),
        ).fetchone()
        return str(row["id"]) if row else None

    def _scan_session_result(
        self,
        session_id: str,
        *,
        source_id: str,
        external: ExternalSession,
        adapter: JsonlTranscriptAdapter,
        inserted_turns: int,
        skipped: bool = False,
    ) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT workspace_id, project_path, repo FROM conversation_session WHERE id = ?",
            (session_id,),
        ).fetchone()
        turn_count = self.conn.execute(
            "SELECT COUNT(*) AS count FROM conversation_turn WHERE session_id = ?",
            (session_id,),
        ).fetchone()["count"]
        return {
            "id": session_id,
            "source_app_id": source_id,
            "source": adapter.source_name,
            "external_session_id": external.external_session_id,
            "path": str(external.path),
            "turn_count": turn_count,
            "inserted_turns": inserted_turns,
            "workspace_id": row["workspace_id"] if row else None,
            "project_path": row["project_path"] if row else external.project_path,
            "repo": row["repo"] if row else None,
            "skipped": skipped,
        }

    def _sync_cursor_id(self, adapter: JsonlTranscriptAdapter) -> str:
        return f"dream:{adapter.source_name}"

    def _load_sync_cursor(self, source_id: str, adapter: JsonlTranscriptAdapter) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT cursor_json FROM sync_cursor WHERE id = ?",
            (self._sync_cursor_id(adapter),),
        ).fetchone()
        cursor = json_loads(row["cursor_json"] if row else None)
        if not isinstance(cursor, dict):
            cursor = {}
        cursor.setdefault("files", {})
        cursor["source_app_id"] = source_id
        return cursor

    def _save_sync_cursor(
        self,
        source_id: str,
        adapter: JsonlTranscriptAdapter,
        cursor: dict[str, Any],
    ) -> None:
        stored_cursor = {
            key: value
            for key, value in cursor.items()
            if not str(key).startswith("_") and key != "source_app_id"
        }
        stored_cursor.setdefault("files", {})
        ts = now_iso()
        self.conn.execute(
            """
            INSERT INTO sync_cursor(id, source_app_id, cursor_json, last_seen_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              source_app_id = excluded.source_app_id,
              cursor_json = excluded.cursor_json,
              last_seen_at = excluded.last_seen_at,
              updated_at = excluded.updated_at
            """,
            (
                self._sync_cursor_id(adapter),
                source_id,
                json_dumps(stored_cursor),
                ts,
                ts,
            ),
        )
        self.conn.commit()

    def _record_cursor_file(self, cursor: dict[str, Any], external: ExternalSession) -> None:
        signature = external.metadata.get("file_signature")
        cursor_key = external.metadata.get("cursor_key")
        if not isinstance(signature, dict) or not isinstance(cursor_key, str):
            return
        cursor.setdefault("files", {})[cursor_key] = {
            **signature,
            "external_session_id": external.external_session_id,
            "seen_at": now_iso(),
        }

    def _persist_turns(self, session_id: str, turns: list[RawTurn], artifact_id: str) -> int:
        inserted = 0
        for index, turn in enumerate(turns):
            turn_hash = sha256_text(f"{turn.role}:{clean_text(turn.content)}")
            turn_id = new_id("turn")
            cursor = self.conn.execute(
                """
                INSERT OR IGNORE INTO conversation_turn(
                  id, session_id, external_turn_id, role, content, parts_json, created_at,
                  token_count, raw_ref, hash
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    turn_id,
                    session_id,
                    turn.external_turn_id or f"turn-{index}",
                    turn.role,
                    turn.content,
                    json_dumps(turn.raw),
                    turn.created_at,
                    rough_token_count(turn.content),
                    artifact_id,
                    turn_hash,
                ),
            )
            inserted += cursor.rowcount
        return inserted

    def _insert_raw_artifact(
        self,
        *,
        source_app_id: str | None,
        kind: str,
        stored: StoredArtifact,
        mime: str,
        metadata: dict[str, Any],
    ) -> str:
        artifact_id = new_id("art")
        self.conn.execute(
            """
            INSERT INTO raw_artifact(
              id, source_app_id, kind, uri, checksum, mime, size, metadata_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact_id,
                source_app_id,
                kind,
                stored.uri,
                stored.checksum,
                mime,
                stored.size,
                json_dumps(metadata),
                now_iso(),
            ),
        )
        return artifact_id

    def _detect_project_path(self, turns: list[RawTurn]) -> str | None:
        for turn in turns:
            raw = turn.raw
            for key in ("cwd", "project_path", "workspace", "repo_path"):
                value = raw.get(key)
                if isinstance(value, str) and value:
                    return str(Path(value).expanduser().resolve())
            message = raw.get("message")
            if isinstance(message, dict):
                value = message.get("cwd") or message.get("project_path")
                if isinstance(value, str) and value:
                    return str(Path(value).expanduser().resolve())
        return None

    def _detect_repo(self, project_path: str | None) -> str | None:
        if not project_path:
            return None
        path = Path(project_path)
        for parent in [path, *path.parents]:
            if (parent / ".git").exists():
                return str(parent)
        return None

    def _session_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["metadata"] = json_loads(result.pop("metadata_json", None))
        return result


def summarize_turns(turns: list[dict[str, Any]]) -> tuple[str, str]:
    user_turns = [turn for turn in turns if turn["role"] == "user"]
    lead = user_turns[0]["content"] if user_turns else turns[0]["content"]
    l0 = clean_text(lead.replace("\n", " "))[:220]
    if len(turns) > 1:
        l0 = f"{l0} ({len(turns)} turns)"
    bullets: list[str] = []
    for turn in turns[:24]:
        content = clean_text(turn["content"].replace("\n", " "))
        bullets.append(f"- {turn['role']}: {content[:260]}")
    l1 = "\n".join(bullets)
    return l0, l1
