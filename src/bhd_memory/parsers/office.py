from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from ..utils import clean_text
from .base import ParsedDocument, ParsedNode


def _xml_text(xml: bytes, tags: set[str]) -> list[str]:
    root = ET.fromstring(xml)
    values: list[str] = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] in tags and element.text:
            values.append(element.text)
    return values


class DocxParser:
    extensions = {".docx"}
    mime_types = {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}

    def parse(self, path: str | Path, *, title: str | None = None, mime: str | None = None) -> ParsedDocument:
        file_path = Path(path)
        doc_title = title or file_path.name
        paragraphs: list[str] = []
        with zipfile.ZipFile(file_path) as archive:
            xml = archive.read("word/document.xml")
        root = ET.fromstring(xml)
        for paragraph in root.iter():
            if paragraph.tag.rsplit("}", 1)[-1] != "p":
                continue
            texts = [
                child.text
                for child in paragraph.iter()
                if child.tag.rsplit("}", 1)[-1] == "t" and child.text
            ]
            if texts:
                paragraphs.append("".join(texts))
        text = clean_text("\n".join(paragraphs))
        root_node = ParsedNode(title=doc_title, path=doc_title, text=text, node_type="document")
        return ParsedDocument(title=doc_title, mime=mime or next(iter(self.mime_types)), root=root_node)


class PptxParser:
    extensions = {".pptx"}
    mime_types = {"application/vnd.openxmlformats-officedocument.presentationml.presentation"}

    def parse(self, path: str | Path, *, title: str | None = None, mime: str | None = None) -> ParsedDocument:
        file_path = Path(path)
        doc_title = title or file_path.name
        root = ParsedNode(title=doc_title, path=doc_title, text="", node_type="document")
        with zipfile.ZipFile(file_path) as archive:
            slide_names = sorted(
                name
                for name in archive.namelist()
                if re.match(r"ppt/slides/slide\d+\.xml$", name)
            )
            for order, slide_name in enumerate(slide_names, start=1):
                texts = _xml_text(archive.read(slide_name), {"t"})
                body = clean_text("\n".join(texts))
                if body:
                    root.children.append(
                        ParsedNode(
                            title=f"Slide {order}",
                            path=f"{doc_title}/Slide {order}",
                            text=body,
                            node_type="slide",
                            metadata={"slide": order},
                        )
                    )
        root.text = "\n\n".join(child.text for child in root.children)
        return ParsedDocument(title=doc_title, mime=mime or next(iter(self.mime_types)), root=root)


class XlsxParser:
    extensions = {".xlsx"}
    mime_types = {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}

    def parse(self, path: str | Path, *, title: str | None = None, mime: str | None = None) -> ParsedDocument:
        file_path = Path(path)
        doc_title = title or file_path.name
        root = ParsedNode(title=doc_title, path=doc_title, text="", node_type="document")
        with zipfile.ZipFile(file_path) as archive:
            shared_strings = self._shared_strings(archive)
            sheet_names = sorted(
                name for name in archive.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", name)
            )
            for order, sheet_name in enumerate(sheet_names, start=1):
                text = self._sheet_text(archive.read(sheet_name), shared_strings)
                if text:
                    root.children.append(
                        ParsedNode(
                            title=f"Sheet {order}",
                            path=f"{doc_title}/Sheet {order}",
                            text=text,
                            node_type="sheet",
                            metadata={"sheet": order},
                        )
                    )
        root.text = "\n\n".join(child.text for child in root.children)
        return ParsedDocument(title=doc_title, mime=mime or next(iter(self.mime_types)), root=root)

    def _shared_strings(self, archive: zipfile.ZipFile) -> list[str]:
        try:
            xml = archive.read("xl/sharedStrings.xml")
        except KeyError:
            return []
        root = ET.fromstring(xml)
        strings: list[str] = []
        for si in root.iter():
            if si.tag.rsplit("}", 1)[-1] != "si":
                continue
            texts = [
                child.text
                for child in si.iter()
                if child.tag.rsplit("}", 1)[-1] == "t" and child.text
            ]
            strings.append("".join(texts))
        return strings

    def _sheet_text(self, xml: bytes, shared_strings: list[str]) -> str:
        root = ET.fromstring(xml)
        rows: list[str] = []
        for row in root.iter():
            if row.tag.rsplit("}", 1)[-1] != "row":
                continue
            cells: list[str] = []
            for cell in row:
                if cell.tag.rsplit("}", 1)[-1] != "c":
                    continue
                cell_type = cell.attrib.get("t")
                value = ""
                for child in cell:
                    if child.tag.rsplit("}", 1)[-1] == "v" and child.text is not None:
                        value = child.text
                        break
                if cell_type == "s" and value.isdigit() and int(value) < len(shared_strings):
                    value = shared_strings[int(value)]
                if value:
                    cells.append(value)
            if cells:
                rows.append(" | ".join(cells))
        return clean_text("\n".join(rows))

