from __future__ import annotations

from bhd_memory.knowledge import KnowledgeService
from bhd_memory.resources import ResourceService


def test_knowledge_tools_and_resource_acl(runtime):
    conn, index, store = runtime
    resources = ResourceService(conn, index, store)
    resource = resources.ingest_text(
        "Knowledge tools can list, view, grep, and query resource chunks.",
        title="Knowledge Tools",
    )
    knowledge = KnowledgeService(conn, index, store)

    resources.grant_access(
        resource["id"],
        subject_type="agent",
        subject_id="codex",
        permission="read",
    )
    listed = knowledge.list()
    viewed = knowledge.view(resource["id"])
    grep = knowledge.grep("grep")
    query = knowledge.query("resource chunks")
    acl = resources.list_acl(resource["id"])
    revoked = resources.revoke_access(resource["id"], subject_type="agent", subject_id="codex")

    assert listed and listed[0]["id"] == resource["id"]
    assert viewed and viewed["chunks"]
    assert grep and grep[0]["resource_id"] == resource["id"]
    assert query and query[0]["type"] == "resource"
    assert acl and acl[0]["subject_id"] == "codex"
    assert revoked["revoked"] is True
    assert resources.list_acl(resource["id"]) == []

