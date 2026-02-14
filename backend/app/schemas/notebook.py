"""Notebook API schemas."""

from pydantic import BaseModel, Field
from typing import List, Optional


class NotebookNote(BaseModel):
    id: str
    title: str
    path: str
    tags: List[str]
    updated_at: Optional[str] = None
    summary: Optional[str] = None


class NotebookNoteListResponse(BaseModel):
    notes: List[NotebookNote]


class NotebookCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    summary: Optional[str] = Field(default="", max_length=500)
    tags: List[str] = Field(default_factory=list)
    content: str = Field(..., min_length=1)


class NotebookQaRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4000)
    model: Optional[str] = Field(default="gpt-4o-mini")
    api_key: Optional[str] = Field(default="")
    base_url: Optional[str] = Field(default="")
