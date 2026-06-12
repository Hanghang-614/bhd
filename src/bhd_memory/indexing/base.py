from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class SearchHit:
    target_type: str
    target_id: str
    score: float
    payload: dict[str, Any] = field(default_factory=dict)
    score_details: dict[str, Any] = field(default_factory=dict)


class IndexBackend(Protocol):
    index_name: str

    def ensure_ready(self) -> None:
        ...

    def upsert(self, target_type: str, target_id: str, content: str, payload: dict[str, Any]) -> str:
        ...

    def delete(self, target_type: str, target_id: str) -> None:
        ...

    def search(
        self,
        query: str,
        *,
        target_types: list[str] | None = None,
        filters: dict[str, Any] | None = None,
        limit: int = 10,
    ) -> list[SearchHit]:
        ...

