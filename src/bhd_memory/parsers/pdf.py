from __future__ import annotations

from pathlib import Path

from ..utils import clean_text
from .base import ParsedDocument, ParsedNode


class PdfParser:
    extensions = {".pdf"}
    mime_types = {"application/pdf"}

    def parse(self, path: str | Path, *, title: str | None = None, mime: str | None = None) -> ParsedDocument:
        from pypdf import PdfReader

        file_path = Path(path)
        doc_title = title or file_path.name
        reader = PdfReader(str(file_path))
        root = ParsedNode(title=doc_title, path=doc_title, text="", node_type="document")
        for index, page in enumerate(reader.pages, start=1):
            text = clean_text(page.extract_text() or "")
            if text:
                root.children.append(
                    ParsedNode(
                        title=f"Page {index}",
                        path=f"{doc_title}/Page {index}",
                        text=text,
                        node_type="page",
                        metadata={"page": index},
                    )
                )
        root.text = "\n\n".join(child.text for child in root.children)
        return ParsedDocument(title=doc_title, mime=mime or "application/pdf", root=root)

