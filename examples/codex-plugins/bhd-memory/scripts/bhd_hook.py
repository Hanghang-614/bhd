#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any


def main() -> int:
    action = sys.argv[1] if len(sys.argv) > 1 else "recall"
    payload = read_payload()
    source_app = os.environ.get("BHD_HOOK_SOURCE_APP", "codex_hook")
    session_id = first_text(
        os.environ.get("BHD_HOOK_SESSION_ID"),
        os.environ.get("CODEX_SESSION_ID"),
        lookup(payload, "session_id"),
        lookup(payload, "codex_session_id"),
        lookup(payload, "conversation_id"),
        lookup(payload, "id"),
        "default",
    )
    project_path = first_text(
        os.environ.get("BHD_HOOK_PROJECT_PATH"),
        os.environ.get("PWD"),
        lookup(payload, "cwd"),
        lookup(payload, "project_path"),
        lookup(payload, "workspace"),
    )

    if action == "recall":
        query = extract_query(payload)
        if not query:
            return 0
        result = run_bhd(
            [
                "hook-recall",
                query,
                "--source-app",
                source_app,
                "--session-id",
                session_id,
                "--limit",
                os.environ.get("BHD_HOOK_RECALL_LIMIT", "6"),
                *optional("--project-path", project_path),
            ]
        )
        contexts = json.loads(result.stdout or "[]")
        if contexts:
            print(format_contexts(contexts))
        return 0

    if action == "capture":
        captured = 0
        for role, content in extract_turns(payload):
            run_bhd(
                [
                    "hook-capture",
                    "--source-app",
                    source_app,
                    "--session-id",
                    session_id,
                    "--role",
                    role,
                    "--content",
                    content,
                    "--event-type",
                    "codex_stop",
                    *optional("--project-path", project_path),
                ],
                check=False,
            )
            captured += 1
        if captured:
            print(f"BHD Memory captured {captured} turn(s).")
        return 0

    if action == "commit":
        run_bhd(
            [
                "hook-commit",
                "--source-app",
                source_app,
                "--session-id",
                session_id,
                "--reason",
                "precompact",
            ],
            check=False,
        )
        return 0

    if action == "sweep":
        run_bhd(["dream-sweep", "--idle-seconds", os.environ.get("BHD_HOOK_IDLE_SECONDS", "1800")], check=False)
        return 0

    print(f"unknown action: {action}", file=sys.stderr)
    return 2


def read_payload() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"text": raw}
    return parsed if isinstance(parsed, dict) else {"payload": parsed}


def lookup(payload: dict[str, Any], key: str) -> Any:
    if key in payload:
        return payload[key]
    for value in payload.values():
        if isinstance(value, dict) and key in value:
            return value[key]
    return None


def first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def optional(flag: str, value: str | None) -> list[str]:
    return [flag, value] if value else []


def extract_query(payload: dict[str, Any]) -> str:
    return first_text(
        lookup(payload, "prompt"),
        lookup(payload, "user_prompt"),
        lookup(payload, "input"),
        lookup(payload, "query"),
        lookup(payload, "content"),
        lookup(payload, "text"),
    )


def extract_turns(payload: dict[str, Any]) -> list[tuple[str, str]]:
    turns: list[tuple[str, str]] = []
    messages = lookup(payload, "messages")
    if isinstance(messages, list):
        for item in messages[-4:]:
            if not isinstance(item, dict):
                continue
            role = first_text(item.get("role"), item.get("type"), "user")
            content = first_text(item.get("content"), item.get("text"))
            if content:
                turns.append((normalize_role(role), content))
    user_text = first_text(lookup(payload, "prompt"), lookup(payload, "user_prompt"), lookup(payload, "input"))
    assistant_text = first_text(lookup(payload, "response"), lookup(payload, "assistant_response"), lookup(payload, "output"))
    if user_text:
        turns.append(("user", user_text))
    if assistant_text:
        turns.append(("assistant", assistant_text))
    if not turns:
        text = first_text(lookup(payload, "content"), lookup(payload, "text"))
        if text:
            turns.append(("user", text))
    deduped: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for role, content in turns:
        key = (role, content)
        if key not in seen:
            seen.add(key)
            deduped.append(key)
    return deduped


def normalize_role(role: str) -> str:
    role = role.lower()
    if role in {"human", "prompt"}:
        return "user"
    if role in {"completion", "response"}:
        return "assistant"
    return role


def run_bhd(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    command = [os.environ.get("BHD_MEMORY_BIN", "bhd-memory"), *args]
    try:
        result = subprocess.run(command, text=True, capture_output=True, check=check)
    except FileNotFoundError:
        fallback = ["uv", "run", "bhd-memory", *args]
        result = subprocess.run(fallback, text=True, capture_output=True, check=check)
    if result.stderr and os.environ.get("BHD_HOOK_DEBUG"):
        print(result.stderr, file=sys.stderr)
    return result


def format_contexts(contexts: list[dict[str, Any]]) -> str:
    lines = ["BHD Memory Context:"]
    for index, item in enumerate(contexts, start=1):
        source = item.get("source") or {}
        label = source.get("title") or source.get("kind") or item.get("type")
        lines.append(f"{index}. [{item.get('type')}] {label}")
        lines.append(str(item.get("content", "")).strip())
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())

