from __future__ import annotations

from bhd_memory.hooks import HookService
from bhd_memory.memory import MemoryService
from bhd_memory.retrieval import RetrievalService


def test_hook_capture_commit_and_recall(runtime, tmp_path):
    conn, index, store = runtime
    hooks = HookService(conn, index, store)

    captured = hooks.capture(
        source_app="codex_hook",
        external_session_id="cx-test",
        external_turn_id="u1",
        role="user",
        content="请记住：当前项目测试命令使用 uv run --extra dev pytest -q。",
        project_path=str(tmp_path),
    )
    committed = hooks.commit(
        source_app="codex_hook",
        external_session_id="cx-test",
        reason="precompact",
    )
    recalled = hooks.recall(
        query="测试命令",
        source_app="codex_hook",
        external_session_id="cx-test",
        target_types=["memory"],
        limit=3,
    )

    assert captured["inserted"] is True
    assert committed["created"] is True
    assert committed["memories"]
    assert recalled and recalled[0]["type"] == "memory"


def test_approving_conflict_supersedes_old_memory(runtime):
    conn, index, _store = runtime
    memory = MemoryService(conn, index)
    old = memory.create_memory(
        content="我偏好中文回复。",
        scope="global",
        category="preference",
    )
    new = memory.create_memory(
        content="我不再偏好中文回复，改为英文回复。",
        scope="global",
        category="preference",
        status="conflict",
    )

    approved = memory.approve_memory(new["id"], actor="test")
    old_after = memory.get_memory(old["id"])
    relations = memory.relations(new["id"])
    contexts = RetrievalService(conn, index).retrieve(
        query="中文回复",
        target_types=["memory"],
        limit=5,
    )

    assert approved["status"] == "active"
    assert old_after and old_after["status"] == "archived"
    assert old_after["invalid_at"] is not None
    assert relations and relations[0]["relation_type"] == "supersedes"
    assert all(item["id"] != old["id"] for item in contexts)

