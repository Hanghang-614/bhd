from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .dream import DreamService
from .indexing import IndexBackend
from .memory import MemoryService
from .repository import ensure_source_app, ensure_workspace
from .retrieval import RetrievalService
from .storage import ArtifactStore
from .utils import clean_text, json_dumps, json_loads, new_id, now_iso, rough_token_count, sha256_text


class HookService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        index: IndexBackend,
        store: ArtifactStore | None = None,
    ) -> None:
        self.conn = conn
        self.index = index
        self.store = store or ArtifactStore()

    def capture(
        self,
        *,
        source_app: str,
        external_session_id: str,
        role: str,
        content: str,
        external_turn_id: str | None = None,
        project_path: str | None = None,
        event_type: str = "hook_capture",
        created_at: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        content = clean_text(content)
        if not content:
            raise ValueError("content is required")
        source_id = ensure_source_app(
            self.conn,
            name=source_app,
            app_type="transcript_hook",
            config={"capture": "hook"},
        )
        workspace_id = ensure_workspace(root_path=project_path, conn=self.conn) if project_path else ensure_workspace(
            conn=self.conn,
            name="Default",
        )
        session_id = self._ensure_session(
            source_id=source_id,
            workspace_id=workspace_id,
            external_session_id=external_session_id,
            project_path=project_path,
            metadata={"hook_source": source_app},
        )
        turn_id = new_id("turn")
        ts = created_at or now_iso()
        raw = {
            "event_type": event_type,
            "metadata": metadata or {},
        }
        stable_turn_id = external_turn_id or sha256_text(
            f"{source_app}:{external_session_id}:{role}:{content}:{ts}"
        )[:32]
        cursor = self.conn.execute(
            """
            INSERT OR IGNORE INTO conversation_turn(
              id, session_id, external_turn_id, role, content, parts_json, created_at,
              token_count, raw_ref, hash
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                turn_id,
                session_id,
                stable_turn_id,
                _normalize_role(role),
                content,
                json_dumps(raw),
                ts,
                rough_token_count(content),
                sha256_text(f"{role}:{content}"),
            ),
        )
        self.conn.execute(
            "UPDATE conversation_session SET status = 'active', updated_at = ? WHERE id = ?",
            (ts, session_id),
        )
        self.conn.commit()
        return {
            "session_id": session_id,
            "turn_id": turn_id if cursor.rowcount else None,
            "inserted": bool(cursor.rowcount),
            "external_session_id": external_session_id,
            "external_turn_id": stable_turn_id,
        }

    def commit(
        self,
        *,
        source_app: str,
        external_session_id: str,
        reason: str = "hook_commit",
    ) -> dict[str, Any]:
        session = self._find_session(source_app=source_app, external_session_id=external_session_id)
        if not session:
            raise KeyError(f"session not found: {source_app}/{external_session_id}")
        memory = MemoryService(self.conn, self.index)
        dream = DreamService(self.conn, memory, self.store)
        return dream.commit_session(session["id"], reason=reason)

    def recall(
        self,
        *,
        query: str,
        source_app: str | None = None,
        external_session_id: str | None = None,
        project_path: str | None = None,
        target_types: list[str] | None = None,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        workspace_id: str | None = None
        if source_app and external_session_id:
            session = self._find_session(source_app=source_app, external_session_id=external_session_id)
            workspace_id = session["workspace_id"] if session else None
        if workspace_id is None and project_path:
            workspace_id = ensure_workspace(conn=self.conn, root_path=project_path)
        return RetrievalService(self.conn, self.index).retrieve(
            query=query,
            target_types=target_types,
            workspace_id=workspace_id,
            limit=limit,
        )

    def _ensure_session(
        self,
        *,
        source_id: str,
        workspace_id: str,
        external_session_id: str,
        project_path: str | None,
        metadata: dict[str, Any],
    ) -> str:
        row = self.conn.execute(
            """
            SELECT id FROM conversation_session
            WHERE source_app_id = ? AND external_session_id = ?
            """,
            (source_id, external_session_id),
        ).fetchone()
        ts = now_iso()
        if row:
            session_id = row["id"]
            self.conn.execute(
                """
                UPDATE conversation_session
                SET workspace_id = ?, project_path = ?, metadata_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (workspace_id, project_path, json_dumps(metadata), ts, session_id),
            )
            return session_id

        session_id = new_id("ses")
        self.conn.execute(
            """
            INSERT INTO conversation_session(
              id, source_app_id, workspace_id, external_session_id, project_path, repo,
              started_at, ended_at, status, metadata_json, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'active', ?, ?)
            """,
            (
                session_id,
                source_id,
                workspace_id,
                external_session_id,
                project_path,
                self._detect_repo(project_path),
                ts,
                json_dumps(metadata),
                ts,
            ),
        )
        return session_id

    def _find_session(self, *, source_app: str, external_session_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT cs.*
            FROM conversation_session cs
            JOIN source_app sa ON sa.id = cs.source_app_id
            WHERE sa.name = ? AND cs.external_session_id = ?
            """,
            (source_app, external_session_id),
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["metadata"] = json_loads(result.pop("metadata_json", None))
        return result

    def _detect_repo(self, project_path: str | None) -> str | None:
        if not project_path:
            return None
        path = Path(project_path)
        for parent in [path, *path.parents]:
            if (parent / ".git").exists():
                return str(parent)
        return None


def _normalize_role(role: str) -> str:
    role = role.lower()
    if role in {"human", "prompt"}:
        return "user"
    if role in {"completion", "response"}:
        return "assistant"
    if role in {"tool_use", "tool_result", "function"}:
        return "tool"
    return role

