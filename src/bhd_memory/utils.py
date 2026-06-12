from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


TOKEN_RE = re.compile(r"[A-Za-z0-9_./:-]+|[\u4e00-\u9fff]")


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: str | Path) -> str:
    hasher = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


def json_loads(value: str | bytes | None, default: Any = None) -> Any:
    if value in (None, ""):
        return {} if default is None else default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {} if default is None else default


def guess_mime(filename: str | Path, fallback: str = "application/octet-stream") -> str:
    guessed, _ = mimetypes.guess_type(str(filename))
    return guessed or fallback


def clean_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def word_tokens(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text)]


def rough_token_count(text: str) -> int:
    tokens = word_tokens(text)
    return max(1, len(tokens))


def normalize_for_hash(text: str) -> str:
    return " ".join(word_tokens(clean_text(text)))


def safe_filename(name: str, fallback: str = "artifact") -> str:
    name = os.path.basename(name).strip() or fallback
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", name)
    return name[:180] or fallback


def maybe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

