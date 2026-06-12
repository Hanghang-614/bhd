from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

from ..utils import word_tokens


@dataclass(frozen=True)
class SparseEmbedding:
    indices: list[int]
    values: list[float]


def _hash_int(value: str) -> int:
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:16], 16)


def dense_hash_embedding(text: str, dim: int = 384) -> list[float]:
    vector = [0.0] * dim
    tokens = word_tokens(text)
    if not tokens:
        tokens = ["_empty"]

    for token in tokens:
        digest = _hash_int(token)
        index = digest % dim
        sign = 1.0 if ((digest >> 9) & 1) else -1.0
        vector[index] += sign

    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def sparse_token_embedding(text: str) -> SparseEmbedding:
    counts: dict[int, int] = {}
    for token in word_tokens(text) or ["_empty"]:
        # Qdrant sparse indices are unsigned integer dimensions. A stable hash keeps the
        # representation deterministic without maintaining a separate vocabulary table.
        index = _hash_int(token) % 2_000_000_000
        counts[index] = counts.get(index, 0) + 1

    indices = sorted(counts)
    values = [math.sqrt(float(counts[index])) for index in indices]
    norm = math.sqrt(sum(value * value for value in values)) or 1.0
    return SparseEmbedding(indices=indices, values=[value / norm for value in values])

