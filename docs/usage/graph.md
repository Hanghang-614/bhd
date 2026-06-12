# Graph And Temporal Memory

BHD keeps a local graph truth layer in SQLite:

- `graph_episode`: provenance episode for a memory or resource chunk.
- `graph_entity`: extracted entities for each episode.
- `graph_edge`: local facts, co-mentions, and temporal relations.

Conflict approval creates temporal provenance:

1. New `conflict` memory is approved.
2. Related old active memories are archived.
3. Old memories get `invalid_at`.
4. A `memory_relation` and `graph_edge` with `relation_type=supersedes` are created.

Sync local graph:

```bash
uv run bhd-memory graph-sync
uv run bhd-memory graph-episodes
uv run bhd-memory graph-search Qdrant
```

API:

```bash
curl -X POST http://127.0.0.1:8765/api/graph/sync \
  -H 'content-type: application/json' \
  -d '{"external":false}'

curl http://127.0.0.1:8765/api/graph/episodes
curl 'http://127.0.0.1:8765/api/graph/entities/search?query=Qdrant'
```

Optional Graphiti-compatible HTTP sync:

```bash
export BHD_GRAPHITI_URL=http://127.0.0.1:8000
uv run bhd-memory graph-sync --external
```

External sync sends episodes to Graphiti server's `/messages` endpoint while preserving the local SQLite graph as the truth layer.

