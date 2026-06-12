from __future__ import annotations

from bhd_memory.graph import GraphService
from bhd_memory.memory import MemoryService
from bhd_memory.resources import ResourceService


def test_graph_sync_creates_episodes_entities_and_supersedes_edges(runtime):
    conn, index, store = runtime
    memory = MemoryService(conn, index)
    old = memory.create_memory(
        content="Graphiti temporal layer tracks Qdrant facts.",
        scope="global",
        category="procedure",
    )
    new = memory.create_memory(
        content="Graphiti temporal layer no longer tracks only Qdrant facts.",
        scope="global",
        category="procedure",
        status="conflict",
    )
    memory.approve_memory(new["id"], actor="test")
    resource = ResourceService(conn, index, store).ingest_text(
        "Graph episodes preserve provenance for uploaded knowledge.",
        title="Graph Note",
    )

    graph = GraphService(conn)
    result = graph.sync_all()
    episodes = graph.list_episodes()
    entities = graph.search_entities("Graphiti")
    memory_episode = next(item for item in episodes if item["target_id"] == new["id"])
    full_episode = graph.get_episode(memory_episode["id"])

    assert result["memories_synced"] == 2
    assert result["chunks_synced"] == len(resource["chunks"])
    assert any(item["target_id"] == old["id"] for item in episodes)
    assert entities
    assert full_episode and full_episode["entities"]
    assert any(edge["relation_type"] == "supersedes" for edge in full_episode["edges"])

