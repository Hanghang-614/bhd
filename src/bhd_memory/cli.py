from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import uvicorn

from .config import Settings
from .database import open_db
from .dream import DreamService
from .graph import GraphService
from .hooks import HookService
from .indexing import QdrantIndexBackend
from .jobs import JobService
from .knowledge import KnowledgeService
from .maintenance import MaintenanceService
from .memory import MemoryService
from .resources import ResourceService
from .retrieval import RetrievalService
from .storage import ArtifactStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bhd-memory")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Initialize SQLite and Qdrant collection")

    serve = subparsers.add_parser("serve", help="Run the FastAPI server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--reload", action="store_true")

    scan = subparsers.add_parser("dream-scan", help="Scan Claude/Codex/generic transcript files")
    scan.add_argument("paths", nargs="*", help="Optional JSONL transcript paths")
    scan.add_argument("--auto-commit", action="store_true")
    scan.add_argument("--enqueue", action="store_true")

    commit = subparsers.add_parser("dream-commit", help="Commit one Dream session")
    commit.add_argument("session_id")
    commit.add_argument("--reason", default="manual")
    commit.add_argument("--enqueue", action="store_true")

    sweep = subparsers.add_parser("dream-sweep", help="Commit idle Dream sessions")
    sweep.add_argument("--idle-seconds", type=int, default=1800)
    sweep.add_argument("--limit", type=int, default=50)
    sweep.add_argument("--enqueue", action="store_true")

    upload = subparsers.add_parser("upload-file", help="Upload and index a document")
    upload.add_argument("path")
    upload.add_argument("--workspace-name")
    upload.add_argument("--title")
    upload.add_argument("--enqueue", action="store_true")

    upload_text = subparsers.add_parser("upload-text", help="Upload raw text")
    upload_text.add_argument("title")
    upload_text.add_argument("text")
    upload_text.add_argument("--workspace-name")
    upload_text.add_argument("--enqueue", action="store_true")

    upload_url = subparsers.add_parser("upload-url", help="Fetch, upload, and index a URL")
    upload_url.add_argument("url")
    upload_url.add_argument("--workspace-name")
    upload_url.add_argument("--title")
    upload_url.add_argument("--enqueue", action="store_true")

    search = subparsers.add_parser("search", help="Retrieve memories and knowledge")
    search.add_argument("query")
    search.add_argument("--type", dest="target_types", action="append", choices=["memory", "resource"])
    search.add_argument("--limit", type=int, default=10)

    memories = subparsers.add_parser("memories", help="List memories")
    memories.add_argument("--status")
    memories.add_argument("--scope")
    memories.add_argument("--limit", type=int, default=100)

    review = subparsers.add_parser("review", help="List or act on pending memories")
    review.add_argument("--approve")
    review.add_argument("--reject")
    review.add_argument("--limit", type=int, default=100)

    jobs = subparsers.add_parser("jobs", help="List ingest jobs")
    jobs.add_argument("--status")
    jobs.add_argument("--pipeline")
    jobs.add_argument("--limit", type=int, default=100)

    worker = subparsers.add_parser("worker", help="Run queued ingest jobs")
    worker.add_argument("--once", action="store_true", help="Run at most one job")
    worker.add_argument("--max-jobs", type=int)

    watch = subparsers.add_parser("watch", help="Poll transcripts, sweep idle sessions, and run jobs")
    watch.add_argument("paths", nargs="*", help="Optional transcript paths")
    watch.add_argument("--interval", type=float, default=60.0)
    watch.add_argument("--idle-seconds", type=int, default=1800)
    watch.add_argument("--once", action="store_true")

    rebuild = subparsers.add_parser("rebuild-index", help="Rebuild Qdrant from SQLite truth")
    rebuild.add_argument("--clear", action="store_true")
    rebuild.add_argument("--enqueue", action="store_true")

    hook_capture = subparsers.add_parser("hook-capture", help="Capture one hook turn")
    hook_capture.add_argument("--source-app", required=True)
    hook_capture.add_argument("--session-id", required=True)
    hook_capture.add_argument("--role", required=True)
    hook_capture.add_argument("--content", required=True)
    hook_capture.add_argument("--turn-id")
    hook_capture.add_argument("--project-path")
    hook_capture.add_argument("--event-type", default="hook_capture")

    hook_commit = subparsers.add_parser("hook-commit", help="Commit a hook session")
    hook_commit.add_argument("--source-app", required=True)
    hook_commit.add_argument("--session-id", required=True)
    hook_commit.add_argument("--reason", default="hook_commit")

    hook_recall = subparsers.add_parser("hook-recall", help="Recall memory/knowledge for a hook query")
    hook_recall.add_argument("query")
    hook_recall.add_argument("--source-app")
    hook_recall.add_argument("--session-id")
    hook_recall.add_argument("--project-path")
    hook_recall.add_argument("--type", dest="target_types", action="append", choices=["memory", "resource"])
    hook_recall.add_argument("--limit", type=int, default=8)

    knowledge_list = subparsers.add_parser("knowledge-list", help="List knowledge resources")
    knowledge_list.add_argument("--workspace-id")
    knowledge_list.add_argument("--status", default="ready")
    knowledge_list.add_argument("--limit", type=int, default=100)

    knowledge_view = subparsers.add_parser("knowledge-view", help="View a resource or chunk")
    knowledge_view.add_argument("resource_id")
    knowledge_view.add_argument("--chunk-id")
    knowledge_view.add_argument("--no-chunks", action="store_true")

    knowledge_grep = subparsers.add_parser("knowledge-grep", help="Grep knowledge chunks")
    knowledge_grep.add_argument("pattern")
    knowledge_grep.add_argument("--resource-id")
    knowledge_grep.add_argument("--workspace-id")
    knowledge_grep.add_argument("--limit", type=int, default=50)

    knowledge_query = subparsers.add_parser("knowledge-query", help="Query knowledge via retrieval")
    knowledge_query.add_argument("query")
    knowledge_query.add_argument("--workspace-id")
    knowledge_query.add_argument("--limit", type=int, default=10)

    resource_acl = subparsers.add_parser("resource-acl", help="List, grant, or revoke resource ACL")
    resource_acl.add_argument("resource_id")
    resource_acl.add_argument("--grant", action="store_true")
    resource_acl.add_argument("--revoke", action="store_true")
    resource_acl.add_argument("--subject-type")
    resource_acl.add_argument("--subject-id")
    resource_acl.add_argument("--permission", default="read")

    graph_sync = subparsers.add_parser("graph-sync", help="Sync SQLite truth into local graph episodes")
    graph_sync.add_argument("--external", action="store_true")
    graph_sync.add_argument("--limit", type=int)
    graph_sync.add_argument("--enqueue", action="store_true")

    graph_episodes = subparsers.add_parser("graph-episodes", help="List graph episodes")
    graph_episodes.add_argument("--group-id")
    graph_episodes.add_argument("--target-type")
    graph_episodes.add_argument("--limit", type=int, default=100)

    graph_search = subparsers.add_parser("graph-search", help="Search local graph entities")
    graph_search.add_argument("query")
    graph_search.add_argument("--limit", type=int, default=20)

    args = parser.parse_args(argv)
    settings = Settings.from_env()

    if args.command == "serve":
        uvicorn.run(
            "bhd_memory.asgi:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
        )
        return 0

    conn = open_db(settings.db_path)
    index = QdrantIndexBackend(
        url=settings.qdrant_url,
        collection_name=settings.qdrant_collection,
        embedding_dim=settings.embedding_dim,
    )
    store = ArtifactStore(settings.data_dir)

    try:
        if args.command == "init":
            index.ensure_ready()
            _print_json(
                {
                    "sqlite": str(settings.db_path),
                    "data_dir": str(settings.data_dir),
                    "qdrant_url": settings.qdrant_url,
                    "qdrant_collection": settings.qdrant_collection,
                }
            )
            return 0

        memory = MemoryService(conn, index)
        resources = ResourceService(conn, index, store)
        dream = DreamService(conn, memory, store)
        retrieval = RetrievalService(conn, index)
        jobs_service = JobService(conn, index, store)
        maintenance = MaintenanceService(conn, index, store)
        hooks = HookService(conn, index, store)
        knowledge = KnowledgeService(conn, index, store)
        graph = GraphService(conn)

        if args.command == "dream-scan":
            if args.enqueue:
                _print_json(
                    jobs_service.enqueue(
                        "dream_scan",
                        {"paths": args.paths or None, "auto_commit": args.auto_commit},
                    )
                )
            else:
                _print_json(dream.scan(paths=args.paths or None, auto_commit=args.auto_commit))
        elif args.command == "dream-commit":
            if args.enqueue:
                _print_json(
                    jobs_service.enqueue(
                        "dream_commit",
                        {"session_id": args.session_id, "reason": args.reason},
                    )
                )
            else:
                _print_json(dream.commit_session(args.session_id, reason=args.reason))
        elif args.command == "dream-sweep":
            payload = {"idle_seconds": args.idle_seconds, "limit": args.limit}
            if args.enqueue:
                _print_json(jobs_service.enqueue("dream_sweep", payload))
            else:
                _print_json(dream.sweep_idle(**payload))
        elif args.command == "upload-file":
            if args.enqueue:
                path = Path(args.path)
                artifact = resources.create_upload_artifact(
                    path.read_bytes(),
                    filename=path.name,
                    mime=None,
                    metadata={"original_path": str(path)},
                )
                _print_json(
                    jobs_service.enqueue(
                        "resource_ingest_artifact",
                        {
                            "artifact_id": artifact["id"],
                            "filename": path.name,
                            "workspace_name": args.workspace_name,
                            "title": args.title,
                            "metadata": {"original_path": str(path)},
                        },
                        artifact_id=artifact["id"],
                    )
                )
            else:
                _print_json(
                    resources.ingest_file(
                        Path(args.path),
                        workspace_name=args.workspace_name,
                        title=args.title,
                    )
                )
        elif args.command == "upload-text":
            if args.enqueue:
                _print_json(
                    jobs_service.enqueue(
                        "resource_text",
                        {
                            "text": args.text,
                            "title": args.title,
                            "workspace_name": args.workspace_name,
                        },
                    )
                )
            else:
                _print_json(
                    resources.ingest_text(
                        args.text,
                        title=args.title,
                        workspace_name=args.workspace_name,
                    )
                )
        elif args.command == "upload-url":
            if args.enqueue:
                _print_json(
                    jobs_service.enqueue(
                        "resource_url",
                        {
                            "url": args.url,
                            "workspace_name": args.workspace_name,
                            "title": args.title,
                        },
                    )
                )
            else:
                _print_json(
                    resources.ingest_url(
                        args.url,
                        workspace_name=args.workspace_name,
                        title=args.title,
                    )
                )
        elif args.command == "search":
            _print_json(
                retrieval.retrieve(
                    query=args.query,
                    target_types=args.target_types,
                    limit=args.limit,
                )
            )
        elif args.command == "memories":
            _print_json(
                memory.list_memories(
                    status=args.status,
                    scope=args.scope,
                    limit=args.limit,
                )
            )
        elif args.command == "review":
            if args.approve:
                _print_json(memory.approve_memory(args.approve, actor="cli"))
            elif args.reject:
                _print_json(memory.reject_memory(args.reject, actor="cli"))
            else:
                _print_json(memory.review_queue(limit=args.limit))
        elif args.command == "jobs":
            _print_json(
                jobs_service.list_jobs(
                    status=args.status,
                    pipeline=args.pipeline,
                    limit=args.limit,
                )
            )
        elif args.command == "worker":
            if args.once:
                result = jobs_service.run_next()
                _print_json({"job": result.job, "result": result.result} if result else {"job": None})
            else:
                results = jobs_service.run_until_idle(max_jobs=args.max_jobs)
                _print_json(
                    {
                        "count": len(results),
                        "jobs": [{"job": item.job, "result": item.result} for item in results],
                    }
                )
        elif args.command == "watch":
            while True:
                snapshot = {
                    "scan": dream.scan(paths=args.paths or None, auto_commit=False),
                    "sweep": dream.sweep_idle(idle_seconds=args.idle_seconds),
                    "jobs": [
                        {"job": item.job, "result": item.result}
                        for item in jobs_service.run_until_idle()
                    ],
                }
                _print_json(snapshot)
                if args.once:
                    break
                time.sleep(args.interval)
        elif args.command == "rebuild-index":
            if args.enqueue:
                _print_json(jobs_service.enqueue("index_rebuild", {"clear": args.clear}))
            else:
                _print_json(maintenance.rebuild_index(clear=args.clear))
        elif args.command == "hook-capture":
            _print_json(
                hooks.capture(
                    source_app=args.source_app,
                    external_session_id=args.session_id,
                    role=args.role,
                    content=args.content,
                    external_turn_id=args.turn_id,
                    project_path=args.project_path,
                    event_type=args.event_type,
                )
            )
        elif args.command == "hook-commit":
            _print_json(
                hooks.commit(
                    source_app=args.source_app,
                    external_session_id=args.session_id,
                    reason=args.reason,
                )
            )
        elif args.command == "hook-recall":
            _print_json(
                hooks.recall(
                    query=args.query,
                    source_app=args.source_app,
                    external_session_id=args.session_id,
                    project_path=args.project_path,
                    target_types=args.target_types,
                    limit=args.limit,
                )
            )
        elif args.command == "knowledge-list":
            _print_json(
                knowledge.list(
                    workspace_id=args.workspace_id,
                    status=args.status,
                    limit=args.limit,
                )
            )
        elif args.command == "knowledge-view":
            result = knowledge.view(
                args.resource_id,
                chunk_id=args.chunk_id,
                include_chunks=not args.no_chunks,
            )
            _print_json(result or {})
        elif args.command == "knowledge-grep":
            _print_json(
                knowledge.grep(
                    args.pattern,
                    resource_id=args.resource_id,
                    workspace_id=args.workspace_id,
                    limit=args.limit,
                )
            )
        elif args.command == "knowledge-query":
            _print_json(
                knowledge.query(
                    args.query,
                    workspace_id=args.workspace_id,
                    limit=args.limit,
                )
            )
        elif args.command == "resource-acl":
            if args.grant:
                if not args.subject_type or not args.subject_id:
                    raise ValueError("--subject-type and --subject-id are required for --grant")
                _print_json(
                    resources.grant_access(
                        args.resource_id,
                        subject_type=args.subject_type,
                        subject_id=args.subject_id,
                        permission=args.permission,
                    )
                )
            elif args.revoke:
                if not args.subject_type or not args.subject_id:
                    raise ValueError("--subject-type and --subject-id are required for --revoke")
                _print_json(
                    resources.revoke_access(
                        args.resource_id,
                        subject_type=args.subject_type,
                        subject_id=args.subject_id,
                    )
                )
            else:
                _print_json(resources.list_acl(args.resource_id))
        elif args.command == "graph-sync":
            payload = {"external": args.external, "limit": args.limit}
            if args.enqueue:
                _print_json(jobs_service.enqueue("graph_sync", payload))
            else:
                _print_json(graph.sync_all(**payload))
        elif args.command == "graph-episodes":
            _print_json(
                graph.list_episodes(
                    group_id=args.group_id,
                    target_type=args.target_type,
                    limit=args.limit,
                )
            )
        elif args.command == "graph-search":
            _print_json(graph.search_entities(args.query, limit=args.limit))
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def _print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    raise SystemExit(main())
