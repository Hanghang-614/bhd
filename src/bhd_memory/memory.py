from __future__ import annotations

import re
import os
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from .indexing import IndexBackend
from .llm import LLMNotConfigured, OpenAICompatibleClient
from .repository import record_vector_index_item
from .utils import (
    clean_text,
    json_dumps,
    json_loads,
    new_id,
    normalize_for_hash,
    now_iso,
    rough_token_count,
    sha256_text,
)


@dataclass(frozen=True)
class MemoryEvidenceDraft:
    session_id: str | None = None
    turn_id: str | None = None
    artifact_id: str | None = None
    quote_ref: str | None = None
    confidence: float = 0.75


@dataclass(frozen=True)
class CandidateMemory:
    content: str
    category: str
    scope: str = "workspace"
    confidence: float = 0.72
    evidence_turn_ids: list[str] = field(default_factory=list)
    reasoning: str = "rule-based Dream observer"


class MemoryService:
    def __init__(self, conn: sqlite3.Connection, index: IndexBackend) -> None:
        self.conn = conn
        self.index = index

    def create_memory(
        self,
        *,
        content: str,
        scope: str = "global",
        category: str = "event",
        status: str = "active",
        confidence: float = 0.75,
        workspace_id: str | None = None,
        valid_at: str | None = None,
        metadata: dict[str, Any] | None = None,
        evidence: list[MemoryEvidenceDraft] | None = None,
        archive_id: str | None = None,
        reasoning: str | None = None,
        actor: str = "system",
    ) -> dict[str, Any]:
        content = clean_text(content)
        if not content:
            raise ValueError("memory content is required")
        memory_hash = sha256_text(normalize_for_hash(f"{scope}:{workspace_id or ''}:{category}:{content}"))
        existing = self.conn.execute(
            """
            SELECT * FROM memory
            WHERE hash = ? AND status IN ('active', 'pending', 'paused')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (memory_hash,),
        ).fetchone()
        if existing:
            return self._memory_dict(existing, created=False)

        memory_id = new_id("mem")
        ts = now_iso()
        self.conn.execute(
            """
            INSERT INTO memory(
              id, scope, workspace_id, category, content, status, confidence,
              valid_at, invalid_at, created_at, updated_at, metadata_json, hash
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)
            """,
            (
                memory_id,
                scope,
                workspace_id,
                category,
                content,
                status,
                confidence,
                valid_at,
                ts,
                ts,
                json_dumps(metadata or {}),
                memory_hash,
            ),
        )
        for draft in evidence or []:
            self.conn.execute(
                """
                INSERT INTO memory_evidence(
                  id, memory_id, session_id, turn_id, artifact_id, quote_ref, confidence
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id("mev"),
                    memory_id,
                    draft.session_id,
                    draft.turn_id,
                    draft.artifact_id,
                    draft.quote_ref,
                    draft.confidence,
                ),
            )
        self._insert_entities(memory_id, content)
        after = self.get_memory(memory_id) or {}
        self.conn.execute(
            """
            INSERT INTO memory_operation(
              id, archive_id, op, memory_id, before_json, after_json, reasoning, actor, created_at
            )
            VALUES (?, ?, 'create', ?, '{}', ?, ?, ?, ?)
            """,
            (
                new_id("mop"),
                archive_id,
                memory_id,
                json_dumps(after),
                reasoning,
                actor,
                ts,
            ),
        )
        self.conn.commit()
        if status == "active":
            self.index_memory(memory_id)
        return self.get_memory(memory_id) | {"created": True}

    def get_memory(self, memory_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM memory WHERE id = ?", (memory_id,)).fetchone()
        return self._memory_dict(row) if row else None

    def list_memories(
        self,
        *,
        status: str | None = None,
        scope: str | None = None,
        workspace_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if scope:
            clauses.append("scope = ?")
            params.append(scope)
        if workspace_id:
            clauses.append("workspace_id = ?")
            params.append(workspace_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"SELECT * FROM memory {where} ORDER BY updated_at DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [self._memory_dict(row) for row in rows]

    def update_memory(
        self,
        memory_id: str,
        *,
        content: str | None = None,
        status: str | None = None,
        category: str | None = None,
        scope: str | None = None,
        confidence: float | None = None,
        actor: str = "user",
        reasoning: str | None = None,
    ) -> dict[str, Any]:
        before = self.get_memory(memory_id)
        if not before:
            raise KeyError(f"memory not found: {memory_id}")

        next_values = {
            "content": clean_text(content) if content is not None else before["content"],
            "status": status or before["status"],
            "category": category or before["category"],
            "scope": scope or before["scope"],
            "confidence": confidence if confidence is not None else before["confidence"],
        }
        memory_hash = sha256_text(
            normalize_for_hash(
                f"{next_values['scope']}:{before.get('workspace_id') or ''}:"
                f"{next_values['category']}:{next_values['content']}"
            )
        )
        self.conn.execute(
            """
            UPDATE memory
            SET content = ?, status = ?, category = ?, scope = ?, confidence = ?,
                hash = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                next_values["content"],
                next_values["status"],
                next_values["category"],
                next_values["scope"],
                next_values["confidence"],
                memory_hash,
                now_iso(),
                memory_id,
            ),
        )
        self.conn.execute("DELETE FROM memory_entity WHERE memory_id = ?", (memory_id,))
        self._insert_entities(memory_id, next_values["content"])
        after = self.get_memory(memory_id) or {}
        self.conn.execute(
            """
            INSERT INTO memory_operation(
              id, op, memory_id, before_json, after_json, reasoning, actor, created_at
            )
            VALUES (?, 'update', ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id("mop"),
                memory_id,
                json_dumps(before),
                json_dumps(after),
                reasoning,
                actor,
                now_iso(),
            ),
        )
        self.conn.commit()
        if next_values["status"] == "active":
            self.index_memory(memory_id)
        else:
            self.index.delete("memory", memory_id)
            self.conn.execute(
                "DELETE FROM vector_index_item WHERE target_type = 'memory' AND target_id = ?",
                (memory_id,),
            )
            self.conn.commit()
        return self.get_memory(memory_id) or {}

    def delete_memory(self, memory_id: str, *, actor: str = "user") -> dict[str, Any]:
        return self.update_memory(memory_id, status="deleted", actor=actor, reasoning="soft delete")

    def review_queue(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT *
            FROM memory
            WHERE status IN ('pending', 'conflict')
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [self._memory_dict(row) for row in rows]

    def approve_memory(self, memory_id: str, *, actor: str = "user") -> dict[str, Any]:
        before = self.get_memory(memory_id)
        approved = self.update_memory(
            memory_id,
            status="active",
            actor=actor,
            reasoning="approved from review queue",
        )
        if before and before["status"] == "conflict":
            self._supersede_related_memories(approved, actor=actor)
            approved = self.get_memory(memory_id) or approved
        return approved

    def reject_memory(self, memory_id: str, *, actor: str = "user") -> dict[str, Any]:
        return self.update_memory(
            memory_id,
            status="archived",
            actor=actor,
            reasoning="rejected from review queue",
        )

    def relations(self, memory_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT mr.*, source.content AS source_content, target.content AS target_content
            FROM memory_relation mr
            JOIN memory source ON source.id = mr.source_memory_id
            JOIN memory target ON target.id = mr.target_memory_id
            WHERE mr.source_memory_id = ? OR mr.target_memory_id = ?
            ORDER BY mr.created_at DESC
            """,
            (memory_id, memory_id),
        ).fetchall()
        return [
            {
                **dict(row),
                "metadata": json_loads(row["metadata_json"]),
            }
            for row in rows
        ]

    def evidence(self, memory_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT me.*, ct.role, ct.content AS turn_content, ra.uri AS artifact_uri
            FROM memory_evidence me
            LEFT JOIN conversation_turn ct ON ct.id = me.turn_id
            LEFT JOIN raw_artifact ra ON ra.id = me.artifact_id
            WHERE me.memory_id = ?
            ORDER BY me.rowid
            """,
            (memory_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def operations(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM memory_operation ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {
                **dict(row),
                "before": json_loads(row["before_json"]),
                "after": json_loads(row["after_json"]),
            }
            for row in rows
        ]

    def index_memory(self, memory_id: str) -> None:
        memory = self.get_memory(memory_id)
        if not memory or memory["status"] != "active":
            return
        payload = {
            "scope": memory["scope"],
            "workspace_id": memory.get("workspace_id") or "",
            "category": memory["category"],
            "status": memory["status"],
            "created_at": memory["created_at"],
            "updated_at": memory["updated_at"],
        }
        vector_id = self.index.upsert("memory", memory_id, memory["content"], payload)
        record_vector_index_item(
            self.conn,
            target_type="memory",
            target_id=memory_id,
            vector_id=vector_id,
            index_name=self.index.index_name,
            embedding_model=getattr(self.index, "embedding_model", "unknown"),
        )
        self.conn.commit()

    def extract_from_archive(
        self,
        archive_id: str,
        *,
        max_candidates: int = 10,
        actor: str = "dream",
    ) -> list[dict[str, Any]]:
        archive = self.conn.execute(
            """
            SELECT sa.*, cs.id AS session_id, cs.workspace_id, cs.project_path
            FROM session_archive sa
            JOIN conversation_session cs ON cs.id = sa.session_id
            WHERE sa.id = ?
            """,
            (archive_id,),
        ).fetchone()
        if not archive:
            raise KeyError(f"archive not found: {archive_id}")

        session_id = archive["session_id"]
        turns = self.conn.execute(
            """
            SELECT id, role, content, created_at
            FROM conversation_turn
            WHERE session_id = ?
            ORDER BY created_at, external_turn_id
            """,
            (session_id,),
        ).fetchall()
        candidates = self._observe_candidates(turns)[:max_candidates]
        created: list[dict[str, Any]] = []
        for candidate in candidates:
            evidence = [
                MemoryEvidenceDraft(
                    session_id=session_id,
                    turn_id=turn_id,
                    quote_ref="dream-observer",
                    confidence=candidate.confidence,
                )
                for turn_id in candidate.evidence_turn_ids
            ]
            workspace_id = archive["workspace_id"] if candidate.scope == "workspace" else None
            status = self._status_for_candidate(candidate, workspace_id)
            created.append(
                self.create_memory(
                    content=candidate.content,
                    scope=candidate.scope,
                    category=candidate.category,
                    status=status,
                    confidence=candidate.confidence,
                    workspace_id=workspace_id,
                    evidence=evidence,
                    archive_id=archive_id,
                    reasoning=candidate.reasoning,
                    actor=actor,
                    metadata={"observer": candidate.reasoning.split(":", 1)[0]},
                )
            )
        return created

    def _observe_candidates(self, turns: list[sqlite3.Row]) -> list[CandidateMemory]:
        mode = os.environ.get("BHD_MEMORY_OBSERVER", "rule").lower()
        if mode in {"llm", "hybrid"}:
            try:
                llm_candidates = self._observe_candidates_with_llm(turns)
            except (LLMNotConfigured, OSError, ValueError, KeyError):
                llm_candidates = []
            if mode == "llm" and llm_candidates:
                return llm_candidates
            if mode == "hybrid" and llm_candidates:
                return self._merge_candidates(llm_candidates, self._observe_candidates_with_rules(turns))
        return self._observe_candidates_with_rules(turns)

    def _observe_candidates_with_rules(self, turns: list[sqlite3.Row]) -> list[CandidateMemory]:
        candidates: list[CandidateMemory] = []
        seen_hashes: set[str] = set()
        for turn in turns:
            if turn["role"] not in {"user", "human"}:
                continue
            for sentence in _split_sentences(turn["content"]):
                candidate = self._candidate_from_sentence(sentence, turn["id"])
                if not candidate:
                    continue
                dedup = sha256_text(normalize_for_hash(candidate.content))
                if dedup in seen_hashes:
                    continue
                seen_hashes.add(dedup)
                candidates.append(candidate)
        return candidates

    def _observe_candidates_with_llm(self, turns: list[sqlite3.Row]) -> list[CandidateMemory]:
        client = OpenAICompatibleClient.from_env()
        turn_payload = [
            {
                "turn_id": turn["id"],
                "role": turn["role"],
                "content": clean_text(turn["content"])[:1800],
                "created_at": turn["created_at"],
            }
            for turn in turns[:80]
        ]
        response = client.chat_json(
            [
                {
                    "role": "system",
                    "content": (
                        "You extract durable personal/project memories from developer transcripts. "
                        "Return JSON with a 'candidates' array. Each item must include content, "
                        "category, scope, confidence, evidence_turn_ids, and reasoning. "
                        "Only save future-useful facts. Do not treat assistant suggestions as user facts. "
                        "Use categories profile, preference, entity, event, procedure, or lesson. "
                        "Use scope global, workspace, session, or agent."
                    ),
                },
                {
                    "role": "user",
                    "content": json_dumps({"turns": turn_payload}),
                },
            ]
        )
        raw_candidates = response.get("candidates", response if isinstance(response, list) else [])
        valid_turn_ids = {turn["id"] for turn in turns}
        turn_roles = {turn["id"]: turn["role"] for turn in turns}
        candidates: list[CandidateMemory] = []
        for item in raw_candidates:
            if not isinstance(item, dict):
                continue
            content = clean_text(str(item.get("content") or ""))
            if not content:
                continue
            evidence_turn_ids = [
                str(turn_id)
                for turn_id in item.get("evidence_turn_ids", [])
                if str(turn_id) in valid_turn_ids
            ]
            if not evidence_turn_ids:
                continue
            category = _safe_choice(
                item.get("category"),
                {"profile", "preference", "entity", "event", "procedure", "lesson"},
                "event",
            )
            scope = _safe_choice(
                item.get("scope"),
                {"global", "workspace", "session", "agent"},
                "workspace",
            )
            if not _evidence_allowed_for_candidate(category, scope, evidence_turn_ids, turn_roles):
                continue
            candidates.append(
                CandidateMemory(
                    content=content,
                    category=category,
                    scope=scope,
                    confidence=float(item.get("confidence", 0.65)),
                    evidence_turn_ids=evidence_turn_ids,
                    reasoning=f"llm-observer-v1: {item.get('reasoning', '')}",
                )
            )
        return candidates

    def _merge_candidates(
        self,
        primary: list[CandidateMemory],
        secondary: list[CandidateMemory],
    ) -> list[CandidateMemory]:
        merged: list[CandidateMemory] = []
        seen: set[str] = set()
        for candidate in [*primary, *secondary]:
            key = sha256_text(normalize_for_hash(candidate.content))
            if key in seen:
                continue
            seen.add(key)
            merged.append(candidate)
        return merged

    def _status_for_candidate(self, candidate: CandidateMemory, workspace_id: str | None) -> str:
        if candidate.confidence < 0.7 or _is_sensitive(candidate.content):
            return "pending"
        if _looks_like_conflict(candidate.content) and self._has_related_active_memory(candidate, workspace_id):
            return "conflict"
        return "active"

    def _has_related_active_memory(
        self,
        candidate: CandidateMemory,
        workspace_id: str | None,
    ) -> bool:
        tokens = set(normalize_for_hash(candidate.content).split())
        if not tokens:
            return False
        rows = self.conn.execute(
            """
            SELECT content
            FROM memory
            WHERE status = 'active' AND category = ? AND scope = ?
              AND ((workspace_id IS NULL AND ? IS NULL) OR workspace_id = ?)
            LIMIT 50
            """,
            (candidate.category, candidate.scope, workspace_id, workspace_id),
        ).fetchall()
        for row in rows:
            existing_tokens = set(normalize_for_hash(row["content"]).split())
            if len(tokens & existing_tokens) >= 2:
                return True
        return False

    def _related_active_memories(self, memory: dict[str, Any]) -> list[sqlite3.Row]:
        tokens = set(normalize_for_hash(memory["content"]).split())
        if not tokens:
            return []
        rows = self.conn.execute(
            """
            SELECT *
            FROM memory
            WHERE id != ? AND status = 'active' AND category = ? AND scope = ?
              AND ((workspace_id IS NULL AND ? IS NULL) OR workspace_id = ?)
            LIMIT 50
            """,
            (
                memory["id"],
                memory["category"],
                memory["scope"],
                memory.get("workspace_id"),
                memory.get("workspace_id"),
            ),
        ).fetchall()
        related: list[sqlite3.Row] = []
        for row in rows:
            existing_tokens = set(normalize_for_hash(row["content"]).split())
            if len(tokens & existing_tokens) >= 2:
                related.append(row)
        return related

    def _supersede_related_memories(self, memory: dict[str, Any], *, actor: str) -> None:
        ts = now_iso()
        for row in self._related_active_memories(memory):
            before = self._memory_dict(row)
            self.conn.execute(
                """
                UPDATE memory
                SET status = 'archived', invalid_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (ts, ts, row["id"]),
            )
            after = self.get_memory(row["id"]) or {}
            self.conn.execute(
                """
                INSERT OR IGNORE INTO memory_relation(
                  id, source_memory_id, target_memory_id, relation_type, metadata_json, created_at
                )
                VALUES (?, ?, ?, 'supersedes', ?, ?)
                """,
                (
                    new_id("mrel"),
                    memory["id"],
                    row["id"],
                    json_dumps({"reason": "conflict approved", "actor": actor}),
                    ts,
                ),
            )
            self.conn.execute(
                """
                INSERT INTO memory_operation(
                  id, op, memory_id, before_json, after_json, reasoning, actor, created_at
                )
                VALUES (?, 'invalidate', ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id("mop"),
                    row["id"],
                    json_dumps(before),
                    json_dumps(after),
                    f"superseded by {memory['id']}",
                    actor,
                    ts,
                ),
            )
            self.index.delete("memory", row["id"])
            self.conn.execute(
                "DELETE FROM vector_index_item WHERE target_type = 'memory' AND target_id = ?",
                (row["id"],),
            )
        self.conn.commit()

    def _candidate_from_sentence(self, sentence: str, turn_id: str) -> CandidateMemory | None:
        text = clean_text(sentence)
        if len(text) < 8 or rough_token_count(text) < 3:
            return None
        lowered = text.lower()
        trigger_patterns = [
            r"记住",
            r"以后",
            r"偏好",
            r"喜欢",
            r"希望",
            r"不要",
            r"请先",
            r"当前项目",
            r"这个项目",
            r"使用",
            r"采用",
            r"约定",
            r"测试",
            r"部署",
            r"流程",
            r"my preference",
            r"remember",
            r"prefer",
        ]
        if not any(re.search(pattern, lowered) for pattern in trigger_patterns):
            return None

        category = "event"
        scope = "workspace"
        if re.search(r"偏好|喜欢|希望|不要|请先|prefer|preference", lowered):
            category = "preference"
            scope = "global"
        if re.search(r"命令|测试|部署|流程|约定|使用|采用|run|test|deploy", lowered):
            category = "procedure"
        if re.search(r"我是|我的身份|my role|i am", lowered):
            category = "profile"
            scope = "global"
        if re.search(r"当前项目|这个项目|repo|repository|workspace", lowered):
            scope = "workspace"

        content = re.sub(r"^(请)?记住[:：\s]*", "", text).strip()
        return CandidateMemory(
            content=content,
            category=category,
            scope=scope,
            confidence=0.76,
            evidence_turn_ids=[turn_id],
            reasoning="matched explicit memory/procedure/preference trigger",
        )

    def _insert_entities(self, memory_id: str, content: str) -> None:
        entities = extract_entities(content)
        for entity_text, entity_type in entities:
            self.conn.execute(
                """
                INSERT INTO memory_entity(id, memory_id, entity_text, entity_type, normalized, canonical_id)
                VALUES (?, ?, ?, ?, ?, NULL)
                """,
                (new_id("ent"), memory_id, entity_text, entity_type, entity_text.lower()),
            )

    def _memory_dict(self, row: sqlite3.Row, *, created: bool | None = None) -> dict[str, Any]:
        result = dict(row)
        result["metadata"] = json_loads(result.pop("metadata_json", None))
        if created is not None:
            result["created"] = created
        return result


def extract_entities(text: str) -> list[tuple[str, str]]:
    entities: list[tuple[str, str]] = []
    for value in re.findall(r"`([^`]{2,120})`", text):
        entities.append((value.strip(), "code"))
    for value in re.findall(r"\b[A-Z][A-Za-z0-9_-]{2,}\b", text):
        entities.append((value, "term"))
    for value in re.findall(r"[\w./-]+/[\w./-]+", text):
        entities.append((value, "path"))

    deduped: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for entity in entities:
        key = (entity[0].lower(), entity[1])
        if key not in seen:
            seen.add(key)
            deduped.append(entity)
    return deduped[:20]


def _split_sentences(text: str) -> list[str]:
    normalized = clean_text(text)
    parts = re.split(r"(?<=[。！？!?])\s+|\n+", normalized)
    return [part.strip() for part in parts if part.strip()]


def _safe_choice(value: Any, allowed: set[str], fallback: str) -> str:
    normalized = str(value or "").lower()
    return normalized if normalized in allowed else fallback


def _evidence_allowed_for_candidate(
    category: str,
    scope: str,
    evidence_turn_ids: list[str],
    turn_roles: dict[str, str],
) -> bool:
    roles = {turn_roles.get(turn_id, "unknown") for turn_id in evidence_turn_ids}
    if roles & {"user", "human"}:
        return True
    if scope == "agent" or category in {"procedure", "lesson"}:
        return bool(roles & {"assistant", "tool", "function"})
    return False


def _is_sensitive(text: str) -> bool:
    return bool(
        re.search(
            r"密钥|密码|token|api[_ -]?key|secret|身份证|银行卡|财务|健康|病历|客户隐私",
            text,
            flags=re.IGNORECASE,
        )
    )


def _looks_like_conflict(text: str) -> bool:
    return bool(re.search(r"不再|改为|替换|停止|不要再|no longer|instead of|replace", text, flags=re.IGNORECASE))
