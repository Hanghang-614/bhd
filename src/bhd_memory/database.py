from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


SCHEMA_VERSION = 1


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_app (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  type TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  config_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_artifact (
  id TEXT PRIMARY KEY,
  source_app_id TEXT REFERENCES source_app(id),
  kind TEXT NOT NULL,
  uri TEXT NOT NULL,
  checksum TEXT NOT NULL,
  mime TEXT NOT NULL,
  size INTEGER NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_raw_artifact_checksum ON raw_artifact(checksum);

CREATE TABLE IF NOT EXISTS ingest_job (
  id TEXT PRIMARY KEY,
  artifact_id TEXT REFERENCES raw_artifact(id),
  pipeline TEXT NOT NULL,
  status TEXT NOT NULL,
  stage TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}',
  result_json TEXT NOT NULL DEFAULT '{}',
  attempts INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  started_at TEXT,
  finished_at TEXT,
  updated_at TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ingest_job_status ON ingest_job(status, created_at);

CREATE TABLE IF NOT EXISTS sync_cursor (
  id TEXT PRIMARY KEY,
  source_app_id TEXT REFERENCES source_app(id),
  cursor_json TEXT NOT NULL DEFAULT '{}',
  last_seen_at TEXT,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workspace (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  root_path TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_workspace_root ON workspace(root_path) WHERE root_path IS NOT NULL;

CREATE TABLE IF NOT EXISTS conversation_session (
  id TEXT PRIMARY KEY,
  source_app_id TEXT NOT NULL REFERENCES source_app(id),
  workspace_id TEXT REFERENCES workspace(id),
  external_session_id TEXT NOT NULL,
  project_path TEXT,
  repo TEXT,
  started_at TEXT,
  ended_at TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL,
  UNIQUE(source_app_id, external_session_id)
);
CREATE INDEX IF NOT EXISTS idx_conversation_session_source ON conversation_session(source_app_id, status);
CREATE INDEX IF NOT EXISTS idx_conversation_session_workspace ON conversation_session(workspace_id, status);

CREATE TABLE IF NOT EXISTS conversation_turn (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES conversation_session(id) ON DELETE CASCADE,
  external_turn_id TEXT NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  parts_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT,
  token_count INTEGER NOT NULL DEFAULT 0,
  raw_ref TEXT,
  hash TEXT NOT NULL,
  UNIQUE(session_id, external_turn_id)
);
CREATE INDEX IF NOT EXISTS idx_conversation_turn_session ON conversation_turn(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_conversation_turn_hash ON conversation_turn(session_id, hash);

CREATE TABLE IF NOT EXISTS session_archive (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES conversation_session(id) ON DELETE CASCADE,
  archive_no INTEGER NOT NULL,
  raw_artifact_id TEXT REFERENCES raw_artifact(id),
  raw_uri TEXT NOT NULL,
  l0_abstract TEXT NOT NULL,
  l1_overview TEXT NOT NULL,
  committed_at TEXT NOT NULL,
  commit_reason TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE(session_id, archive_no)
);
CREATE INDEX IF NOT EXISTS idx_session_archive_session ON session_archive(session_id, committed_at);

CREATE TABLE IF NOT EXISTS memory (
  id TEXT PRIMARY KEY,
  scope TEXT NOT NULL,
  workspace_id TEXT REFERENCES workspace(id),
  category TEXT NOT NULL,
  content TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  confidence REAL NOT NULL DEFAULT 0.75,
  valid_at TEXT,
  invalid_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_used_at TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_status_scope ON memory(status, scope, workspace_id);
CREATE INDEX IF NOT EXISTS idx_memory_hash ON memory(hash);

CREATE TABLE IF NOT EXISTS memory_evidence (
  id TEXT PRIMARY KEY,
  memory_id TEXT NOT NULL REFERENCES memory(id) ON DELETE CASCADE,
  session_id TEXT REFERENCES conversation_session(id) ON DELETE SET NULL,
  turn_id TEXT REFERENCES conversation_turn(id) ON DELETE SET NULL,
  artifact_id TEXT REFERENCES raw_artifact(id) ON DELETE SET NULL,
  quote_ref TEXT,
  confidence REAL NOT NULL DEFAULT 0.75
);
CREATE INDEX IF NOT EXISTS idx_memory_evidence_memory ON memory_evidence(memory_id);

CREATE TABLE IF NOT EXISTS memory_entity (
  id TEXT PRIMARY KEY,
  memory_id TEXT NOT NULL REFERENCES memory(id) ON DELETE CASCADE,
  entity_text TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  normalized TEXT NOT NULL,
  canonical_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_memory_entity_normalized ON memory_entity(normalized, entity_type);

CREATE TABLE IF NOT EXISTS memory_operation (
  id TEXT PRIMARY KEY,
  archive_id TEXT REFERENCES session_archive(id) ON DELETE SET NULL,
  op TEXT NOT NULL,
  memory_id TEXT REFERENCES memory(id) ON DELETE SET NULL,
  before_json TEXT NOT NULL DEFAULT '{}',
  after_json TEXT NOT NULL DEFAULT '{}',
  reasoning TEXT,
  actor TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_operation_memory ON memory_operation(memory_id, created_at);

CREATE TABLE IF NOT EXISTS memory_relation (
  id TEXT PRIMARY KEY,
  source_memory_id TEXT NOT NULL REFERENCES memory(id) ON DELETE CASCADE,
  target_memory_id TEXT NOT NULL REFERENCES memory(id) ON DELETE CASCADE,
  relation_type TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  UNIQUE(source_memory_id, target_memory_id, relation_type)
);
CREATE INDEX IF NOT EXISTS idx_memory_relation_target ON memory_relation(target_memory_id, relation_type);

CREATE TABLE IF NOT EXISTS memory_access_log (
  id TEXT PRIMARY KEY,
  memory_id TEXT REFERENCES memory(id) ON DELETE SET NULL,
  request_id TEXT,
  query TEXT NOT NULL,
  used_in_response INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS resource (
  id TEXT PRIMARY KEY,
  workspace_id TEXT REFERENCES workspace(id),
  artifact_id TEXT NOT NULL REFERENCES raw_artifact(id),
  title TEXT NOT NULL,
  source_uri TEXT NOT NULL,
  mime TEXT NOT NULL,
  checksum TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'ready',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_resource_workspace ON resource(workspace_id, status);
CREATE INDEX IF NOT EXISTS idx_resource_checksum ON resource(checksum);

CREATE TABLE IF NOT EXISTS resource_acl (
  resource_id TEXT NOT NULL REFERENCES resource(id) ON DELETE CASCADE,
  subject_type TEXT NOT NULL,
  subject_id TEXT NOT NULL,
  permission TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(resource_id, subject_type, subject_id)
);

CREATE TABLE IF NOT EXISTS resource_node (
  id TEXT PRIMARY KEY,
  resource_id TEXT NOT NULL REFERENCES resource(id) ON DELETE CASCADE,
  parent_id TEXT REFERENCES resource_node(id) ON DELETE CASCADE,
  node_type TEXT NOT NULL,
  title TEXT NOT NULL,
  path TEXT NOT NULL,
  l0_abstract TEXT,
  l1_overview TEXT,
  order_no INTEGER NOT NULL DEFAULT 0,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_resource_node_resource ON resource_node(resource_id, parent_id);

CREATE TABLE IF NOT EXISTS chunk (
  id TEXT PRIMARY KEY,
  resource_id TEXT NOT NULL REFERENCES resource(id) ON DELETE CASCADE,
  node_id TEXT REFERENCES resource_node(id) ON DELETE SET NULL,
  text TEXT NOT NULL,
  compiled_text TEXT NOT NULL,
  page INTEGER,
  line_start INTEGER,
  line_end INTEGER,
  token_count INTEGER NOT NULL,
  hash TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_chunk_resource ON chunk(resource_id, node_id);
CREATE INDEX IF NOT EXISTS idx_chunk_hash ON chunk(hash);

CREATE TABLE IF NOT EXISTS vector_index_item (
  id TEXT PRIMARY KEY,
  target_type TEXT NOT NULL,
  target_id TEXT NOT NULL,
  vector_id TEXT NOT NULL,
  index_name TEXT NOT NULL,
  embedding_model TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(target_type, target_id, index_name)
);

CREATE TABLE IF NOT EXISTS index_document (
  target_type TEXT NOT NULL,
  target_id TEXT NOT NULL,
  content TEXT NOT NULL,
  token_count INTEGER NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL,
  PRIMARY KEY(target_type, target_id)
);

CREATE TABLE IF NOT EXISTS config (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS graph_episode (
  id TEXT PRIMARY KEY,
  target_type TEXT NOT NULL,
  target_id TEXT NOT NULL,
  group_id TEXT NOT NULL,
  name TEXT NOT NULL,
  body TEXT NOT NULL,
  source TEXT NOT NULL,
  source_description TEXT,
  reference_time TEXT NOT NULL,
  external_status TEXT NOT NULL DEFAULT 'local',
  external_ref TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  UNIQUE(target_type, target_id)
);
CREATE INDEX IF NOT EXISTS idx_graph_episode_group ON graph_episode(group_id, reference_time);

CREATE TABLE IF NOT EXISTS graph_entity (
  id TEXT PRIMARY KEY,
  episode_id TEXT NOT NULL REFERENCES graph_episode(id) ON DELETE CASCADE,
  entity_text TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  normalized TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_graph_entity_normalized ON graph_entity(normalized, entity_type);

CREATE TABLE IF NOT EXISTS graph_edge (
  id TEXT PRIMARY KEY,
  episode_id TEXT REFERENCES graph_episode(id) ON DELETE CASCADE,
  source_entity_id TEXT REFERENCES graph_entity(id) ON DELETE CASCADE,
  target_entity_id TEXT REFERENCES graph_entity(id) ON DELETE CASCADE,
  relation_type TEXT NOT NULL,
  fact TEXT NOT NULL,
  valid_at TEXT,
  invalid_at TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_graph_edge_relation ON graph_edge(relation_type, valid_at, invalid_at);

INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('schema_version', '1');
"""


def default_db_path() -> Path:
    return Path(os.environ.get("BHD_DB_PATH", ".bhd/bhd.sqlite"))


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    apply_migrations(conn)
    conn.commit()


def open_db(db_path: str | Path | None = None) -> sqlite3.Connection:
    conn = connect(db_path)
    init_db(conn)
    return conn


def apply_migrations(conn: sqlite3.Connection) -> None:
    conversation_columns = _columns(conn, "conversation_session")
    if conversation_columns and "workspace_id" not in conversation_columns:
        conn.execute("ALTER TABLE conversation_session ADD COLUMN workspace_id TEXT REFERENCES workspace(id)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_conversation_session_workspace "
            "ON conversation_session(workspace_id, status)"
        )

    ingest_job_columns = _columns(conn, "ingest_job")
    if ingest_job_columns:
        if "payload_json" not in ingest_job_columns:
            conn.execute("ALTER TABLE ingest_job ADD COLUMN payload_json TEXT NOT NULL DEFAULT '{}'")
        if "result_json" not in ingest_job_columns:
            conn.execute("ALTER TABLE ingest_job ADD COLUMN result_json TEXT NOT NULL DEFAULT '{}'")
        if "updated_at" not in ingest_job_columns:
            conn.execute("ALTER TABLE ingest_job ADD COLUMN updated_at TEXT")
            conn.execute("UPDATE ingest_job SET updated_at = COALESCE(created_at, datetime('now'))")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ingest_job_status ON ingest_job(status, created_at)")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_relation (
          id TEXT PRIMARY KEY,
          source_memory_id TEXT NOT NULL REFERENCES memory(id) ON DELETE CASCADE,
          target_memory_id TEXT NOT NULL REFERENCES memory(id) ON DELETE CASCADE,
          relation_type TEXT NOT NULL,
          metadata_json TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL,
          UNIQUE(source_memory_id, target_memory_id, relation_type)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_relation_target "
        "ON memory_relation(target_memory_id, relation_type)"
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS graph_episode (
          id TEXT PRIMARY KEY,
          target_type TEXT NOT NULL,
          target_id TEXT NOT NULL,
          group_id TEXT NOT NULL,
          name TEXT NOT NULL,
          body TEXT NOT NULL,
          source TEXT NOT NULL,
          source_description TEXT,
          reference_time TEXT NOT NULL,
          external_status TEXT NOT NULL DEFAULT 'local',
          external_ref TEXT,
          metadata_json TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL,
          UNIQUE(target_type, target_id)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_graph_episode_group ON graph_episode(group_id, reference_time)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS graph_entity (
          id TEXT PRIMARY KEY,
          episode_id TEXT NOT NULL REFERENCES graph_episode(id) ON DELETE CASCADE,
          entity_text TEXT NOT NULL,
          entity_type TEXT NOT NULL,
          normalized TEXT NOT NULL,
          metadata_json TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_graph_entity_normalized "
        "ON graph_entity(normalized, entity_type)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS graph_edge (
          id TEXT PRIMARY KEY,
          episode_id TEXT REFERENCES graph_episode(id) ON DELETE CASCADE,
          source_entity_id TEXT REFERENCES graph_entity(id) ON DELETE CASCADE,
          target_entity_id TEXT REFERENCES graph_entity(id) ON DELETE CASCADE,
          relation_type TEXT NOT NULL,
          fact TEXT NOT NULL,
          valid_at TEXT,
          invalid_at TEXT,
          metadata_json TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_graph_edge_relation "
        "ON graph_edge(relation_type, valid_at, invalid_at)"
    )


def _columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}


def row_to_dict(row: sqlite3.Row | None) -> dict:
    return dict(row) if row is not None else {}


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    try:
        conn.execute("BEGIN")
        yield conn
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()
