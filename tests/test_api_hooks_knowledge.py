from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from bhd_memory.api import create_app
from bhd_memory.config import Settings
from bhd_memory.database import open_db
from bhd_memory.indexing import QdrantIndexBackend


def test_api_hooks_knowledge_and_acl(tmp_path):
    settings = Settings(
        db_path=tmp_path / "bhd.sqlite",
        data_dir=tmp_path / "data",
        qdrant_url=":memory:",
        qdrant_collection=f"api_extra_{uuid.uuid4().hex}",
        embedding_dim=384,
    )
    conn = open_db(settings.db_path)
    index = QdrantIndexBackend(
        url=settings.qdrant_url,
        collection_name=settings.qdrant_collection,
        embedding_dim=settings.embedding_dim,
    )
    client = TestClient(create_app(settings=settings, conn=conn, index=index))

    capture = client.post(
        "/api/hooks/capture",
        json={
            "source_app": "codex_hook",
            "external_session_id": "api-session",
            "role": "user",
            "content": "请记住：API hook recall uses Qdrant.",
            "project_path": str(tmp_path),
        },
    )
    commit = client.post(
        "/api/hooks/commit",
        json={
            "source_app": "codex_hook",
            "external_session_id": "api-session",
            "reason": "test",
        },
    )
    recall = client.post(
        "/api/hooks/recall",
        json={
            "source_app": "codex_hook",
            "external_session_id": "api-session",
            "query": "hook recall Qdrant",
            "target_types": ["memory"],
        },
    )
    resource = client.post(
        "/api/resources/text",
        json={
            "title": "API Knowledge",
            "text": "API knowledge grep and query endpoints work.",
        },
    ).json()
    grep = client.post("/api/knowledge/grep", json={"pattern": "grep"}).json()
    acl = client.post(
        f"/api/resources/{resource['id']}/acl",
        json={"subject_type": "agent", "subject_id": "codex", "permission": "read"},
    )
    acl_list = client.get(f"/api/resources/{resource['id']}/acl")
    graph_sync = client.post("/api/graph/sync", json={"external": False})
    graph_episodes = client.get("/api/graph/episodes")
    graph_entities = client.get("/api/graph/entities/search", params={"query": "Qdrant"})

    assert capture.status_code == 200
    assert commit.status_code == 200
    assert recall.status_code == 200
    assert recall.json()
    assert grep and grep[0]["resource_id"] == resource["id"]
    assert acl.status_code == 200
    assert acl_list.json()[0]["subject_id"] == "codex"
    assert graph_sync.status_code == 200
    assert graph_episodes.json()
    assert graph_entities.json()
