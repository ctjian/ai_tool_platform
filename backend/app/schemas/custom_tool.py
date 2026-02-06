"""自定义工具相关Schema"""
from pydantic import BaseModel, Field
from typing import List, Optional


class DemoCustomToolRequest(BaseModel):
    """测试自定义工具请求"""
    value: int = Field(..., ge=-10**9, le=10**9)


class DemoCustomToolResponse(BaseModel):
    """测试自定义工具响应"""
    result: int


class BibLookupRequest(BaseModel):
    """Bib 引用查询请求"""
    title: str = Field(..., min_length=1, max_length=500)
    shorten: bool = False
    remove_fields: List[str] = []
    max_candidates: int = Field(5, ge=0, le=20)


class BibLookupCandidate(BaseModel):
    """Bib 候选结果"""
    title: str
    bibtex: str


class BibLookupResponse(BaseModel):
    """Bib 引用查询响应"""
    found: bool
    bibtex: Optional[str] = None
    candidates: List[BibLookupCandidate] = []
