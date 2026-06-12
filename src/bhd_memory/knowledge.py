from __future__ import annotations

import re
import sqlite3
from typing import Any

from .resources import ResourceService
from .retrieval import RetrievalService
from .storage import ArtifactStore
from .indexing import IndexBackend
from .utils import json_loads


class KnowledgeService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        index: IndexBackend,
        store: ArtifactStore | None = None,
    ) -> None:
        self.conn = conn
        self.index = index
        self.store = store or ArtifactStore()

    def list(
        self,
        *,
        workspace_id: str | None = None,
        status: str = "ready",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return ResourceService(self.conn, self.index, self.store).list_resources(
            workspace_id=workspace_id,
            status=status,
            limit=limit,
        )

    def view(
        self,
        resource_id: str,
        *,
        chunk_id: str | None = None,
        include_chunks: bool = True,
    ) -> dict[str, Any] | None:
        if chunk_id:
            row = self.conn.execute(
                """
                SELECT c.*, r.title AS resource_title, r.source_uri, r.workspace_id
                FROM chunk c
                JOIN resource r ON r.id = c.resource_id
                WHERE c.id = ? AND c.resource_id = ? AND r.status = 'ready'
                """,
                (chunk_id, resource_id),
            ).fetchone()
            if not row:
                return None
            result = dict(row)
            result["metadata"] = json_loads(result.pop("metadata_json", None))
            return result
        return ResourceService(self.conn, self.index, self.store).get_resource(
            resource_id,
            include_chunks=include_chunks,
        )

    def grep(
        self,
        pattern: str,
        *,
        resource_id: str | None = None,
        workspace_id: str | None = None,
        limit: int = 50,
        ignore_case: bool = True,
    ) -> list[dict[str, Any]]:
        flags = re.IGNORECASE if ignore_case else 0
        regex = re.compile(pattern, flags=flags)
        clauses = ["r.status = 'ready'"]
        params: list[Any] = []
        if resource_id:
            clauses.append("r.id = ?")
            params.append(resource_id)
        if workspace_id:
            clauses.append("r.workspace_id = ?")
            params.append(workspace_id)
        where = " AND ".join(clauses)
        rows = self.conn.execute(
            f"""
            SELECT c.*, r.title AS resource_title, r.source_uri, r.workspace_id
            FROM chunk c
            JOIN resource r ON r.id = c.resource_id
            WHERE {where}
            ORDER BY r.updated_at DESC
            LIMIT 500
            """,
            params,
        ).fetchall()
        matches: list[dict[str, Any]] = []
        for row in rows:
            text = row["text"]
            for match in regex.finditer(text):
                start = max(0, match.start() - 100)
                end = min(len(text), match.end() + 100)
                matches.append(
                    {
                        "resource_id": row["resource_id"],
                        "chunk_id": row["id"],
                        "resource_title": row["resource_title"],
                        "source_uri": row["source_uri"],
                        "workspace_id": row["workspace_id"],
                        "match": match.group(0),
                        "snippet": text[start:end],
                        "page": row["page"],
                    }
                )
                if len(matches) >= limit:
                    return matches
        return matches

    def query(
        self,
        query: str,
        *,
        workspace_id: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        return RetrievalService(self.conn, self.index).retrieve(
            query=query,
            target_types=["resource"],
            workspace_id=workspace_id,
            limit=limit,
        )

