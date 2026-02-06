"""Bib 数据加载与查询"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import re
from typing import Dict, List, Tuple

import bibtexparser
from bibtexparser.bwriter import BibTexWriter


BASE_DIR = Path(__file__).resolve().parent
BIB_DATA_DIR = BASE_DIR / "bib_data"


def normalize_title(title_str: str) -> str:
    """与 rebiber 一致的标题归一化逻辑"""
    title_str = re.sub(r"[^a-zA-Z]", r"", title_str)
    return title_str.lower().replace(" ", "").strip()


def _load_bib_list() -> List[Path]:
    """默认加载 data 目录下全部 .json（不使用 bib_list.txt）"""
    data_dir = BIB_DATA_DIR / "data"
    return sorted(data_dir.glob("*.json"))


def _load_abbr_dict() -> List[Tuple[str, str]]:
    abbr_path = BIB_DATA_DIR / "abbr.tsv"
    if not abbr_path.exists():
        return []
    abbr_dict = []
    with abbr_path.open("r", encoding="utf-8") as f:
        for line in f.read().splitlines():
            ls = line.split("|")
            if len(ls) == 2:
                abbr_dict.append((ls[0].strip(), ls[1].strip()))
    return abbr_dict


@dataclass
class BibEntry:
    title: str
    bibtex: str


class BibStore:
    def __init__(self) -> None:
        self._bib_db: Dict[str, List[str]] = {}
        self._abbr_dict: List[Tuple[str, str]] = []
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return

        bib_files = _load_bib_list()
        bib_db: Dict[str, List[str]] = {}
        for file_path in bib_files:
            if not file_path.exists():
                continue
            with file_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            # data: {normalized_title: [bib lines...]}
            bib_db.update(data)
        self._bib_db = bib_db
        self._abbr_dict = _load_abbr_dict()
        self._loaded = True

    def lookup(self, title: str) -> List[str] | None:
        self.load()
        key = normalize_title(title)
        return self._bib_db.get(key)

    def search_candidates(self, title: str, limit: int = 5) -> List[List[str]]:
        self.load()
        key = normalize_title(title)
        if not key:
            return []
        candidates: List[List[str]] = []
        for k, v in self._bib_db.items():
            if key in k or k in key:
                candidates.append(v)
                if len(candidates) >= limit:
                    break
        return candidates

    def post_process(
        self,
        entry_lines: List[str],
        shorten: bool,
        remove_fields: List[str],
    ) -> str:
        bib_entry_str = "".join(entry_lines)
        bibparser = bibtexparser.bparser.BibTexParser(ignore_nonstandard_types=False)
        parsed = bibtexparser.loads(bib_entry_str, bibparser)
        if not parsed.entries:
            return bib_entry_str

        entry = parsed.entries[0]
        for field in remove_fields:
            if field in entry:
                del entry[field]

        if shorten and self._abbr_dict:
            for short, pattern in self._abbr_dict:
                for place in ["booktitle", "journal"]:
                    if place in entry and re.match(pattern, entry[place], flags=re.DOTALL):
                        entry[place] = short

        writer = BibTexWriter()
        writer.order_entries_by = None
        return bibtexparser.dumps(parsed, writer=writer)

    def extract_title(self, entry_lines: List[str]) -> str:
        for line in entry_lines:
            if line.lower().strip().startswith("title"):
                # title = {xxx}
                m = re.search(r"title\\s*=\\s*[\\{\\\"](.+)[\\}\\\"]", line, flags=re.IGNORECASE)
                if m:
                    return m.group(1).strip()
        return ""


bib_store = BibStore()
