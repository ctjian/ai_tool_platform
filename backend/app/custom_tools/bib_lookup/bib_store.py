"""Bib 数据加载与查询"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import re
from typing import Dict, List

import bibtexparser
from bibtexparser.bwriter import BibTexWriter


BACKEND_DIR = Path(__file__).resolve().parents[3]
BIB_DATA_DIR = BACKEND_DIR / "data" / "custom_tools" / "bib_lookup"
VENUE_RULES_PATH = BIB_DATA_DIR / "venues.json"


@dataclass
class VenueRule:
    id: str
    abbr: str
    full_name: str
    type: str
    regex: List[str]


def normalize_title(title_str: str) -> str:
    """与 rebiber 一致的标题归一化逻辑"""
    title_str = re.sub(r"[^a-zA-Z]", r"", title_str)
    return title_str.lower().replace(" ", "").strip()


def _load_bib_list() -> List[Path]:
    """加载 backend/data/custom_tools/bib_lookup/data 目录下全部 .json。"""
    return sorted((BIB_DATA_DIR / "data").glob("*.json"))


def _load_venue_rules() -> List[VenueRule]:
    if not VENUE_RULES_PATH.exists():
        return []
    try:
        with VENUE_RULES_PATH.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return []
    raw_venues = payload.get("venues", [])
    if not isinstance(raw_venues, list):
        return []
    rules: List[VenueRule] = []
    for item in raw_venues:
        if not isinstance(item, dict):
            continue
        abbr = str(item.get("abbr", "")).strip()
        raw_regex = item.get("regex", [])
        if not abbr or not isinstance(raw_regex, list):
            continue
        regexes = [str(pattern).strip() for pattern in raw_regex if str(pattern).strip()]
        if not regexes:
            continue
        rules.append(
            VenueRule(
                id=str(item.get("id", "")).strip(),
                abbr=abbr,
                full_name=str(item.get("full_name", "")).strip(),
                type=str(item.get("type", "")).strip().lower(),
                regex=regexes,
            )
        )
    return rules


def _rule_applies_to_place(rule: VenueRule, place: str) -> bool:
    if rule.type == "conference":
        return place == "booktitle"
    if rule.type == "journal":
        return place == "journal"
    return place in {"booktitle", "journal"}


def _rule_matches_text(rule: VenueRule, text: str) -> bool:
    for pattern in rule.regex:
        try:
            if re.search(pattern, text, flags=re.DOTALL):
                return True
        except re.error:
            continue
    return False


def _normalize_venue_by_rules(value: str, place: str, rules: List[VenueRule], shorten: bool) -> str:
    for rule in rules:
        if not _rule_applies_to_place(rule, place):
            continue
        if not _rule_matches_text(rule, value):
            continue
        if shorten:
            return rule.abbr
        return rule.full_name or rule.abbr
    return value


class BibStore:
    def __init__(self) -> None:
        self._bib_db: Dict[str, List[str]] = {}
        self._venue_rules: List[VenueRule] = []
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
        self._venue_rules = _load_venue_rules()
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

        if self._venue_rules:
            for place in ["booktitle", "journal"]:
                if place not in entry:
                    continue
                entry[place] = _normalize_venue_by_rules(
                    value=entry[place],
                    place=place,
                    rules=self._venue_rules,
                    shorten=shorten,
                )

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
