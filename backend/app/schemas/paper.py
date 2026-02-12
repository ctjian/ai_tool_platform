"""Schemas for parsed paper artifacts (schema v1)."""

from __future__ import annotations

from pydantic import BaseModel
from typing import List, Optional


class PaperSection(BaseModel):
    section_id: str
    level: int
    title: str
    order: int
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    char_start: int
    char_end: int


class PaperChunk(BaseModel):
    chunk_id: str
    section_id: str
    order: int
    heading_path: List[str]
    text: str
    token_count: int
    char_count: int
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    char_start: Optional[int] = None
    char_end: Optional[int] = None
    text_sha1: str

