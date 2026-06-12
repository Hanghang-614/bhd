from __future__ import annotations

from bhd_memory.memory import MemoryService
from bhd_memory.retrieval import RetrievalService


def test_memory_is_written_to_qdrant_and_retrieved(runtime):
    conn, index, _store = runtime
    memory = MemoryService(conn, index)
    created = memory.create_memory(
        content="用户偏好先给结论，再展开关键细节。",
        scope="global",
        category="preference",
        confidence=0.9,
    )

    contexts = RetrievalService(conn, index).retrieve(query="先给结论", target_types=["memory"], limit=3)

    assert created["created"] is True
    assert contexts
    assert contexts[0]["id"] == created["id"]
    assert contexts[0]["type"] == "memory"
    assert contexts[0]["source"]["kind"] == "memory"

