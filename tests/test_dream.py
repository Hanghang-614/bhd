from __future__ import annotations

import json

from bhd_memory.dream import CodexTranscriptAdapter, DreamService
from bhd_memory.memory import MemoryService
from bhd_memory import memory as memory_module
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


def test_dream_scan_uses_file_cursor_and_rescans_changed_file(runtime, tmp_path):
    conn, index, store = runtime
    transcript = tmp_path / "cursor-session.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "id": "u1",
                "role": "user",
                "content": "请记住：当前项目约定使用 SQLite 保存事实库。",
                "cwd": str(tmp_path),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    dream = DreamService(conn, MemoryService(conn, index), store)
    first = dream.scan(paths=[str(transcript)], auto_commit=False)
    second = dream.scan(paths=[str(transcript)], auto_commit=False)
    transcript.write_text(
        transcript.read_text(encoding="utf-8")
        + "\n"
        + json.dumps(
            {
                "id": "u2",
                "role": "user",
                "content": "当前项目测试命令使用 uv run pytest。",
                "cwd": str(tmp_path),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    third = dream.scan(paths=[str(transcript)], auto_commit=False)
    cursor = conn.execute(
        "SELECT cursor_json FROM sync_cursor WHERE id = 'dream:generic_jsonl'"
    ).fetchone()

    assert first["scanned"][0]["sessions"][0]["inserted_turns"] == 1
    assert second["scanned"][0]["sessions"] == []
    assert second["scanned"][0]["skipped_sessions"] == 1
    assert third["scanned"][0]["sessions"][0]["inserted_turns"] == 1
    assert third["scanned"][0]["sessions"][0]["turn_count"] == 2
    assert cursor and str(transcript.resolve()) in json.loads(cursor["cursor_json"])["files"]


def test_dream_auto_commit_can_commit_unchanged_active_session(runtime, tmp_path):
    conn, index, store = runtime
    transcript = tmp_path / "commit-after-scan.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "id": "u1",
                "role": "user",
                "content": "请记住：当前项目测试命令使用 uv run pytest。",
                "cwd": str(tmp_path),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    memory = MemoryService(conn, index)
    dream = DreamService(conn, memory, store)
    dream.scan(paths=[str(transcript)], auto_commit=False)
    committed = dream.scan(paths=[str(transcript)], auto_commit=True)

    session = committed["scanned"][0]["sessions"][0]
    assert session["skipped"] is True
    assert session["archive"]["created"] is True
    assert memory.list_memories(status="active")


def test_changed_committed_session_becomes_active_for_idle_sweep(runtime, tmp_path):
    conn, index, store = runtime
    transcript = tmp_path / "changed-committed.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "id": "u1",
                "role": "user",
                "content": "请记住：当前项目约定使用 Qdrant 检索。",
                "cwd": str(tmp_path),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    dream = DreamService(conn, MemoryService(conn, index), store)
    first = dream.scan(paths=[str(transcript)], auto_commit=True)
    session_id = first["scanned"][0]["sessions"][0]["id"]
    transcript.write_text(
        transcript.read_text(encoding="utf-8")
        + "\n"
        + json.dumps(
            {
                "id": "u2",
                "role": "user",
                "content": "当前项目部署流程使用 start.sh。",
                "cwd": str(tmp_path),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    changed = dream.scan(paths=[str(transcript)], auto_commit=False)
    active = dream.get_session(session_id)
    sweep = dream.sweep_idle(idle_seconds=0)

    assert changed["scanned"][0]["sessions"][0]["inserted_turns"] == 1
    assert active and active["status"] == "active"
    assert sweep["committed"][0]["archive_no"] == 2


def test_codex_nested_item_turn_normalizes_content_and_role():
    turn = CodexTranscriptAdapter().normalize_turn(
        {
            "type": "response_item",
            "item": {
                "id": "item-1",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Done with the implementation."}],
                "timestamp": "2026-06-12T00:00:00Z",
            },
        }
    )

    assert turn is not None
    assert turn.external_turn_id == "item-1"
    assert turn.role == "assistant"
    assert turn.content == "Done with the implementation."


def test_llm_observer_rejects_user_memory_without_user_evidence(runtime, tmp_path, monkeypatch):
    conn, index, store = runtime
    transcript = tmp_path / "assistant-only.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "id": "a1",
                "role": "assistant",
                "content": "The user prefers very terse answers.",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    class FakeClient:
        def chat_json(self, messages):
            payload = json.loads(messages[1]["content"])
            turn_id = payload["turns"][0]["turn_id"]
            return {
                "candidates": [
                    {
                        "content": "The user prefers very terse answers.",
                        "category": "preference",
                        "scope": "global",
                        "confidence": 0.92,
                        "evidence_turn_ids": [turn_id],
                        "reasoning": "assistant-only claim should not become user memory",
                    }
                ]
            }

    monkeypatch.setenv("BHD_MEMORY_OBSERVER", "llm")
    monkeypatch.setattr(
        memory_module.OpenAICompatibleClient,
        "from_env",
        staticmethod(lambda: FakeClient()),
    )

    memory = MemoryService(conn, index)
    DreamService(conn, memory, store).scan(paths=[str(transcript)], auto_commit=True)

    assert memory.list_memories() == []
