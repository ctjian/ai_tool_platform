"""Convert GROBID TEI XML to normalized markdown."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
import xml.etree.ElementTree as ET


TEI_NS = {"tei": "http://www.tei-c.org/ns/1.0"}


@dataclass
class SectionMeta:
    section_id: str
    level: int
    title: str
    order: int
    page_start: Optional[int]
    page_end: Optional[int]
    char_start: int
    char_end: int


@dataclass
class MarkdownParseResult:
    title: str
    abstract: str
    markdown: str
    sections: List[SectionMeta]


def _norm_text(value: str) -> str:
    return " ".join((value or "").split())


def _collect_text(el: Optional[ET.Element]) -> str:
    if el is None:
        return ""
    return _norm_text("".join(el.itertext()))


def _extract_title(root: ET.Element) -> str:
    title_el = root.find(".//tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title", TEI_NS)
    return _collect_text(title_el)


def _extract_abstract(root: ET.Element) -> str:
    abstract_el = root.find(".//tei:teiHeader/tei:profileDesc/tei:abstract", TEI_NS)
    return _collect_text(abstract_el)


def _collect_sections(root: ET.Element) -> List[tuple[str, str]]:
    body = root.find(".//tei:text/tei:body", TEI_NS)
    if body is None:
        return []

    sections: List[tuple[str, str]] = []
    current_title = "Body"
    current_paragraphs: List[str] = []

    def flush():
        nonlocal current_paragraphs, current_title
        text = "\n\n".join(p for p in current_paragraphs if p)
        if text.strip():
            sections.append((current_title, text))
        current_paragraphs = []

    for el in body.iter():
        local = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        if local == "head":
            heading = _collect_text(el)
            if heading:
                flush()
                current_title = heading
        elif local == "p":
            para = _collect_text(el)
            if para:
                current_paragraphs.append(para)

    flush()
    return sections


def tei_to_markdown(tei_path: Path, markdown_path: Path) -> MarkdownParseResult:
    """
    Convert TEI XML to normalized markdown + section metadata.
    """
    xml_text = tei_path.read_text(encoding="utf-8", errors="ignore")
    root = ET.fromstring(xml_text)

    title = _extract_title(root) or "Untitled Paper"
    abstract = _extract_abstract(root)
    sec_pairs = _collect_sections(root)
    if not sec_pairs:
        sec_pairs = [("Body", _norm_text("".join(root.itertext())))]

    pieces: List[str] = []
    sections_meta: List[SectionMeta] = []
    cursor = 0

    def add_piece(text: str):
        nonlocal cursor
        pieces.append(text)
        cursor += len(text)

    add_piece(f"# {title}\n\n")
    if abstract:
        add_piece("## Abstract\n\n")
        add_piece(f"{abstract}\n\n")

    for idx, (heading, body_text) in enumerate(sec_pairs, start=1):
        heading_text = heading or f"Section {idx}"
        section_start = cursor
        add_piece(f"## {heading_text}\n\n")
        add_piece(f"{body_text}\n\n")
        section_end = cursor
        sections_meta.append(
            SectionMeta(
                section_id=f"s{idx}",
                level=2,
                title=heading_text,
                order=idx,
                page_start=None,
                page_end=None,
                char_start=section_start,
                char_end=section_end,
            )
        )

    markdown = "".join(pieces).strip() + "\n"
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(markdown, encoding="utf-8")

    return MarkdownParseResult(
        title=title,
        abstract=abstract,
        markdown=markdown,
        sections=sections_meta,
    )

