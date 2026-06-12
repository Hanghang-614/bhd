from __future__ import annotations

import json

from bhd_memory.dream import DreamService
from bhd_memory.memory import MemoryService
from bhd_memory.retrieval import RetrievalService


def test_dream_scan_commit_extracts_evidence_backed_memory(runtime, tmp_path):
    conn, index, store = runtime
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "u1",
                        "role": "user",
                        "content": "请记住：我偏好先给结论再展开分析。",
                        "cwd": str(tmp_path),
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "id": "a1",
                        "role": "assistant",
                        "content": "好的，我会按这个偏好回答。",
                    },
                    ensure_ascii=False,
                ),
            ]
        ),
        encoding="utf-8",
    )

    memory = MemoryService(conn, index)
    dream = DreamService(conn, memory, store)
    result = dream.scan(paths=[str(transcript)], auto_commit=True)
    session_id = result["scanned"][0]["sessions"][0]["id"]
    archive = dream.get_archive(session_id, 1)
    memories = memory.list_memories(status="active")
    contexts = RetrievalService(conn, index).retrieve(query="先给结论", target_types=["memory"], limit=3)

    assert result["scanned"][0]["sessions"][0]["inserted_turns"] == 2
    assert archive and len(archive["turns"]) == 2
    assert len(memories) == 1
    assert memories[0]["category"] == "preference"
    assert memory.evidence(memories[0]["id"])
    assert contexts and contexts[0]["id"] == memories[0]["id"]


def test_dream_idle_sweep_commits_active_session(runtime, tmp_path):
    conn, index, store = runtime
    transcript = tmp_path / "idle-session.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "id": "u1",
                "role": "user",
                "content": "当前项目约定使用 Qdrant 作为统一检索入口。",
                "cwd": str(tmp_path),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    memory = MemoryService(conn, index)
    dream = DreamService(conn, memory, store)
    scan = dream.scan(paths=[str(transcript)], auto_commit=False)
    sweep = dream.sweep_idle(idle_seconds=0)

    assert scan["scanned"][0]["sessions"][0]["inserted_turns"] == 1
    assert sweep["committed"]
    assert memory.list_memories(status="active")


def test_sensitive_dream_memory_goes_to_review(runtime, tmp_path):
    conn, index, store = runtime
    transcript = tmp_path / "sensitive.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "id": "u1",
                "role": "user",
                "content": "请记住：API token 是 secret-value。",
                "cwd": str(tmp_path),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    memory = MemoryService(conn, index)
    DreamService(conn, memory, store).scan(paths=[str(transcript)], auto_commit=True)

    pending = memory.review_queue()
    assert pending
    assert pending[0]["status"] == "pending"


def test_conflicting_dream_memory_goes_to_review(runtime, tmp_path):
    conn, index, store = runtime
    memory = MemoryService(conn, index)
    memory.create_memory(
        content="我偏好中文回复。",
        scope="global",
        category="preference",
    )
    transcript = tmp_path / "conflict.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "id": "u1",
                "role": "user",
                "content": "请记住：我不再偏好中文回复，改为英文回复。",
                "cwd": str(tmp_path),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    DreamService(conn, memory, store).scan(paths=[str(transcript)], auto_commit=True)

    review = memory.review_queue()
    assert any(item["status"] == "conflict" for item in review)
