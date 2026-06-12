from __future__ import annotations

from bhd_memory.maintenance import MaintenanceService
from bhd_memory.memory import MemoryService
from bhd_memory.resources import ResourceService
from bhd_memory.retrieval import RetrievalService


def test_rebuild_index_from_sqlite_truth(runtime):
    conn, index, store = runtime
    MemoryService(conn, index).create_memory(
        content="Rebuild index should restore active memories.",
        scope="global",
        category="procedure",
    )
    ResourceService(conn, index, store).ingest_text(
        "Rebuild index should restore ready resource chunks.",
        title="Rebuild Resource",
    )

    result = MaintenanceService(conn, index, store).rebuild_index(clear=True)
    contexts = RetrievalService(conn, index).retrieve(query="restore ready resource", limit=5)

    assert result["memories_indexed"] == 1
    assert result["resources_reindexed"] == 1
    assert {item["type"] for item in contexts} == {"memory", "resource"}

