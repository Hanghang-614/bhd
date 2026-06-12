from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .chunking import ChunkDraft, chunk_document
from .indexing import IndexBackend
from .parsers import ParsedDocument, ParsedNode, default_registry
from .repository import ensure_source_app, ensure_workspace, record_vector_index_item
from .storage import ArtifactStore, StoredArtifact
from .utils import (
    clean_text,
    guess_mime,
    json_dumps,
    json_loads,
    new_id,
    now_iso,
    sha256_text,
)


class ResourceService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        index: IndexBackend,
        store: ArtifactStore | None = None,
    ) -> None:
        self.conn = conn
        self.index = index
        self.store = store or ArtifactStore()
        self.registry = default_registry()

    def ingest_bytes(
        self,
        data: bytes,
        *,
        filename: str,
        workspace_id: str | None = None,
        workspace_name: str | None = None,
        title: str | None = None,
        mime: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        artifact = self.create_upload_artifact(
            data,
            filename=filename,
            mime=mime or guess_mime(filename),
            metadata=metadata or {},
        )
        return self.ingest_artifact(
            artifact["id"],
            workspace_id=workspace_id,
            workspace_name=workspace_name,
            title=title,
        )

    def ingest_file(
        self,
        path: str | Path,
        *,
        workspace_id: str | None = None,
        workspace_name: str | None = None,
        title: str | None = None,
        mime: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        file_path = Path(path)
        stored = self.store.copy_file("uploads", file_path)
        source_id = ensure_source_app(self.conn, name="manual_upload", app_type="resource")
        artifact_id = self._insert_raw_artifact(
            source_app_id=source_id,
            kind="upload",
            stored=stored,
            mime=mime or guess_mime(file_path),
            metadata={**(metadata or {}), "filename": file_path.name, "original_path": str(file_path)},
        )
        self.conn.commit()
        return self.ingest_artifact(
            artifact_id,
            filename=file_path.name,
            workspace_id=workspace_id,
            workspace_name=workspace_name,
            title=title,
        )

    def ingest_text(
        self,
        text: str,
        *,
        title: str = "Untitled Text",
        workspace_id: str | None = None,
        workspace_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        filename = f"{title}.txt"
        return self.ingest_bytes(
            clean_text(text).encode("utf-8"),
            filename=filename,
            workspace_id=workspace_id,
            workspace_name=workspace_name,
            title=title,
            mime="text/plain",
            metadata=metadata,
        )

    def ingest_url(
        self,
        url: str,
        *,
        workspace_id: str | None = None,
        workspace_name: str | None = None,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request = Request(url, headers={"user-agent": "bhd-memory/0.1"})
        with urlopen(request, timeout=20) as response:
            data = response.read(25 * 1024 * 1024)
            mime = response.headers.get_content_type() or "application/octet-stream"
        parsed_url = urlparse(url)
        filename = Path(parsed_url.path).name or "downloaded-resource"
        artifact = self.create_upload_artifact(
            data,
            filename=filename,
            mime=mime,
            metadata={**(metadata or {}), "source_url": url},
        )
        return self.ingest_artifact(
            artifact["id"],
            workspace_id=workspace_id,
            workspace_name=workspace_name,
            title=title or filename,
            source_uri=url,
        )

    def create_upload_artifact(
        self,
        data: bytes,
        *,
        filename: str,
        mime: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        source_id = ensure_source_app(self.conn, name="manual_upload", app_type="resource")
        stored = self.store.write_bytes("uploads", filename, data)
        artifact_id = self._insert_raw_artifact(
            source_app_id=source_id,
            kind="upload",
            stored=stored,
            mime=mime or guess_mime(filename),
            metadata={**(metadata or {}), "filename": filename},
        )
        self.conn.commit()
        return {
            "id": artifact_id,
            "source_app_id": source_id,
            "kind": "upload",
            "uri": stored.uri,
            "checksum": stored.checksum,
            "mime": mime or guess_mime(filename),
            "size": stored.size,
            "metadata": {**(metadata or {}), "filename": filename},
        }

    def ingest_artifact(
        self,
        artifact_id: str,
        *,
        filename: str | None = None,
        workspace_id: str | None = None,
        workspace_name: str | None = None,
        title: str | None = None,
        source_uri: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM raw_artifact WHERE id = ?", (artifact_id,)).fetchone()
        if not row:
            raise KeyError(f"artifact not found: {artifact_id}")
        artifact_metadata = json_loads(row["metadata_json"])
        stored = StoredArtifact(
            path=Path(row["uri"]),
            uri=row["uri"],
            checksum=row["checksum"],
            size=row["size"],
        )
        return self._ingest_existing_artifact(
            artifact_id,
            stored,
            filename=filename or artifact_metadata.get("filename") or Path(row["uri"]).name,
            workspace_id=workspace_id,
            workspace_name=workspace_name,
            title=title,
            mime=row["mime"],
            metadata={**artifact_metadata, **(metadata or {})},
            source_uri=source_uri or artifact_metadata.get("source_url"),
        )

    def list_resources(
        self,
        *,
        workspace_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if workspace_id:
            clauses.append("workspace_id = ?")
            params.append(workspace_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"SELECT * FROM resource {where} ORDER BY updated_at DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [self._resource_dict(row) for row in rows]

    def get_resource(self, resource_id: str, *, include_chunks: bool = False) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM resource WHERE id = ?", (resource_id,)).fetchone()
        if not row:
            return None
        resource = self._resource_dict(row)
        nodes = self.conn.execute(
            "SELECT * FROM resource_node WHERE resource_id = ? ORDER BY order_no, rowid",
            (resource_id,),
        ).fetchall()
        resource["nodes"] = [self._node_dict(node) for node in nodes]
        if include_chunks:
            chunks = self.conn.execute(
                "SELECT * FROM chunk WHERE resource_id = ? ORDER BY rowid",
                (resource_id,),
            ).fetchall()
            resource["chunks"] = [self._chunk_dict(chunk) for chunk in chunks]
        return resource

    def delete_resource(self, resource_id: str) -> dict[str, Any]:
        resource = self.get_resource(resource_id)
        if not resource:
            raise KeyError(f"resource not found: {resource_id}")
        now = now_iso()
        self.conn.execute(
            "UPDATE resource SET status = 'deleted', updated_at = ? WHERE id = ?",
            (now, resource_id),
        )
        rows = self.conn.execute("SELECT id FROM chunk WHERE resource_id = ?", (resource_id,)).fetchall()
        for row in rows:
            self.index.delete("chunk", row["id"])
            self.conn.execute(
                "DELETE FROM vector_index_item WHERE target_type = 'chunk' AND target_id = ?",
                (row["id"],),
            )
        self.conn.commit()
        return self.get_resource(resource_id) or {}

    def reindex_resource(self, resource_id: str) -> dict[str, Any]:
        resource = self.get_resource(resource_id)
        if not resource:
            raise KeyError(f"resource not found: {resource_id}")
        chunks = self.conn.execute(
            "SELECT * FROM chunk WHERE resource_id = ? ORDER BY rowid",
            (resource_id,),
        ).fetchall()
        for chunk in chunks:
            self._index_chunk(self._chunk_dict(chunk), resource)
        return self.get_resource(resource_id) or {}

    def grant_access(
        self,
        resource_id: str,
        *,
        subject_type: str,
        subject_id: str,
        permission: str = "read",
    ) -> dict[str, Any]:
        if not self.get_resource(resource_id):
            raise KeyError(f"resource not found: {resource_id}")
        self.conn.execute(
            """
            INSERT INTO resource_acl(resource_id, subject_type, subject_id, permission, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(resource_id, subject_type, subject_id) DO UPDATE SET
              permission = excluded.permission,
              created_at = excluded.created_at
            """,
            (resource_id, subject_type, subject_id, permission, now_iso()),
        )
        self.conn.commit()
        return {
            "resource_id": resource_id,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "permission": permission,
        }

    def revoke_access(self, resource_id: str, *, subject_type: str, subject_id: str) -> dict[str, Any]:
        self.conn.execute(
            """
            DELETE FROM resource_acl
            WHERE resource_id = ? AND subject_type = ? AND subject_id = ?
            """,
            (resource_id, subject_type, subject_id),
        )
        self.conn.commit()
        return {
            "resource_id": resource_id,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "revoked": True,
        }

    def list_acl(self, resource_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT *
            FROM resource_acl
            WHERE resource_id = ?
            ORDER BY created_at DESC
            """,
            (resource_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def _ingest_stored(
        self,
        stored: StoredArtifact,
        *,
        filename: str,
        workspace_id: str | None,
        workspace_name: str | None,
        title: str | None,
        mime: str,
        metadata: dict[str, Any],
        source_uri: str | None = None,
    ) -> dict[str, Any]:
        source_id = ensure_source_app(self.conn, name="manual_upload", app_type="resource")
        artifact_id = self._insert_raw_artifact(
            source_app_id=source_id,
            kind="upload",
            stored=stored,
            mime=mime,
            metadata={**metadata, "filename": filename},
        )
        return self._ingest_existing_artifact(
            artifact_id,
            stored,
            filename=filename,
            workspace_id=workspace_id,
            workspace_name=workspace_name,
            title=title,
            mime=mime,
            metadata=metadata,
            source_uri=source_uri,
        )

    def _ingest_existing_artifact(
        self,
        artifact_id: str,
        stored: StoredArtifact,
        *,
        filename: str,
        workspace_id: str | None,
        workspace_name: str | None,
        title: str | None,
        mime: str,
        metadata: dict[str, Any],
        source_uri: str | None = None,
    ) -> dict[str, Any]:
        if not workspace_id:
            workspace_id = ensure_workspace(self.conn, name=workspace_name or "Default")
        parsed = self.registry.parse(stored.path, title=title or filename, mime=mime)
        resource_id = new_id("res")
        ts = now_iso()
        self.conn.execute(
            """
            INSERT INTO resource(
              id, workspace_id, artifact_id, title, source_uri, mime, checksum,
              status, metadata_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'ready', ?, ?, ?)
            """,
            (
                resource_id,
                workspace_id,
                artifact_id,
                parsed.title,
                source_uri or stored.uri,
                mime,
                stored.checksum,
                json_dumps({**metadata, **parsed.metadata}),
                ts,
                ts,
            ),
        )

        path_to_node_id = self._persist_nodes(resource_id, parsed)
        chunks = chunk_document(parsed)
        for draft in chunks:
            node_id = path_to_node_id.get(draft.path.split("#part-", 1)[0]) or path_to_node_id.get(parsed.title)
            chunk_id = self._persist_chunk(resource_id, node_id, draft)
            chunk_record = {
                "id": chunk_id,
                "resource_id": resource_id,
                "node_id": node_id,
                "compiled_text": draft.compiled_text,
                "text": draft.text,
                "page": draft.page,
                "token_count": draft.token_count,
                "metadata": draft.metadata,
            }
            self._index_chunk(chunk_record, self.get_resource(resource_id) or {})

        self.conn.commit()
        return self.get_resource(resource_id, include_chunks=True) or {}

    def _insert_raw_artifact(
        self,
        *,
        source_app_id: str | None,
        kind: str,
        stored: StoredArtifact,
        mime: str,
        metadata: dict[str, Any],
    ) -> str:
        artifact_id = new_id("art")
        self.conn.execute(
            """
            INSERT INTO raw_artifact(
              id, source_app_id, kind, uri, checksum, mime, size, metadata_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact_id,
                source_app_id,
                kind,
                stored.uri,
                stored.checksum,
                mime,
                stored.size,
                json_dumps(metadata),
                now_iso(),
            ),
        )
        return artifact_id

    def _persist_nodes(self, resource_id: str, parsed: ParsedDocument) -> dict[str, str]:
        path_to_node_id: dict[str, str] = {}

        def insert_node(node: ParsedNode, parent_id: str | None, order_no: int) -> None:
            node_id = new_id("node")
            node_path = node.path or node.title
            path_to_node_id[node_path] = node_id
            self.conn.execute(
                """
                INSERT INTO resource_node(
                  id, resource_id, parent_id, node_type, title, path, l0_abstract,
                  l1_overview, order_no, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    node_id,
                    resource_id,
                    parent_id,
                    node.node_type,
                    node.title,
                    node_path,
                    clean_text(node.text)[:300],
                    clean_text(node.text)[:2400],
                    order_no,
                    json_dumps(node.metadata),
                ),
            )
            for child_order, child in enumerate(node.children):
                insert_node(child, node_id, child_order)

        insert_node(parsed.root, None, 0)
        return path_to_node_id

    def _persist_chunk(self, resource_id: str, node_id: str | None, draft: ChunkDraft) -> str:
        chunk_id = new_id("chk")
        self.conn.execute(
            """
            INSERT INTO chunk(
              id, resource_id, node_id, text, compiled_text, page, line_start,
              line_end, token_count, hash, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chunk_id,
                resource_id,
                node_id,
                draft.text,
                draft.compiled_text,
                draft.page,
                draft.line_start,
                draft.line_end,
                draft.token_count,
                sha256_text(draft.compiled_text),
                json_dumps({**draft.metadata, "path": draft.path, "title": draft.title}),
            ),
        )
        return chunk_id

    def _index_chunk(self, chunk: dict[str, Any], resource: dict[str, Any]) -> None:
        if resource.get("status") != "ready":
            return
        metadata = chunk.get("metadata") or {}
        payload = {
            "workspace_id": resource.get("workspace_id") or "",
            "resource_id": resource["id"],
            "resource_title": resource["title"],
            "resource_status": resource["status"],
            "mime": resource["mime"],
            "path": metadata.get("path") or "",
            "page": chunk.get("page") or 0,
            "status": "active",
        }
        vector_id = self.index.upsert("chunk", chunk["id"], chunk["compiled_text"], payload)
        record_vector_index_item(
            self.conn,
            target_type="chunk",
            target_id=chunk["id"],
            vector_id=vector_id,
            index_name=self.index.index_name,
            embedding_model=getattr(self.index, "embedding_model", "unknown"),
        )

    def _resource_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["metadata"] = json_loads(result.pop("metadata_json", None))
        return result

    def _node_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["metadata"] = json_loads(result.pop("metadata_json", None))
        return result

    def _chunk_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["metadata"] = json_loads(result.pop("metadata_json", None))
        return result
