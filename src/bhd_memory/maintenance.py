from __future__ import annotations

import sqlite3
from typing import Any

from .indexing import IndexBackend
from .memory import MemoryService
from .resources import ResourceService
from .storage import ArtifactStore


class MaintenanceService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        index: IndexBackend,
        store: ArtifactStore | None = None,
    ) -> None:
        self.conn = conn
        self.index = index
        self.store = store or ArtifactStore()

    def rebuild_index(self, *, clear: bool = False) -> dict[str, Any]:
        index_name = getattr(self.index, "index_name", "unknown")
        if clear and hasattr(self.index, "reset"):
            self.index.reset()  # type: ignore[attr-defined]
            self.conn.execute("DELETE FROM vector_index_item WHERE index_name = ?", (index_name,))
            self.conn.commit()
        else:
            self.index.ensure_ready()

        memory_service = MemoryService(self.conn, self.index)
        resource_service = ResourceService(self.conn, self.index, self.store)

        memory_rows = self.conn.execute(
            "SELECT id FROM memory WHERE status = 'active' ORDER BY updated_at"
        ).fetchall()
        resource_rows = self.conn.execute(
            "SELECT id FROM resource WHERE status = 'ready' ORDER BY updated_at"
        ).fetchall()

        for row in memory_rows:
            memory_service.index_memory(row["id"])
        for row in resource_rows:
            resource_service.reindex_resource(row["id"])

        return {
            "index_name": index_name,
            "cleared": clear,
            "memories_indexed": len(memory_rows),
            "resources_reindexed": len(resource_rows),
        }

