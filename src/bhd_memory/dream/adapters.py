from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from ..utils import clean_text, sha256_text


@dataclass(frozen=True)
class ExternalSession:
    source_name: str
    source_type: str
    external_session_id: str
    path: Path
    project_path: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RawTurn:
    external_turn_id: str
    role: str
    content: str
    created_at: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class JsonlTranscriptAdapter:
    source_name = "jsonl"
    source_type = "generic"
    roots: list[Path] = []
    patterns = ["**/*.jsonl"]

    def detect(self) -> bool:
        return any(root.exists() for root in self.roots)

    def list_sessions(self, cursor: dict | None = None) -> list[ExternalSession]:
        cursor = cursor or {}
        file_cursor = cursor.get("files") if isinstance(cursor.get("files"), dict) else {}
        include_unchanged = bool(cursor.get("_include_unchanged"))
        skipped_paths: list[str] = []
        sessions: list[ExternalSession] = []
        for path in self._iter_paths():
            signature = self._file_signature(path)
            cursor_key = signature["path"]
            unchanged = _signature_matches(file_cursor.get(cursor_key), signature)
            if unchanged and not include_unchanged:
                skipped_paths.append(cursor_key)
                continue
            sessions.append(
                ExternalSession(
                    source_name=self.source_name,
                    source_type=self.source_type,
                    external_session_id=self._session_id(path),
                    path=path,
                    project_path=None,
                    metadata={
                        "path": str(path),
                        "cursor_key": cursor_key,
                        "cursor_unchanged": unchanged,
                        "file_signature": signature,
                    },
                )
            )
        cursor["_skipped_paths"] = skipped_paths
        return sessions

    def read_turns(self, session: ExternalSession, cursor: dict | None = None) -> list[RawTurn]:
        turns: list[RawTurn] = []
        for index, line in enumerate(session.path.read_text(encoding="utf-8", errors="replace").splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                payload = {"role": "unknown", "content": line}
            turn = self.normalize_turn(payload, index=index)
            if turn:
                turns.append(turn)
        return turns

    def normalize_turn(self, raw: dict[str, Any], *, index: int = 0) -> RawTurn | None:
        message = raw.get("message") if isinstance(raw.get("message"), dict) else {}
        item = raw.get("item") if isinstance(raw.get("item"), dict) else {}
        role = (
            raw.get("role")
            or message.get("role")
            or item.get("role")
            or raw.get("type")
            or raw.get("speaker")
            or raw.get("author")
            or "unknown"
        )
        role = _normalize_role(str(role))
        content = _extract_content(raw.get("content"))
        if not content and message:
            content = _extract_content(
                message.get("content")
                or message.get("text")
                or message.get("input")
                or message.get("output")
            )
        if not content and item:
            content = _extract_content(
                item.get("content") or item.get("text") or item.get("input") or item.get("output")
            )
        if not content:
            content = _extract_content(
                raw.get("text")
                or raw.get("prompt")
                or raw.get("response")
                or item.get("arguments")
                or message.get("arguments")
            )
        content = clean_text(content)
        if not content:
            return None
        created_at = (
            raw.get("created_at")
            or raw.get("timestamp")
            or raw.get("time")
            or message.get("created_at")
            or message.get("timestamp")
            or item.get("created_at")
            or item.get("timestamp")
        )
        external_turn_id = str(
            raw.get("id")
            or raw.get("uuid")
            or raw.get("turn_id")
            or raw.get("request_id")
            or message.get("id")
            or item.get("id")
            or f"line-{index}"
        )
        return RawTurn(
            external_turn_id=external_turn_id,
            role=role,
            content=content,
            created_at=str(created_at) if created_at else None,
            raw=raw,
        )

    def _iter_paths(self) -> Iterable[Path]:
        seen: set[Path] = set()
        for root in self.roots:
            if root.is_file():
                paths = [root]
            else:
                paths = []
                for pattern in self.patterns:
                    paths.extend(root.glob(pattern))
            for path in sorted(paths):
                if path.is_file() and path not in seen:
                    seen.add(path)
                    yield path

    def _session_id(self, path: Path) -> str:
        return sha256_text(str(path.resolve()))[:32]

    def _file_signature(self, path: Path) -> dict[str, Any]:
        stat = path.stat()
        return {
            "path": str(path.resolve()),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }


class GenericPathTranscriptAdapter(JsonlTranscriptAdapter):
    source_name = "generic_jsonl"
    source_type = "transcript"

    def __init__(self, paths: list[str | Path]) -> None:
        self.roots = [Path(path).expanduser() for path in paths]


class ClaudeCodeTranscriptAdapter(JsonlTranscriptAdapter):
    source_name = "claude_code"
    source_type = "transcript"

    def __init__(self) -> None:
        configured = os.environ.get("BHD_CLAUDE_TRANSCRIPT_DIRS")
        if configured:
            self.roots = [Path(item).expanduser() for item in configured.split(os.pathsep) if item]
        else:
            self.roots = [Path("~/.claude/projects").expanduser()]


class CodexTranscriptAdapter(JsonlTranscriptAdapter):
    source_name = "codex"
    source_type = "transcript"

    def __init__(self) -> None:
        configured = os.environ.get("BHD_CODEX_TRANSCRIPT_DIRS")
        if configured:
            self.roots = [Path(item).expanduser() for item in configured.split(os.pathsep) if item]
        else:
            self.roots = [
                Path("~/.codex/sessions").expanduser(),
                Path("~/.codex/conversations").expanduser(),
            ]


def _normalize_role(role: str) -> str:
    role = role.lower()
    if role in {"human", "user_message", "prompt"}:
        return "user"
    if role in {"assistant_message", "completion", "response"}:
        return "assistant"
    if role in {"tool_use", "tool_result", "function"}:
        return "tool"
    return role


def _extract_content(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if isinstance(item.get("text"), str):
                    parts.append(item["text"])
                elif isinstance(item.get("content"), str):
                    parts.append(item["content"])
                elif isinstance(item.get("input"), str):
                    parts.append(item["input"])
                elif isinstance(item.get("output"), str):
                    parts.append(item["output"])
        return "\n".join(parts)
    if isinstance(value, dict):
        for key in ("text", "content", "message", "input", "output", "arguments"):
            content = _extract_content(value.get(key))
            if content:
                return content
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _signature_matches(previous: Any, current: dict[str, Any]) -> bool:
    if not isinstance(previous, dict):
        return False
    return previous.get("size") == current.get("size") and previous.get("mtime_ns") == current.get(
        "mtime_ns"
    )
