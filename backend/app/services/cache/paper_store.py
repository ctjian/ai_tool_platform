"""File storage utilities for parsed papers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
import json


@dataclass(frozen=True)
class PaperPaths:
    root_dir: Path
    paper_dir: Path
    pdf_path: Path
    tei_path: Path
    markdown_path: Path
    meta_path: Path
    chunks_path: Path
    chunk_embeddings_path: Path


def build_paper_paths(base_dir: str, safe_id: str) -> PaperPaths:
    root = Path(base_dir)
    paper_dir = root / safe_id
    return PaperPaths(
        root_dir=root,
        paper_dir=paper_dir,
        pdf_path=paper_dir / f"{safe_id}.pdf",
        tei_path=paper_dir / "tei.xml",
        markdown_path=paper_dir / "paper.md",
        meta_path=paper_dir / "paper.json",
        chunks_path=paper_dir / "chunks.jsonl",
        chunk_embeddings_path=paper_dir / "chunk_embeddings.json",
    )


def ensure_paper_dir(paths: PaperPaths) -> None:
    paths.paper_dir.mkdir(parents=True, exist_ok=True)


def has_ready_parsed_artifacts(paths: PaperPaths) -> bool:
    return (
        paths.meta_path.exists()
        and paths.markdown_path.exists()
        and paths.chunks_path.exists()
    )


def load_meta(paths: PaperPaths) -> Optional[Dict]:
    if not paths.meta_path.exists():
        return None
    return json.loads(paths.meta_path.read_text(encoding="utf-8"))


def save_meta(paths: PaperPaths, meta: Dict) -> None:
    ensure_paper_dir(paths)
    paths.meta_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def save_chunks_jsonl(paths: PaperPaths, chunks: List[Dict]) -> None:
    ensure_paper_dir(paths)
    with paths.chunks_path.open("w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")


def load_chunks_jsonl(paths: PaperPaths) -> List[Dict]:
    if not paths.chunks_path.exists():
        return []
    items: List[Dict] = []
    with paths.chunks_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            items.append(json.loads(line))
    return items


def save_chunk_embeddings(paths: PaperPaths, payload: Dict) -> None:
    ensure_paper_dir(paths)
    paths.chunk_embeddings_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_chunk_embeddings(paths: PaperPaths) -> Optional[Dict]:
    if not paths.chunk_embeddings_path.exists():
        return None
    return json.loads(paths.chunk_embeddings_path.read_text(encoding="utf-8"))
