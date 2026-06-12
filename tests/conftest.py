from __future__ import annotations

import uuid

import pytest

from bhd_memory.database import open_db
from bhd_memory.indexing import QdrantIndexBackend
from bhd_memory.storage import ArtifactStore


@pytest.fixture()
def runtime(tmp_path):
    conn = open_db(tmp_path / "bhd.sqlite")
    index = QdrantIndexBackend(url=":memory:", collection_name=f"test_{uuid.uuid4().hex}")
    index.ensure_ready()
    store = ArtifactStore(tmp_path / "data")
    return conn, index, store

