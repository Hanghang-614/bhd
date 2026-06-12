from __future__ import annotations

from bhd_memory.resources import ResourceService
from bhd_memory.retrieval import RetrievalService


def test_text_resource_is_chunked_indexed_and_retrieved(runtime):
    conn, index, store = runtime
    resources = ResourceService(conn, index, store)
    resource = resources.ingest_text(
        "Qdrant dense sparse hybrid retrieval is the main search path.\nSQLite stores truth.",
        title="Architecture Note",
        workspace_name="demo",
    )

    contexts = RetrievalService(conn, index).retrieve(
        query="hybrid retrieval main search path",
        target_types=["resource"],
        workspace_id=resource["workspace_id"],
        limit=3,
    )

    assert resource["status"] == "ready"
    assert resource["chunks"]
    assert contexts
    assert contexts[0]["type"] == "resource"
    assert contexts[0]["source"]["title"] == "Architecture Note"


def test_deleted_resource_is_removed_from_retrieval(runtime):
    conn, index, store = runtime
    resources = ResourceService(conn, index, store)
    resource = resources.ingest_text("Only visible before deletion.", title="Delete Me")
    resources.delete_resource(resource["id"])

    contexts = RetrievalService(conn, index).retrieve(
        query="visible before deletion",
        target_types=["resource"],
        limit=3,
    )

    assert contexts == []


def test_url_resource_uses_original_url_as_source(runtime, tmp_path):
    conn, index, store = runtime
    source = tmp_path / "note.txt"
    source.write_text("URL imported resource keeps the original source URI.", encoding="utf-8")
    resources = ResourceService(conn, index, store)

    resource = resources.ingest_url(source.as_uri(), title="URL Note")

    assert resource["source_uri"] == source.as_uri()
    assert resource["chunks"]
