from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    db_path: Path
    data_dir: Path
    qdrant_url: str
    qdrant_collection: str
    embedding_dim: int

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            db_path=Path(os.environ.get("BHD_DB_PATH", ".bhd/bhd.sqlite")),
            data_dir=Path(os.environ.get("BHD_DATA_DIR", ".bhd")),
            qdrant_url=os.environ.get("BHD_QDRANT_URL", "http://127.0.0.1:6333"),
            qdrant_collection=os.environ.get("BHD_QDRANT_COLLECTION", "bhd_context"),
            embedding_dim=int(os.environ.get("BHD_EMBEDDING_DIM", "384")),
        )

