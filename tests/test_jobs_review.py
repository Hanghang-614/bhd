from __future__ import annotations

from bhd_memory.jobs import JobService
from bhd_memory.memory import MemoryService
from bhd_memory.resources import ResourceService
from bhd_memory.retrieval import RetrievalService


def test_job_worker_ingests_text_resource(runtime):
    conn, index, store = runtime
    jobs = JobService(conn, index, store)
    job = jobs.enqueue(
        "resource_text",
        {
            "title": "Queued Note",
            "text": "Queued parsing writes chunks and indexes Qdrant.",
            "workspace_name": "queued",
        },
    )

    result = jobs.run_next()
    resources = ResourceService(conn, index, store).list_resources()
    contexts = RetrievalService(conn, index).retrieve(
        query="queued parsing chunks",
        target_types=["resource"],
        limit=3,
    )

    assert job["status"] == "queued"
    assert result is not None
    assert result.job["status"] == "succeeded"
    assert resources[0]["title"] == "Queued Note"
    assert contexts and contexts[0]["source"]["title"] == "Queued Note"


def test_review_queue_approve_indexes_pending_memory(runtime):
    conn, index, _store = runtime
    memory = MemoryService(conn, index)
    created = memory.create_memory(
        content="Pending memory should enter review before indexing.",
        scope="global",
        category="preference",
        status="pending",
        confidence=0.4,
    )

    before = RetrievalService(conn, index).retrieve(
        query="review before indexing",
        target_types=["memory"],
        limit=3,
    )
    review = memory.review_queue()
    approved = memory.approve_memory(created["id"], actor="test")
    after = RetrievalService(conn, index).retrieve(
        query="review before indexing",
        target_types=["memory"],
        limit=3,
    )

    assert review and review[0]["id"] == created["id"]
    assert before == []
    assert approved["status"] == "active"
    assert after and after[0]["id"] == created["id"]
