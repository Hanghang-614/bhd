from __future__ import annotations

import json
import os
import sqlite3
from typing import Any
from urllib.request import Request, urlopen

from .memory import extract_entities
from .utils import json_dumps, json_loads, new_id, normalize_for_hash, now_iso


class GraphService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def sync_all(self, *, external: bool = False, limit: int | None = None) -> dict[str, Any]:
        memories = self.conn.execute(
            """
            SELECT id FROM memory
            WHERE status IN ('active', 'archived', 'conflict', 'pending')
            ORDER BY updated_at DESC
            """
            + (" LIMIT ?" if limit else ""),
            (limit,) if limit else (),
        ).fetchall()
        chunks = self.conn.execute(
            """
            SELECT c.id
            FROM chunk c
            JOIN resource r ON r.id = c.resource_id
            WHERE r.status = 'ready'
            ORDER BY r.updated_at DESC
            """
            + (" LIMIT ?" if limit else ""),
            (limit,) if limit else (),
        ).fetchall()

        memory_count = 0
        chunk_count = 0
        for row in memories:
            self.sync_memory(row["id"], external=external)
            memory_count += 1
        for row in chunks:
            self.sync_chunk(row["id"], external=external)
            chunk_count += 1
        self.sync_memory_relations()
        return {
            "memories_synced": memory_count,
            "chunks_synced": chunk_count,
            "external": external,
        }

    def sync_memory(self, memory_id: str, *, external: bool = False) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM memory WHERE id = ?", (memory_id,)).fetchone()
        if not row:
            raise KeyError(f"memory not found: {memory_id}")
        group_id = row["workspace_id"] or row["scope"] or "global"
        episode = self._upsert_episode(
            target_type="memory",
            target_id=memory_id,
            group_id=group_id,
            name=f"Memory {row['category']}",
            body=row["content"],
            source="json",
            source_description=f"BHD memory/{row['category']}",
            reference_time=row["valid_at"] or row["created_at"],
            metadata={
                "scope": row["scope"],
                "status": row["status"],
                "category": row["category"],
                "invalid_at": row["invalid_at"],
            },
        )
        self._replace_entities(episode["id"], row["content"], metadata={"target_type": "memory"})
        if external:
            self._sync_external_graphiti(episode["id"])
        return self.get_episode(episode["id"]) or episode

    def sync_chunk(self, chunk_id: str, *, external: bool = False) -> dict[str, Any]:
        row = self.conn.execute(
            """
            SELECT c.*, r.title AS resource_title, r.workspace_id, r.source_uri, r.updated_at AS resource_updated_at
            FROM chunk c
            JOIN resource r ON r.id = c.resource_id
            WHERE c.id = ?
            """,
            (chunk_id,),
        ).fetchone()
        if not row:
            raise KeyError(f"chunk not found: {chunk_id}")
        group_id = row["workspace_id"] or "default"
        episode = self._upsert_episode(
            target_type="chunk",
            target_id=chunk_id,
            group_id=group_id,
            name=f"Resource {row['resource_title']}",
            body=row["compiled_text"],
            source="text",
            source_description=f"BHD resource/{row['resource_id']}",
            reference_time=row["resource_updated_at"],
            metadata={
                "resource_id": row["resource_id"],
                "resource_title": row["resource_title"],
                "source_uri": row["source_uri"],
                "page": row["page"],
            },
        )
        self._replace_entities(episode["id"], row["compiled_text"], metadata={"target_type": "chunk"})
        if external:
            self._sync_external_graphiti(episode["id"])
        return self.get_episode(episode["id"]) or episode

    def sync_memory_relations(self) -> dict[str, Any]:
        rows = self.conn.execute(
            """
            SELECT mr.*, source_episode.id AS source_episode_id, target_episode.id AS target_episode_id,
                   source.content AS source_content, target.content AS target_content,
                   source.valid_at AS source_valid_at, target.invalid_at AS target_invalid_at
            FROM memory_relation mr
            JOIN memory source ON source.id = mr.source_memory_id
            JOIN memory target ON target.id = mr.target_memory_id
            LEFT JOIN graph_episode source_episode
              ON source_episode.target_type = 'memory' AND source_episode.target_id = source.id
            LEFT JOIN graph_episode target_episode
              ON target_episode.target_type = 'memory' AND target_episode.target_id = target.id
            """
        ).fetchall()
        count = 0
        for row in rows:
            source_episode_id = row["source_episode_id"]
            target_episode_id = row["target_episode_id"]
            if not source_episode_id:
                source_episode_id = self.sync_memory(row["source_memory_id"])["id"]
            if not target_episode_id:
                target_episode_id = self.sync_memory(row["target_memory_id"])["id"]
            self.conn.execute(
                """
                INSERT OR IGNORE INTO graph_edge(
                  id, episode_id, source_entity_id, target_entity_id, relation_type,
                  fact, valid_at, invalid_at, metadata_json, created_at
                )
                VALUES (?, ?, NULL, NULL, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id("gedge"),
                    source_episode_id,
                    row["relation_type"],
                    f"{row['source_memory_id']} {row['relation_type']} {row['target_memory_id']}",
                    row["source_valid_at"],
                    row["target_invalid_at"],
                    json_dumps(
                        {
                            "source_memory_id": row["source_memory_id"],
                            "target_memory_id": row["target_memory_id"],
                            "target_episode_id": target_episode_id,
                        }
                    ),
                    now_iso(),
                ),
            )
            count += 1
        self.conn.commit()
        return {"relations_synced": count}

    def list_episodes(
        self,
        *,
        group_id: str | None = None,
        target_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if group_id:
            clauses.append("group_id = ?")
            params.append(group_id)
        if target_type:
            clauses.append("target_type = ?")
            params.append(target_type)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"SELECT * FROM graph_episode {where} ORDER BY reference_time DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [self._episode_dict(row) for row in rows]

    def get_episode(self, episode_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM graph_episode WHERE id = ?", (episode_id,)).fetchone()
        if not row:
            return None
        episode = self._episode_dict(row)
        episode["entities"] = self.episode_entities(episode_id)
        episode["edges"] = self.episode_edges(episode_id)
        return episode

    def episode_entities(self, episode_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM graph_entity WHERE episode_id = ? ORDER BY entity_text",
            (episode_id,),
        ).fetchall()
        return [self._entity_dict(row) for row in rows]

    def episode_edges(self, episode_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM graph_edge WHERE episode_id = ? ORDER BY created_at DESC",
            (episode_id,),
        ).fetchall()
        return [self._edge_dict(row) for row in rows]

    def search_entities(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        normalized = normalize_for_hash(query)
        rows = self.conn.execute(
            """
            SELECT ge.*, ep.target_type, ep.target_id, ep.name AS episode_name
            FROM graph_entity ge
            JOIN graph_episode ep ON ep.id = ge.episode_id
            WHERE ge.normalized LIKE ?
            ORDER BY ep.reference_time DESC
            LIMIT ?
            """,
            (f"%{normalized}%", limit),
        ).fetchall()
        return [self._entity_dict(row) | {"target_type": row["target_type"], "target_id": row["target_id"], "episode_name": row["episode_name"]} for row in rows]

    def _upsert_episode(
        self,
        *,
        target_type: str,
        target_id: str,
        group_id: str,
        name: str,
        body: str,
        source: str,
        source_description: str,
        reference_time: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT id FROM graph_episode WHERE target_type = ? AND target_id = ?",
            (target_type, target_id),
        ).fetchone()
        if row:
            episode_id = row["id"]
            self.conn.execute(
                """
                UPDATE graph_episode
                SET group_id = ?, name = ?, body = ?, source = ?, source_description = ?,
                    reference_time = ?, metadata_json = ?
                WHERE id = ?
                """,
                (
                    group_id,
                    name,
                    body,
                    source,
                    source_description,
                    reference_time,
                    json_dumps(metadata),
                    episode_id,
                ),
            )
        else:
            episode_id = new_id("gepi")
            self.conn.execute(
                """
                INSERT INTO graph_episode(
                  id, target_type, target_id, group_id, name, body, source,
                  source_description, reference_time, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    episode_id,
                    target_type,
                    target_id,
                    group_id,
                    name,
                    body,
                    source,
                    source_description,
                    reference_time,
                    json_dumps(metadata),
                    now_iso(),
                ),
            )
        self.conn.commit()
        return self.get_episode(episode_id) or {"id": episode_id}

    def _replace_entities(self, episode_id: str, text: str, *, metadata: dict[str, Any]) -> None:
        self.conn.execute("DELETE FROM graph_entity WHERE episode_id = ?", (episode_id,))
        entities = extract_entities(text)
        created_ids: list[str] = []
        for entity_text, entity_type in entities:
            entity_id = new_id("gent")
            self.conn.execute(
                """
                INSERT INTO graph_entity(
                  id, episode_id, entity_text, entity_type, normalized, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entity_id,
                    episode_id,
                    entity_text,
                    entity_type,
                    normalize_for_hash(entity_text),
                    json_dumps(metadata),
                    now_iso(),
                ),
            )
            created_ids.append(entity_id)
        self.conn.execute("DELETE FROM graph_edge WHERE episode_id = ? AND relation_type = 'co_mentions'", (episode_id,))
        if len(created_ids) > 1:
            source = created_ids[0]
            for target in created_ids[1:]:
                self.conn.execute(
                    """
                    INSERT INTO graph_edge(
                      id, episode_id, source_entity_id, target_entity_id, relation_type,
                      fact, metadata_json, created_at
                    )
                    VALUES (?, ?, ?, ?, 'co_mentions', ?, '{}', ?)
                    """,
                    (new_id("gedge"), episode_id, source, target, "Entities co-occur in episode", now_iso()),
                )
        self.conn.commit()

    def _sync_external_graphiti(self, episode_id: str) -> None:
        base_url = os.environ.get("BHD_GRAPHITI_URL", "").rstrip("/")
        if not base_url:
            return
        episode = self.get_episode(episode_id)
        if not episode:
            return
        payload = {
            "group_id": episode["group_id"],
            "messages": [
                {
                    "uuid": episode["id"],
                    "name": episode["name"],
                    "role_type": episode["source"],
                    "role": episode["target_type"],
                    "content": episode["body"],
                    "timestamp": episode["reference_time"],
                    "source_description": episode.get("source_description"),
                }
            ],
        }
        request = Request(
            f"{base_url}/messages",
            data=json.dumps(payload).encode("utf-8"),
            headers={"content-type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=int(os.environ.get("BHD_GRAPHITI_TIMEOUT", "30"))) as response:
                response_body = response.read().decode("utf-8")
            status = "synced"
            ref = response_body[:1000]
        except OSError as exc:
            status = "failed"
            ref = str(exc)
        self.conn.execute(
            """
            UPDATE graph_episode
            SET external_status = ?, external_ref = ?
            WHERE id = ?
            """,
            (status, ref, episode_id),
        )
        self.conn.commit()

    def _episode_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["metadata"] = json_loads(result.pop("metadata_json", None))
        return result

    def _entity_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["metadata"] = json_loads(result.pop("metadata_json", None))
        return result

    def _edge_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["metadata"] = json_loads(result.pop("metadata_json", None))
        return result

