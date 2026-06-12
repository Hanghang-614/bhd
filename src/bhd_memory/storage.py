from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from .utils import now_iso, safe_filename, sha256_bytes, sha256_file


@dataclass(frozen=True)
class StoredArtifact:
    path: Path
    uri: str
    checksum: str
    size: int


class ArtifactStore:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or os.environ.get("BHD_DATA_DIR", ".bhd")).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def write_bytes(self, kind: str, filename: str, data: bytes) -> StoredArtifact:
        checksum = sha256_bytes(data)
        directory = self.root / "artifacts" / kind / checksum[:2]
        directory.mkdir(parents=True, exist_ok=True)
        safe_name = safe_filename(filename)
        path = directory / f"{checksum[:16]}-{safe_name}"
        if not path.exists():
            path.write_bytes(data)
        return StoredArtifact(path=path, uri=str(path), checksum=checksum, size=len(data))

    def copy_file(self, kind: str, path: str | Path, filename: str | None = None) -> StoredArtifact:
        source = Path(path)
        checksum = sha256_file(source)
        directory = self.root / "artifacts" / kind / checksum[:2]
        directory.mkdir(parents=True, exist_ok=True)
        safe_name = safe_filename(filename or source.name)
        target = directory / f"{checksum[:16]}-{safe_name}"
        if not target.exists():
            shutil.copy2(source, target)
        return StoredArtifact(path=target, uri=str(target), checksum=checksum, size=target.stat().st_size)

    def write_jsonl(self, kind: str, filename: str, lines: list[str]) -> StoredArtifact:
        content = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
        return self.write_bytes(kind, filename, content)

    def dated_name(self, prefix: str, suffix: str = ".jsonl") -> str:
        return f"{prefix}-{now_iso().replace(':', '').replace('+', 'Z')}{suffix}"

