from __future__ import annotations

from dataclasses import dataclass, field

from .parsers import ParsedDocument, ParsedNode
from .utils import clean_text, rough_token_count, word_tokens


@dataclass(frozen=True)
class ChunkDraft:
    text: str
    compiled_text: str
    title: str
    path: str
    node_type: str
    page: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    token_count: int = 0
    metadata: dict = field(default_factory=dict)


def chunk_document(
    parsed: ParsedDocument,
    *,
    max_tokens: int = 900,
    overlap_tokens: int = 90,
) -> list[ChunkDraft]:
    chunks: list[ChunkDraft] = []
    nodes = parsed.root.children or [parsed.root]
    for node in nodes:
        chunks.extend(_chunk_node(parsed.title, node, max_tokens=max_tokens, overlap_tokens=overlap_tokens))
    return chunks


def _chunk_node(
    document_title: str,
    node: ParsedNode,
    *,
    max_tokens: int,
    overlap_tokens: int,
) -> list[ChunkDraft]:
    text = clean_text(node.text)
    if not text:
        return []

    line_count = max(1, text.count("\n") + 1)
    token_count = rough_token_count(text)
    if token_count <= max_tokens:
        return [
            ChunkDraft(
                text=text,
                compiled_text=_compiled_text(document_title, node.path or node.title, text),
                title=node.title,
                path=node.path or node.title,
                node_type=node.node_type,
                page=node.metadata.get("page"),
                line_start=1,
                line_end=line_count,
                token_count=token_count,
                metadata=dict(node.metadata),
            )
        ]

    tokens = word_tokens(text)
    if not tokens:
        return []

    chunks: list[ChunkDraft] = []
    step = max(1, max_tokens - overlap_tokens)
    for start in range(0, len(tokens), step):
        window = tokens[start : start + max_tokens]
        if not window:
            continue
        body = " ".join(window)
        part_no = len(chunks) + 1
        path = f"{node.path or node.title}#part-{part_no}"
        chunks.append(
            ChunkDraft(
                text=body,
                compiled_text=_compiled_text(document_title, path, body),
                title=f"{node.title} part {part_no}",
                path=path,
                node_type=node.node_type,
                page=node.metadata.get("page"),
                token_count=len(window),
                metadata={**node.metadata, "part_no": part_no},
            )
        )
        if start + max_tokens >= len(tokens):
            break
    return chunks


def _compiled_text(document_title: str, path: str, text: str) -> str:
    return clean_text(f"Document: {document_title}\nPath: {path}\n\n{text}")

