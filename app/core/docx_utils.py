from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET
from zipfile import ZipFile


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": WORD_NS}


def qn(tag: str) -> str:
    prefix, local = tag.split(":", 1)
    if prefix != "w":
        raise ValueError(f"Unsupported namespace prefix: {prefix}")
    return f"{{{WORD_NS}}}{local}"


@dataclass
class DocxBlock:
    kind: str
    text: str = ""
    rows: list[list[str]] | None = None


def _read_document_root(docx_path: str | Path) -> ET.Element:
    with ZipFile(docx_path) as archive:
        document_xml = archive.read("word/document.xml")
    return ET.fromstring(document_xml)


def _normalize_text(text: str) -> str:
    return text.replace("\r", "").replace("\xa0", " ").strip()


def _collect_text(node: ET.Element) -> str:
    parts: list[str] = []
    for child in node.iter():
        if child.tag == qn("w:t") and child.text:
            parts.append(child.text)
        elif child.tag == qn("w:tab"):
            parts.append("\t")
        elif child.tag in {qn("w:br"), qn("w:cr")}:
            parts.append("\n")
    return _normalize_text("".join(parts))


def _collect_cell_text(cell: ET.Element) -> str:
    paragraphs = []
    for paragraph in cell.findall(".//w:p", NS):
        text = _collect_text(paragraph)
        if text:
            paragraphs.append(text)
    return "\n".join(paragraphs).strip()


def _collect_table_rows(table: ET.Element) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in table.findall("./w:tr", NS):
        cells = [_collect_cell_text(cell) for cell in row.findall("./w:tc", NS)]
        if any(cell.strip() for cell in cells):
            rows.append(cells)
    return rows


def iter_docx_blocks(docx_path: str | Path) -> Iterable[DocxBlock]:
    root = _read_document_root(docx_path)
    body = root.find("w:body", NS)
    if body is None:
        return []

    blocks: list[DocxBlock] = []
    for child in list(body):
        if child.tag == qn("w:p"):
            text = _collect_text(child)
            if text:
                blocks.append(DocxBlock(kind="paragraph", text=text))
        elif child.tag == qn("w:tbl"):
            rows = _collect_table_rows(child)
            if rows:
                blocks.append(DocxBlock(kind="table", rows=rows))
    return blocks


def extract_docx_text(docx_path: str | Path) -> str:
    paragraphs = [block.text for block in iter_docx_blocks(docx_path) if block.kind == "paragraph" and block.text]
    return "\n".join(paragraphs).strip()


def extract_docx_tables(docx_path: str | Path) -> list[list[list[str]]]:
    return [block.rows or [] for block in iter_docx_blocks(docx_path) if block.kind == "table"]
