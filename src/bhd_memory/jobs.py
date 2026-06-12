from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from typing import Any

from .dream import DreamService
from .graph import GraphService
from .indexing import IndexBackend
from .memory import MemoryService
from .maintenance import MaintenanceService
from .resources import ResourceService
from .storage import ArtifactStore
from .utils import json_dumps, json_loads, new_id, now_iso


@dataclass(frozen=True)
class JobResult:
    job: dict[str, Any]
    result: dict[str, Any]


class JobService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        index: IndexBackend,
        store: ArtifactStore | None = None,
    ) -> None:
        self.conn = conn
        self.index = index
        self.store = store or ArtifactStore()

    def enqueue(
        self,
        pipeline: str,
        payload: dict[str, Any] | None = None,
        *,
        artifact_id: str | None = None,
        stage: str = "queued",
    ) -> dict[str, Any]:
        job_id = new_id("job")
        ts = now_iso()
        self.conn.execute(
            """
            INSERT INTO ingest_job(
              id, artifact_id, pipeline, status, stage, payload_json, result_json,
              attempts, error, started_at, finished_at, updated_at, created_at
            )
            VALUES (?, ?, ?, 'queued', ?, ?, '{}', 0, NULL, NULL, NULL, ?, ?)
            """,
            (job_id, artifact_id, pipeline, stage, json_dumps(payload or {}), ts, ts),
        )
        self.conn.commit()
        return self.get_job(job_id) or {}

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM ingest_job WHERE id = ?", (job_id,)).fetchone()
        return self._job_dict(row) if row else None

    def list_jobs(
        self,
        *,
        status: str | None = None,
        pipeline: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if pipeline:
            clauses.append("pipeline = ?")
            params.append(pipeline)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"SELECT * FROM ingest_job {where} ORDER BY created_at DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [self._job_dict(row) for row in rows]

    def run_next(self) -> JobResult | None:
        job = self._claim_next()
        if not job:
            return None
        try:
            result = self._run_job(job)
        except Exception as exc:
            self._mark_failed(job["id"], exc)
            raise
        else:
            self._mark_succeeded(job["id"], result)
            return JobResult(job=self.get_job(job["id"]) or job, result=result)

    def run_until_idle(
        self,
        *,
        max_jobs: int | None = None,
        poll_interval: float = 0.0,
    ) -> list[JobResult]:
        results: list[JobResult] = []
        while max_jobs is None or len(results) < max_jobs:
            try:
                result = self.run_next()
            except Exception:
                # The failed job is already marked. Continue so one bad document does not
                # block the rest of the local queue.
                result = None
            if result is None:
                if poll_interval <= 0:
                    break
                time.sleep(poll_interval)
                continue
            results.append(result)
        return results

    def _claim_next(self) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT * FROM ingest_job
            WHERE status = 'queued'
            ORDER BY created_at
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return None
        ts = now_iso()
        self.conn.execute(
            """
            UPDATE ingest_job
            SET status = 'running', stage = 'running', attempts = attempts + 1,
                started_at = COALESCE(started_at, ?), updated_at = ?, error = NULL
            WHERE id = ? AND status = 'queued'
            """,
            (ts, ts, row["id"]),
        )
        self.conn.commit()
        return self.get_job(row["id"])

    def _run_job(self, job: dict[str, Any]) -> dict[str, Any]:
        payload = job["payload"]
        memory = MemoryService(self.conn, self.index)
        resources = ResourceService(self.conn, self.index, self.store)
        dream = DreamService(self.conn, memory, self.store)
        maintenance = MaintenanceService(self.conn, self.index, self.store)
        graph = GraphService(self.conn)

        if job["pipeline"] == "dream_scan":
            return dream.scan(
                paths=payload.get("paths"),
                auto_commit=bool(payload.get("auto_commit", False)),
            )
        if job["pipeline"] == "dream_commit":
            return dream.commit_session(
                payload["session_id"],
                reason=payload.get("reason", "job"),
            )
        if job["pipeline"] == "dream_sweep":
            return dream.sweep_idle(
                idle_seconds=int(payload.get("idle_seconds", 1800)),
                limit=int(payload.get("limit", 50)),
            )
        if job["pipeline"] == "resource_ingest_artifact":
            artifact_id = job.get("artifact_id") or payload["artifact_id"]
            return resources.ingest_artifact(
                artifact_id,
                filename=payload.get("filename"),
                workspace_id=payload.get("workspace_id"),
                workspace_name=payload.get("workspace_name"),
                title=payload.get("title"),
                source_uri=payload.get("source_uri"),
                metadata=payload.get("metadata") or {},
            )
        if job["pipeline"] == "resource_text":
            return resources.ingest_text(
                payload["text"],
                title=payload.get("title", "Untitled Text"),
                workspace_id=payload.get("workspace_id"),
                workspace_name=payload.get("workspace_name"),
                metadata=payload.get("metadata") or {},
            )
        if job["pipeline"] == "resource_url":
            return resources.ingest_url(
                payload["url"],
                workspace_id=payload.get("workspace_id"),
                workspace_name=payload.get("workspace_name"),
                title=payload.get("title"),
                metadata=payload.get("metadata") or {},
            )
        if job["pipeline"] == "resource_reindex":
            return resources.reindex_resource(payload["resource_id"])
        if job["pipeline"] == "memory_index":
            memory.index_memory(payload["memory_id"])
            return {"memory_id": payload["memory_id"]}
        if job["pipeline"] == "index_rebuild":
            return maintenance.rebuild_index(clear=bool(payload.get("clear", False)))
        if job["pipeline"] == "graph_sync":
            return graph.sync_all(
                external=bool(payload.get("external", False)),
                limit=payload.get("limit"),
            )
        raise ValueError(f"unknown pipeline: {job['pipeline']}")

    def _mark_succeeded(self, job_id: str, result: dict[str, Any]) -> None:
        ts = now_iso()
        self.conn.execute(
            """
            UPDATE ingest_job
            SET status = 'succeeded', stage = 'done', result_json = ?, error = NULL,
                finished_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (json_dumps(result), ts, ts, job_id),
        )
        self.conn.commit()

    def _mark_failed(self, job_id: str, exc: Exception) -> None:
        ts = now_iso()
        self.conn.execute(
            """
            UPDATE ingest_job
            SET status = 'failed', stage = 'failed', error = ?, finished_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (str(exc), ts, ts, job_id),
        )
        self.conn.commit()

    def _job_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["payload"] = json_loads(result.pop("payload_json", None))
        result["result"] = json_loads(result.pop("result_json", None))
        return result
