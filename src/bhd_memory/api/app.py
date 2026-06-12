from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..config import Settings
from ..database import open_db
from ..dream import DreamService
from ..indexing import IndexBackend, QdrantIndexBackend
from ..hooks import HookService
from ..graph import GraphService
from ..jobs import JobService
from ..knowledge import KnowledgeService
from ..maintenance import MaintenanceService
from ..memory import MemoryEvidenceDraft, MemoryService
from ..resources import ResourceService
from ..retrieval import RetrievalService
from ..storage import ArtifactStore


class DreamScanRequest(BaseModel):
    paths: list[str] | None = None
    auto_commit: bool = False
    enqueue: bool = False


class DreamSweepRequest(BaseModel):
    idle_seconds: int = 1800
    limit: int = 50
    enqueue: bool = False


class MemoryCreateRequest(BaseModel):
    content: str
    scope: str = "global"
    category: str = "event"
    status: str = "active"
    confidence: float = 0.75
    workspace_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class MemoryUpdateRequest(BaseModel):
    content: str | None = None
    status: str | None = None
    category: str | None = None
    scope: str | None = None
    confidence: float | None = None


class MemorySearchRequest(BaseModel):
    query: str
    workspace_id: str | None = None
    scope: str | None = None
    limit: int = 10


class TextResourceRequest(BaseModel):
    text: str
    title: str = "Untitled Text"
    workspace_id: str | None = None
    workspace_name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    enqueue: bool = False


class LinkResourceRequest(BaseModel):
    url: str
    title: str | None = None
    workspace_id: str | None = None
    workspace_name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    enqueue: bool = False


class RetrieveRequest(BaseModel):
    query: str
    target_types: list[str] | None = None
    workspace_id: str | None = None
    scope: str | None = None
    limit: int = 10


class HookCaptureRequest(BaseModel):
    source_app: str
    external_session_id: str
    role: str
    content: str
    external_turn_id: str | None = None
    project_path: str | None = None
    event_type: str = "hook_capture"
    created_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class HookCommitRequest(BaseModel):
    source_app: str
    external_session_id: str
    reason: str = "hook_commit"


class HookRecallRequest(BaseModel):
    query: str
    source_app: str | None = None
    external_session_id: str | None = None
    project_path: str | None = None
    target_types: list[str] | None = None
    limit: int = 8


class RebuildIndexRequest(BaseModel):
    clear: bool = False
    enqueue: bool = False


class GraphSyncRequest(BaseModel):
    external: bool = False
    limit: int | None = None
    enqueue: bool = False


class ResourceAclRequest(BaseModel):
    subject_type: str
    subject_id: str
    permission: str = "read"


class KnowledgeGrepRequest(BaseModel):
    pattern: str
    resource_id: str | None = None
    workspace_id: str | None = None
    limit: int = 50
    ignore_case: bool = True


class KnowledgeQueryRequest(BaseModel):
    query: str
    workspace_id: str | None = None
    limit: int = 10


def create_app(
    *,
    settings: Settings | None = None,
    conn: sqlite3.Connection | None = None,
    index: IndexBackend | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="BHD Memory", version="0.1.0")
    app.state.settings = settings
    app.state.conn = conn or open_db(settings.db_path)
    app.state.index = index or QdrantIndexBackend(
        url=settings.qdrant_url,
        collection_name=settings.qdrant_collection,
        embedding_dim=settings.embedding_dim,
    )
    app.state.store = ArtifactStore(settings.data_dir)
    static_dir = Path(__file__).with_name("static")
    index_html = static_dir / "index.html"
    assets_dir = static_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/", response_class=HTMLResponse)
    def index_page():
        if index_html.exists():
            return FileResponse(index_html)
        return "<!doctype html><title>BHD Memory</title><h1>BHD Memory</h1><p>Frontend build missing. Run npm run build in ./frontend.</p>"

    @app.get("/health")
    def health(request: Request) -> dict[str, Any]:
        qdrant_ok = True
        qdrant_error = None
        try:
            request.app.state.index.ensure_ready()
        except Exception as exc:  # pragma: no cover - depends on local deployment
            qdrant_ok = False
            qdrant_error = str(exc)
        return {
            "ok": qdrant_ok,
            "sqlite": "ok",
            "qdrant": {
                "ok": qdrant_ok,
                "url": request.app.state.settings.qdrant_url,
                "collection": request.app.state.settings.qdrant_collection,
                "error": qdrant_error,
            },
        }

    @app.post("/api/dream/scan")
    def dream_scan(payload: DreamScanRequest, request: Request) -> dict[str, Any]:
        if payload.enqueue:
            return _jobs(request).enqueue(
                "dream_scan",
                {"paths": payload.paths, "auto_commit": payload.auto_commit},
            )
        return _dream(request).scan(paths=payload.paths, auto_commit=payload.auto_commit)

    @app.get("/api/dream/sessions")
    def dream_sessions(request: Request, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        return _dream(request).list_sessions(status=status, limit=limit)

    @app.get("/api/dream/sessions/{session_id}")
    def dream_session(session_id: str, request: Request, include_turns: bool = False) -> dict[str, Any]:
        session = _dream(request).get_session(session_id, include_turns=include_turns)
        if not session:
            raise HTTPException(status_code=404, detail="session not found")
        return session

    @app.post("/api/dream/sessions/{session_id}/commit")
    def dream_commit(session_id: str, request: Request, reason: str = "manual") -> dict[str, Any]:
        try:
            return _dream(request).commit_session(session_id, reason=reason)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/dream/sweep")
    def dream_sweep(payload: DreamSweepRequest, request: Request) -> dict[str, Any]:
        body = payload.model_dump(exclude={"enqueue"})
        if payload.enqueue:
            return _jobs(request).enqueue("dream_sweep", body)
        return _dream(request).sweep_idle(
            idle_seconds=payload.idle_seconds,
            limit=payload.limit,
        )

    @app.get("/api/dream/sessions/{session_id}/archive/{archive_no}")
    def dream_archive(session_id: str, archive_no: int, request: Request) -> dict[str, Any]:
        archive = _dream(request).get_archive(session_id, archive_no)
        if not archive:
            raise HTTPException(status_code=404, detail="archive not found")
        return archive

    @app.post("/api/memories")
    def create_memory(payload: MemoryCreateRequest, request: Request) -> dict[str, Any]:
        evidence = [
            MemoryEvidenceDraft(
                session_id=item.get("session_id"),
                turn_id=item.get("turn_id"),
                artifact_id=item.get("artifact_id"),
                quote_ref=item.get("quote_ref"),
                confidence=float(item.get("confidence", payload.confidence)),
            )
            for item in payload.evidence
        ]
        return _memory(request).create_memory(
            content=payload.content,
            scope=payload.scope,
            category=payload.category,
            status=payload.status,
            confidence=payload.confidence,
            workspace_id=payload.workspace_id,
            metadata=payload.metadata,
            evidence=evidence,
            actor="api",
        )

    @app.get("/api/memories")
    def list_memories(
        request: Request,
        status: str | None = None,
        scope: str | None = None,
        workspace_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return _memory(request).list_memories(
            status=status,
            scope=scope,
            workspace_id=workspace_id,
            limit=limit,
        )

    @app.post("/api/memories/search")
    def search_memories(payload: MemorySearchRequest, request: Request) -> list[dict[str, Any]]:
        return _retrieval(request).retrieve(
            query=payload.query,
            target_types=["memory"],
            workspace_id=payload.workspace_id,
            scope=payload.scope,
            limit=payload.limit,
        )

    @app.get("/api/memories/operations")
    def memory_operations(request: Request, limit: int = 100) -> list[dict[str, Any]]:
        return _memory(request).operations(limit=limit)

    @app.get("/api/memories/review")
    def memory_review_queue(request: Request, limit: int = 100) -> list[dict[str, Any]]:
        return _memory(request).review_queue(limit=limit)

    @app.get("/api/memories/{memory_id}")
    def get_memory(memory_id: str, request: Request) -> dict[str, Any]:
        memory = _memory(request).get_memory(memory_id)
        if not memory:
            raise HTTPException(status_code=404, detail="memory not found")
        return memory

    @app.patch("/api/memories/{memory_id}")
    def update_memory(memory_id: str, payload: MemoryUpdateRequest, request: Request) -> dict[str, Any]:
        try:
            return _memory(request).update_memory(
                memory_id,
                content=payload.content,
                status=payload.status,
                category=payload.category,
                scope=payload.scope,
                confidence=payload.confidence,
                actor="api",
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.delete("/api/memories/{memory_id}")
    def delete_memory(memory_id: str, request: Request) -> dict[str, Any]:
        try:
            return _memory(request).delete_memory(memory_id, actor="api")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/memories/{memory_id}/approve")
    def approve_memory(memory_id: str, request: Request) -> dict[str, Any]:
        try:
            return _memory(request).approve_memory(memory_id, actor="api")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/memories/{memory_id}/reject")
    def reject_memory(memory_id: str, request: Request) -> dict[str, Any]:
        try:
            return _memory(request).reject_memory(memory_id, actor="api")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/memories/{memory_id}/evidence")
    def memory_evidence(memory_id: str, request: Request) -> list[dict[str, Any]]:
        return _memory(request).evidence(memory_id)

    @app.get("/api/memories/{memory_id}/relations")
    def memory_relations(memory_id: str, request: Request) -> list[dict[str, Any]]:
        return _memory(request).relations(memory_id)

    @app.post("/api/resources/upload")
    async def upload_resource(
        request: Request,
        file: UploadFile = File(...),
        workspace_id: str | None = Form(default=None),
        workspace_name: str | None = Form(default=None),
        title: str | None = Form(default=None),
        metadata_json: str | None = Form(default=None),
        enqueue: bool = Form(default=False),
    ) -> dict[str, Any]:
        metadata = _metadata_from_form(metadata_json)
        data = await file.read()
        if enqueue:
            artifact = _resources(request).create_upload_artifact(
                data,
                filename=file.filename or "upload.bin",
                mime=file.content_type,
                metadata=metadata,
            )
            return _jobs(request).enqueue(
                "resource_ingest_artifact",
                {
                    "artifact_id": artifact["id"],
                    "filename": file.filename or "upload.bin",
                    "workspace_id": workspace_id,
                    "workspace_name": workspace_name,
                    "title": title,
                    "metadata": metadata,
                },
                artifact_id=artifact["id"],
            )
        return _resources(request).ingest_bytes(
            data,
            filename=file.filename or "upload.bin",
            workspace_id=workspace_id,
            workspace_name=workspace_name,
            title=title,
            mime=file.content_type,
            metadata=metadata,
        )

    @app.post("/api/resources/text")
    def create_text_resource(payload: TextResourceRequest, request: Request) -> dict[str, Any]:
        if payload.enqueue:
            return _jobs(request).enqueue("resource_text", payload.model_dump(exclude={"enqueue"}))
        return _resources(request).ingest_text(
            payload.text,
            title=payload.title,
            workspace_id=payload.workspace_id,
            workspace_name=payload.workspace_name,
            metadata=payload.metadata,
        )

    @app.post("/api/resources/link")
    def create_link_resource(payload: LinkResourceRequest, request: Request) -> dict[str, Any]:
        try:
            if payload.enqueue:
                return _jobs(request).enqueue("resource_url", payload.model_dump(exclude={"enqueue"}))
            return _resources(request).ingest_url(
                payload.url,
                title=payload.title,
                workspace_id=payload.workspace_id,
                workspace_name=payload.workspace_name,
                metadata=payload.metadata,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/resources")
    def list_resources(
        request: Request,
        workspace_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return _resources(request).list_resources(workspace_id=workspace_id, status=status, limit=limit)

    @app.get("/api/resources/{resource_id}")
    def get_resource(resource_id: str, request: Request, include_chunks: bool = False) -> dict[str, Any]:
        resource = _resources(request).get_resource(resource_id, include_chunks=include_chunks)
        if not resource:
            raise HTTPException(status_code=404, detail="resource not found")
        return resource

    @app.delete("/api/resources/{resource_id}")
    def delete_resource(resource_id: str, request: Request) -> dict[str, Any]:
        try:
            return _resources(request).delete_resource(resource_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/resources/{resource_id}/reindex")
    def reindex_resource(resource_id: str, request: Request, enqueue: bool = False) -> dict[str, Any]:
        if enqueue:
            return _jobs(request).enqueue("resource_reindex", {"resource_id": resource_id})
        try:
            return _resources(request).reindex_resource(resource_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/resources/{resource_id}/acl")
    def resource_acl(resource_id: str, request: Request) -> list[dict[str, Any]]:
        return _resources(request).list_acl(resource_id)

    @app.post("/api/resources/{resource_id}/acl")
    def grant_resource_acl(
        resource_id: str,
        payload: ResourceAclRequest,
        request: Request,
    ) -> dict[str, Any]:
        try:
            return _resources(request).grant_access(resource_id, **payload.model_dump())
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.delete("/api/resources/{resource_id}/acl/{subject_type}/{subject_id}")
    def revoke_resource_acl(
        resource_id: str,
        subject_type: str,
        subject_id: str,
        request: Request,
    ) -> dict[str, Any]:
        return _resources(request).revoke_access(
            resource_id,
            subject_type=subject_type,
            subject_id=subject_id,
        )

    @app.post("/api/retrieve")
    def retrieve(payload: RetrieveRequest, request: Request) -> list[dict[str, Any]]:
        return _retrieval(request).retrieve(
            query=payload.query,
            target_types=payload.target_types,
            workspace_id=payload.workspace_id,
            scope=payload.scope,
            limit=payload.limit,
        )

    @app.post("/api/hooks/capture")
    def hook_capture(payload: HookCaptureRequest, request: Request) -> dict[str, Any]:
        return _hooks(request).capture(**payload.model_dump())

    @app.post("/api/hooks/commit")
    def hook_commit(payload: HookCommitRequest, request: Request) -> dict[str, Any]:
        try:
            return _hooks(request).commit(**payload.model_dump())
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/hooks/recall")
    def hook_recall(payload: HookRecallRequest, request: Request) -> list[dict[str, Any]]:
        return _hooks(request).recall(**payload.model_dump())

    @app.get("/api/knowledge/list")
    def knowledge_list(
        request: Request,
        workspace_id: str | None = None,
        status: str = "ready",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return _knowledge(request).list(workspace_id=workspace_id, status=status, limit=limit)

    @app.get("/api/knowledge/view/{resource_id}")
    def knowledge_view(
        resource_id: str,
        request: Request,
        chunk_id: str | None = None,
        include_chunks: bool = True,
    ) -> dict[str, Any]:
        result = _knowledge(request).view(
            resource_id,
            chunk_id=chunk_id,
            include_chunks=include_chunks,
        )
        if not result:
            raise HTTPException(status_code=404, detail="knowledge item not found")
        return result

    @app.post("/api/knowledge/grep")
    def knowledge_grep(payload: KnowledgeGrepRequest, request: Request) -> list[dict[str, Any]]:
        return _knowledge(request).grep(**payload.model_dump())

    @app.post("/api/knowledge/query")
    def knowledge_query(payload: KnowledgeQueryRequest, request: Request) -> list[dict[str, Any]]:
        return _knowledge(request).query(**payload.model_dump())

    @app.get("/api/jobs")
    def list_jobs(
        request: Request,
        status: str | None = None,
        pipeline: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return _jobs(request).list_jobs(status=status, pipeline=pipeline, limit=limit)

    @app.post("/api/jobs/run-next")
    def run_next_job(request: Request) -> dict[str, Any]:
        try:
            result = _jobs(request).run_next()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        if result is None:
            return {"job": None, "result": None}
        return {"job": result.job, "result": result.result}

    @app.post("/api/jobs/run-until-idle")
    def run_jobs_until_idle(request: Request, max_jobs: int | None = None) -> dict[str, Any]:
        results = _jobs(request).run_until_idle(max_jobs=max_jobs)
        return {
            "count": len(results),
            "jobs": [{"job": item.job, "result": item.result} for item in results],
        }

    @app.post("/api/index/rebuild")
    def rebuild_index(payload: RebuildIndexRequest, request: Request) -> dict[str, Any]:
        body = payload.model_dump(exclude={"enqueue"})
        if payload.enqueue:
            return _jobs(request).enqueue("index_rebuild", body)
        return _maintenance(request).rebuild_index(clear=payload.clear)

    @app.post("/api/graph/sync")
    def graph_sync(payload: GraphSyncRequest, request: Request) -> dict[str, Any]:
        body = payload.model_dump(exclude={"enqueue"})
        if payload.enqueue:
            return _jobs(request).enqueue("graph_sync", body)
        return _graph(request).sync_all(external=payload.external, limit=payload.limit)

    @app.get("/api/graph/episodes")
    def graph_episodes(
        request: Request,
        group_id: str | None = None,
        target_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return _graph(request).list_episodes(group_id=group_id, target_type=target_type, limit=limit)

    @app.get("/api/graph/episodes/{episode_id}")
    def graph_episode(episode_id: str, request: Request) -> dict[str, Any]:
        episode = _graph(request).get_episode(episode_id)
        if not episode:
            raise HTTPException(status_code=404, detail="graph episode not found")
        return episode

    @app.get("/api/graph/entities/search")
    def graph_entities_search(request: Request, query: str, limit: int = 20) -> list[dict[str, Any]]:
        return _graph(request).search_entities(query, limit=limit)

    return app


def _memory(request: Request) -> MemoryService:
    return MemoryService(request.app.state.conn, request.app.state.index)


def _resources(request: Request) -> ResourceService:
    return ResourceService(request.app.state.conn, request.app.state.index, request.app.state.store)


def _dream(request: Request) -> DreamService:
    return DreamService(request.app.state.conn, _memory(request), request.app.state.store)


def _retrieval(request: Request) -> RetrievalService:
    return RetrievalService(request.app.state.conn, request.app.state.index)


def _jobs(request: Request) -> JobService:
    return JobService(request.app.state.conn, request.app.state.index, request.app.state.store)


def _maintenance(request: Request) -> MaintenanceService:
    return MaintenanceService(request.app.state.conn, request.app.state.index, request.app.state.store)


def _hooks(request: Request) -> HookService:
    return HookService(request.app.state.conn, request.app.state.index, request.app.state.store)


def _knowledge(request: Request) -> KnowledgeService:
    return KnowledgeService(request.app.state.conn, request.app.state.index, request.app.state.store)


def _graph(request: Request) -> GraphService:
    return GraphService(request.app.state.conn)


def _metadata_from_form(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="metadata_json must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="metadata_json must be an object")
    return parsed
