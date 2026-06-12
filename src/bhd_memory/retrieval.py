from __future__ import annotations

import sqlite3
from typing import Any

from .indexing import IndexBackend, SearchHit
from .utils import json_loads, new_id, now_iso


class RetrievalService:
    def __init__(self, conn: sqlite3.Connection, index: IndexBackend) -> None:
        self.conn = conn
        self.index = index

    def retrieve(
        self,
        *,
        query: str,
        target_types: list[str] | None = None,
        workspace_id: str | None = None,
        scope: str | None = None,
        limit: int = 10,
        request_id: str | None = None,
    ) -> list[dict[str, Any]]:
        qdrant_targets = self._normalize_target_types(target_types)
        hits = self.index.search(
            query,
            target_types=qdrant_targets,
            filters={"status": "active"},
            limit=max(limit * 3, limit),
        )
        contexts: list[dict[str, Any]] = []
        for hit in hits:
            context = self._load_hit(hit, query=query, request_id=request_id or new_id("req"))
            if not context:
                continue
            if not self._context_allowed(context, workspace_id=workspace_id, scope=scope):
                continue
            contexts.append(context)
            if len(contexts) >= limit:
                break
        return contexts

    def _normalize_target_types(self, target_types: list[str] | None) -> list[str] | None:
        if not target_types:
            return ["memory", "chunk"]
        normalized: list[str] = []
        for item in target_types:
            if item in {"resource", "knowledge", "chunk"}:
                normalized.append("chunk")
            elif item in {"memory", "session"}:
                normalized.append("memory")
        return sorted(set(normalized)) or ["memory", "chunk"]

    def _load_hit(self, hit: SearchHit, *, query: str, request_id: str) -> dict[str, Any] | None:
        if hit.target_type == "memory":
            return self._load_memory(hit, query=query, request_id=request_id)
        if hit.target_type == "chunk":
            return self._load_chunk(hit)
        return None

    def _load_memory(self, hit: SearchHit, *, query: str, request_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM memory WHERE id = ?", (hit.target_id,)).fetchone()
        if not row or row["status"] != "active":
            return None
        self.conn.execute(
            "UPDATE memory SET last_used_at = ? WHERE id = ?",
            (now_iso(), hit.target_id),
        )
        self.conn.execute(
            """
            INSERT INTO memory_access_log(id, memory_id, request_id, query, used_in_response, created_at)
            VALUES (?, ?, ?, ?, 0, ?)
            """,
            (new_id("mal"), hit.target_id, request_id, query, now_iso()),
        )
        self.conn.commit()
        evidence_rows = self.conn.execute(
            """
            SELECT me.*, ct.content AS turn_content, ct.role AS turn_role, ra.uri AS artifact_uri
            FROM memory_evidence me
            LEFT JOIN conversation_turn ct ON ct.id = me.turn_id
            LEFT JOIN raw_artifact ra ON ra.id = me.artifact_id
            WHERE me.memory_id = ?
            LIMIT 5
            """,
            (hit.target_id,),
        ).fetchall()
        return {
            "id": row["id"],
            "type": "memory",
            "scope": row["scope"],
            "workspace_id": row["workspace_id"],
            "score": hit.score,
            "score_details": hit.score_details,
            "content": row["content"],
            "category": row["category"],
            "source": {"kind": "memory", "memory_id": row["id"]},
            "evidence": [dict(evidence) for evidence in evidence_rows],
            "load_more_uri": f"memory://{row['id']}",
        }

    def _load_chunk(self, hit: SearchHit) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT c.*, r.title AS resource_title, r.source_uri, r.status AS resource_status,
                   r.workspace_id, r.mime, rn.path AS node_path
            FROM chunk c
            JOIN resource r ON r.id = c.resource_id
            LEFT JOIN resource_node rn ON rn.id = c.node_id
            WHERE c.id = ?
            """,
            (hit.target_id,),
        ).fetchone()
        if not row or row["resource_status"] != "ready":
            return None
        metadata = json_loads(row["metadata_json"])
        return {
            "id": row["id"],
            "type": "resource",
            "scope": "workspace",
            "workspace_id": row["workspace_id"],
            "score": hit.score,
            "score_details": hit.score_details,
            "content": row["compiled_text"],
            "source": {
                "kind": "resource",
                "resource_id": row["resource_id"],
                "title": row["resource_title"],
                "uri": row["source_uri"],
                "path": metadata.get("path") or row["node_path"],
                "page": row["page"],
            },
            "evidence": [
                {
                    "resource_id": row["resource_id"],
                    "chunk_id": row["id"],
                    "source_uri": row["source_uri"],
                    "path": metadata.get("path") or row["node_path"],
                    "page": row["page"],
                }
            ],
            "load_more_uri": f"resource://{row['resource_id']}/chunk/{row['id']}",
        }

    def _context_allowed(
        self,
        context: dict[str, Any],
        *,
        workspace_id: str | None,
        scope: str | None,
    ) -> bool:
        if scope and context.get("scope") != scope:
            return False
        if not workspace_id:
            return True
        if context["type"] == "memory":
            return context.get("scope") == "global" or context.get("workspace_id") in {None, workspace_id}
        return context.get("workspace_id") == workspace_id

