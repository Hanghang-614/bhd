from __future__ import annotations

import uuid
from typing import Any

from qdrant_client import QdrantClient, models

from ..config import Settings
from .base import SearchHit
from .embeddings import dense_hash_embedding, sparse_token_embedding


class QdrantIndexBackend:
    index_name = "qdrant_dense_sparse"
    embedding_model = "bhd-hash-dense-sparse-v1"

    def __init__(
        self,
        *,
        url: str | None = None,
        collection_name: str | None = None,
        embedding_dim: int | None = None,
    ) -> None:
        settings = Settings.from_env()
        self.url = url or settings.qdrant_url
        self.collection_name = collection_name or settings.qdrant_collection
        self.embedding_dim = embedding_dim or settings.embedding_dim
        if self.url in {":memory:", "memory"}:
            self.client = QdrantClient(":memory:")
        elif self.url.startswith("path:"):
            self.client = QdrantClient(path=self.url.removeprefix("path:"))
        else:
            self.client = QdrantClient(url=self.url)

    def ensure_ready(self) -> None:
        if self.client.collection_exists(self.collection_name):
            return
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config={
                "dense": models.VectorParams(
                    size=self.embedding_dim,
                    distance=models.Distance.COSINE,
                )
            },
            sparse_vectors_config={
                "sparse": models.SparseVectorParams(
                    index=models.SparseIndexParams(on_disk=False)
                )
            },
        )

    def reset(self) -> None:
        if self.client.collection_exists(self.collection_name):
            self.client.delete_collection(self.collection_name)
        self.ensure_ready()

    def upsert(self, target_type: str, target_id: str, content: str, payload: dict[str, Any]) -> str:
        self.ensure_ready()
        point_id = self._point_id(target_type, target_id)
        sparse = sparse_token_embedding(content)
        qdrant_payload = {
            **payload,
            "target_type": target_type,
            "target_id": target_id,
            "embedding_model": self.embedding_model,
            "content_preview": content[:500],
        }
        point = models.PointStruct(
            id=point_id,
            vector={
                "dense": dense_hash_embedding(content, self.embedding_dim),
                "sparse": models.SparseVector(indices=sparse.indices, values=sparse.values),
            },
            payload=qdrant_payload,
        )
        self.client.upsert(collection_name=self.collection_name, points=[point])
        return point_id

    def delete(self, target_type: str, target_id: str) -> None:
        self.ensure_ready()
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=models.PointIdsList(points=[self._point_id(target_type, target_id)]),
        )

    def search(
        self,
        query: str,
        *,
        target_types: list[str] | None = None,
        filters: dict[str, Any] | None = None,
        limit: int = 10,
    ) -> list[SearchHit]:
        self.ensure_ready()
        query_filter = self._build_filter(target_types, filters or {})
        sparse = sparse_token_embedding(query)
        dense_query = dense_hash_embedding(query, self.embedding_dim)
        sparse_query = models.SparseVector(indices=sparse.indices, values=sparse.values)
        q_limit = max(limit * 4, 20)

        try:
            response = self.client.query_points(
                collection_name=self.collection_name,
                prefetch=[
                    models.Prefetch(
                        query=dense_query,
                        using="dense",
                        filter=query_filter,
                        limit=q_limit,
                    ),
                    models.Prefetch(
                        query=sparse_query,
                        using="sparse",
                        filter=query_filter,
                        limit=q_limit,
                    ),
                ],
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=limit,
                with_payload=True,
            )
            points = getattr(response, "points", response)
            return [self._hit_from_point(point, {"fusion": "rrf"}) for point in points]
        except Exception:
            return self._fallback_two_pass(dense_query, sparse_query, query_filter, limit)

    def _fallback_two_pass(
        self,
        dense_query: list[float],
        sparse_query: models.SparseVector,
        query_filter: models.Filter | None,
        limit: int,
    ) -> list[SearchHit]:
        # Older Qdrant deployments may not expose Query API fusion. In that case do two
        # named-vector searches and fuse ranks in the application with a small RRF step.
        merged: dict[str, tuple[Any, float, dict[str, float]]] = {}
        for channel, query, using in (
            ("dense", dense_query, "dense"),
            ("sparse", sparse_query, "sparse"),
        ):
            response = self.client.query_points(
                collection_name=self.collection_name,
                query=query,
                using=using,
                query_filter=query_filter,
                limit=max(limit * 4, 20),
                with_payload=True,
            )
            points = getattr(response, "points", response)
            for rank, point in enumerate(points, start=1):
                point_id = str(point.id)
                score = 1.0 / (60.0 + rank)
                existing = merged.get(point_id)
                if existing is None:
                    merged[point_id] = (point, score, {channel: float(getattr(point, "score", 0.0))})
                else:
                    old_point, old_score, details = existing
                    details[channel] = float(getattr(point, "score", 0.0))
                    merged[point_id] = (old_point, old_score + score, details)

        ranked = sorted(merged.values(), key=lambda item: item[1], reverse=True)[:limit]
        hits: list[SearchHit] = []
        for point, score, details in ranked:
            hit = self._hit_from_point(point, {"fusion": "client_rrf", **details})
            hits.append(
                SearchHit(
                    target_type=hit.target_type,
                    target_id=hit.target_id,
                    score=score,
                    payload=hit.payload,
                    score_details=hit.score_details,
                )
            )
        return hits

    def _build_filter(
        self,
        target_types: list[str] | None,
        filters: dict[str, Any],
    ) -> models.Filter | None:
        must: list[models.FieldCondition] = []
        if target_types:
            if len(target_types) == 1:
                must.append(
                    models.FieldCondition(
                        key="target_type",
                        match=models.MatchValue(value=target_types[0]),
                    )
                )
            else:
                must.append(
                    models.FieldCondition(
                        key="target_type",
                        match=models.MatchAny(any=target_types),
                    )
                )

        for key, value in filters.items():
            if value is None:
                continue
            if isinstance(value, (list, tuple, set)):
                must.append(models.FieldCondition(key=key, match=models.MatchAny(any=list(value))))
            else:
                must.append(models.FieldCondition(key=key, match=models.MatchValue(value=value)))
        return models.Filter(must=must) if must else None

    def _hit_from_point(self, point: Any, score_details: dict[str, Any]) -> SearchHit:
        payload = dict(getattr(point, "payload", None) or {})
        return SearchHit(
            target_type=payload.get("target_type", ""),
            target_id=payload.get("target_id", ""),
            score=float(getattr(point, "score", 0.0) or 0.0),
            payload=payload,
            score_details=score_details,
        )

    def _point_id(self, target_type: str, target_id: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"bhd:{target_type}:{target_id}"))
