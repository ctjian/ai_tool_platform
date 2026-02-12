"""自定义工具相关 Schema.

Review note:
- 扩展 arxiv-translate 的任务模型（请求、步骤、产物、任务状态）。
"""
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


class ArxivTranslateCreateRequest(BaseModel):
    """创建 arXiv 精细翻译任务"""
    input_text: str = Field(..., min_length=1, max_length=1000, description="arXiv ID 或链接")
    api_key: Optional[str] = Field(None, description="可选，覆盖后端默认 API Key")
    base_url: Optional[str] = Field(None, description="可选，覆盖后端默认 base_url")
    model: Optional[str] = Field(None, description="可选，翻译模型")
    target_language: str = Field("中文", max_length=50, description="目标翻译语言")
    extra_prompt: str = Field("", max_length=2000, description="额外翻译要求")
    allow_cache: bool = Field(True, description="是否允许复用历史缓存")
    concurrency: int = Field(16, ge=1, le=16, description="分片并发数")
    chunk_max_tokens: int = Field(1024, ge=256, le=4096, description="分片最大 token（近似）")
    max_compile_tries: int = Field(32, ge=1, le=32, description="最大编译重试次数")


class ArxivTranslateStep(BaseModel):
    step_id: str
    key: str
    status: str
    message: str
    at: str
    elapsed_ms: Optional[int] = None


class ArxivTranslateArtifact(BaseModel):
    name: str
    path: str
    url: str
    size_bytes: int


class ArxivTranslateJobResponse(BaseModel):
    job_id: str
    status: str
    input_text: str
    paper_id: Optional[str] = None
    canonical_id: Optional[str] = None
    created_at: str
    updated_at: str
    error: Optional[str] = None
    steps: List[ArxivTranslateStep] = []
    artifacts: List[ArxivTranslateArtifact] = []
    meta: dict = {}


class ArxivTranslateHistoryItem(BaseModel):
    job_id: str
    status: str
    input_text: Optional[str] = None
    paper_id: Optional[str] = None
    canonical_id: Optional[str] = None
    created_at: str
    updated_at: str
    task_name: str
    paper_title: Optional[str] = None
    original_pdf_url: Optional[str] = None
    translated_pdf_url: Optional[str] = None
    artifacts: List[ArxivTranslateArtifact] = []


class ArxivTranslateHistoryResponse(BaseModel):
    items: List[ArxivTranslateHistoryItem] = []
