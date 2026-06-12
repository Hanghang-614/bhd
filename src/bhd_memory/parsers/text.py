from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

from ..utils import clean_text
from .base import ParsedDocument, ParsedNode


class MarkdownParser:
    extensions = {".md", ".mdx", ".markdown"}
    mime_types = {"text/markdown", "text/x-markdown"}

    def parse(self, path: str | Path, *, title: str | None = None, mime: str | None = None) -> ParsedDocument:
        file_path = Path(path)
        text = file_path.read_text(encoding="utf-8", errors="replace")
        doc_title = title or file_path.name
        root = ParsedNode(title=doc_title, path=doc_title, text="", node_type="document")
        sections = _split_markdown_sections(text, doc_title)
        if sections:
            root.children = sections
            root.text = "\n\n".join(section.text for section in sections)
        else:
            root.text = clean_text(text)
        return ParsedDocument(title=doc_title, mime=mime or "text/markdown", root=root)


def _split_markdown_sections(text: str, doc_title: str) -> list[ParsedNode]:
    sections: list[ParsedNode] = []
    current_title = doc_title
    current_level = 0
    buffer: list[str] = []

    def flush() -> None:
        if not buffer:
            return
        body = clean_text("\n".join(buffer))
        if body:
            path = current_title if current_level else doc_title
            sections.append(
                ParsedNode(
                    title=current_title,
                    path=path,
                    text=body,
                    node_type="section" if current_level else "document",
                    metadata={"heading_level": current_level},
                )
            )

    for line in text.splitlines():
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match:
            flush()
            buffer = []
            current_level = len(match.group(1))
            current_title = match.group(2).strip()
        else:
            buffer.append(line)
    flush()
    return sections


class _VisibleTextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self.skip_depth += 1
        if tag in {"p", "br", "div", "section", "article", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self.skip_depth:
            self.skip_depth -= 1
        if tag in {"p", "div", "section", "article", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)


class HtmlParser:
    extensions = {".html", ".htm"}
    mime_types = {"text/html", "application/xhtml+xml"}

    def parse(self, path: str | Path, *, title: str | None = None, mime: str | None = None) -> ParsedDocument:
        file_path = Path(path)
        html = file_path.read_text(encoding="utf-8", errors="replace")
        parser = _VisibleTextHTMLParser()
        parser.feed(html)
        doc_title = title or file_path.name
        text = clean_text(" ".join(parser.parts))
        root = ParsedNode(title=doc_title, path=doc_title, text=text, node_type="document")
        return ParsedDocument(title=doc_title, mime=mime or "text/html", root=root)

