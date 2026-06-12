from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from bhd_memory.api import create_app
from bhd_memory.config import Settings
from bhd_memory.database import open_db
from bhd_memory.indexing import QdrantIndexBackend


def test_api_text_resource_memory_and_retrieve(tmp_path):
    settings = Settings(
        db_path=tmp_path / "bhd.sqlite",
        data_dir=tmp_path / "data",
        qdrant_url=":memory:",
        qdrant_collection=f"api_{uuid.uuid4().hex}",
        embedding_dim=384,
    )
    conn = open_db(settings.db_path)
    index = QdrantIndexBackend(
        url=settings.qdrant_url,
        collection_name=settings.qdrant_collection,
        embedding_dim=settings.embedding_dim,
    )
    app = create_app(settings=settings, conn=conn, index=index)
    client = TestClient(app)

    memory_response = client.post(
        "/api/memories",
        json={
            "content": "用户偏好中文回复。",
            "scope": "global",
            "category": "preference",
        },
    )
    resource_response = client.post(
        "/api/resources/text",
        json={
            "title": "Search Design",
            "text": "Qdrant stores dense and sparse vectors for retrieval.",
        },
    )
    retrieve_response = client.post(
        "/api/retrieve",
        json={"query": "dense sparse vectors", "target_types": ["resource"], "limit": 2},
    )
    ui_response = client.get("/")

    assert memory_response.status_code == 200
    assert resource_response.status_code == 200
    assert retrieve_response.status_code == 200
    assert ui_response.status_code == 200
    assert "BHD Memory" in ui_response.text
    assert retrieve_response.json()[0]["type"] == "resource"
