"""自定义工具示例API"""
from fastapi import APIRouter

from app.schemas.custom_tool import (
    DemoCustomToolRequest,
    DemoCustomToolResponse,
    BibLookupRequest,
    BibLookupResponse,
    BibLookupCandidate,
)
from app.custom_tools.bib_store import bib_store

router = APIRouter()


@router.post("/demo", response_model=DemoCustomToolResponse)
async def run_demo_custom_tool(request: DemoCustomToolRequest):
    """演示一个简单的自定义工具（后端处理：值 + 1）"""
    return DemoCustomToolResponse(result=request.value + 1)


@router.post("/bib-lookup", response_model=BibLookupResponse)
async def bib_lookup(request: BibLookupRequest):
    """根据论文标题查询标准 BibTeX 引用"""
    entry_lines = bib_store.lookup(request.title)
    if entry_lines:
        bibtex = bib_store.post_process(
            entry_lines,
            shorten=request.shorten,
            remove_fields=[f.strip() for f in request.remove_fields if f.strip()],
        )
        return BibLookupResponse(found=True, bibtex=bibtex, candidates=[])

    candidates = []
    for cand_lines in bib_store.search_candidates(request.title, request.max_candidates):
        cand_bibtex = bib_store.post_process(
            cand_lines,
            shorten=request.shorten,
            remove_fields=[f.strip() for f in request.remove_fields if f.strip()],
        )
        cand_title = bib_store.extract_title(cand_lines) or "Unknown Title"
        candidates.append(BibLookupCandidate(title=cand_title, bibtex=cand_bibtex))

    return BibLookupResponse(found=False, bibtex=None, candidates=candidates)
