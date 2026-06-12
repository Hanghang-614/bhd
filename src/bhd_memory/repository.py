from __future__ import annotations

import sqlite3
from pathlib import Path

from .utils import json_dumps, new_id, now_iso


def ensure_source_app(
    conn: sqlite3.Connection,
    *,
    name: str,
    app_type: str,
    config: dict | None = None,
) -> str:
    row = conn.execute("SELECT id FROM source_app WHERE name = ?", (name,)).fetchone()
    if row:
        return str(row["id"])
    source_id = new_id("src")
    conn.execute(
        """
        INSERT INTO source_app(id, name, type, enabled, config_json, created_at)
        VALUES (?, ?, ?, 1, ?, ?)
        """,
        (source_id, name, app_type, json_dumps(config or {}), now_iso()),
    )
    return source_id


def ensure_workspace(
    conn: sqlite3.Connection,
    *,
    name: str | None = None,
    root_path: str | Path | None = None,
    metadata: dict | None = None,
) -> str:
    normalized_root = str(Path(root_path).resolve()) if root_path else None
    if normalized_root:
        row = conn.execute("SELECT id FROM workspace WHERE root_path = ?", (normalized_root,)).fetchone()
        if row:
            return str(row["id"])

    workspace_name = name or (Path(normalized_root).name if normalized_root else "Default")
    row = conn.execute(
        "SELECT id FROM workspace WHERE name = ? AND (root_path IS NULL OR root_path = '')",
        (workspace_name,),
    ).fetchone()
    if row and normalized_root is None:
        return str(row["id"])

    workspace_id = new_id("ws")
    conn.execute(
        """
        INSERT INTO workspace(id, name, root_path, metadata_json, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (workspace_id, workspace_name, normalized_root, json_dumps(metadata or {}), now_iso()),
    )
    return workspace_id


def record_vector_index_item(
    conn: sqlite3.Connection,
    *,
    target_type: str,
    target_id: str,
    vector_id: str,
    index_name: str,
    embedding_model: str,
) -> None:
    conn.execute(
        """
        INSERT INTO vector_index_item(
          id, target_type, target_id, vector_id, index_name, embedding_model, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(target_type, target_id, index_name) DO UPDATE SET
          vector_id = excluded.vector_id,
          embedding_model = excluded.embedding_model,
          created_at = excluded.created_at
        """,
        (
            new_id("vix"),
            target_type,
            target_id,
            vector_id,
            index_name,
            embedding_model,
            now_iso(),
        ),
    )

