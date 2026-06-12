from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ..utils import clean_text


@dataclass
class ParsedNode:
    title: str
    text: str
    node_type: str = "section"
    path: str = ""
    metadata: dict = field(default_factory=dict)
    children: list["ParsedNode"] = field(default_factory=list)

    def all_nodes(self) -> list["ParsedNode"]:
        nodes = [self]
        for child in self.children:
            nodes.extend(child.all_nodes())
        return nodes


@dataclass
class ParsedDocument:
    title: str
    mime: str
    root: ParsedNode
    metadata: dict = field(default_factory=dict)


class Parser(Protocol):
    extensions: set[str]
    mime_types: set[str]

    def parse(self, path: str | Path, *, title: str | None = None, mime: str | None = None) -> ParsedDocument:
        ...


class ParserRegistry:
    def __init__(self) -> None:
        self._parsers: list[Parser] = []

    def register(self, parser: Parser) -> None:
        self._parsers.append(parser)

    def get(self, path: str | Path, mime: str | None = None) -> Parser:
        suffix = Path(path).suffix.lower()
        for parser in self._parsers:
            if suffix in parser.extensions or (mime and mime in parser.mime_types):
                return parser
        return PlainTextParser()

    def parse(self, path: str | Path, *, title: str | None = None, mime: str | None = None) -> ParsedDocument:
        return self.get(path, mime).parse(path, title=title, mime=mime)


class PlainTextParser:
    extensions = {".txt", ".log", ".json", ".jsonl", ".csv", ".tsv", ""}
    mime_types = {"text/plain", "application/json", "application/jsonl", "text/csv"}

    def parse(self, path: str | Path, *, title: str | None = None, mime: str | None = None) -> ParsedDocument:
        file_path = Path(path)
        data = file_path.read_bytes()
        text = data.decode("utf-8", errors="replace")
        doc_title = title or file_path.name
        root = ParsedNode(title=doc_title, path=doc_title, text=clean_text(text), node_type="document")
        return ParsedDocument(title=doc_title, mime=mime or "text/plain", root=root)


def default_registry() -> ParserRegistry:
    from .office import DocxParser, PptxParser, XlsxParser
    from .pdf import PdfParser
    from .text import HtmlParser, MarkdownParser

    registry = ParserRegistry()
    registry.register(MarkdownParser())
    registry.register(HtmlParser())
    registry.register(PdfParser())
    registry.register(DocxParser())
    registry.register(PptxParser())
    registry.register(XlsxParser())
    registry.register(PlainTextParser())
    return registry

