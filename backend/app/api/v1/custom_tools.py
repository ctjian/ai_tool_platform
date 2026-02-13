"""自定义工具API.

Review note:
- 保留 demo/bib 示例接口。
- 新增 arxiv-translate 任务接口（创建/查询/取消）。
"""
from fastapi import APIRouter, HTTPException

from app.schemas.custom_tool import (
    DemoCustomToolRequest,
    DemoCustomToolResponse,
    BibLookupRequest,
    BibLookupResponse,
    BibLookupCandidate,
    ArxivTranslateCreateRequest,
    ArxivTranslateJobResponse,
    ArxivTranslateHistoryResponse,
)
from app.custom_tools.bib_lookup.bib_store import bib_store
from app.custom_tools.arxiv_translate.service import (
    create_job as create_arxiv_translate_job,
    get_job as get_arxiv_translate_job,
    cancel_job as cancel_arxiv_translate_job,
    list_jobs as list_arxiv_translate_jobs,
)

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


@router.post("/arxiv-translate/jobs", response_model=ArxivTranslateJobResponse)
async def create_arxiv_translate(request: ArxivTranslateCreateRequest):
    """创建 arXiv 精细翻译任务。"""
    try:
        return await create_arxiv_translate_job(request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"创建任务失败: {exc}")


@router.get("/arxiv-translate/jobs/{job_id}", response_model=ArxivTranslateJobResponse)
async def get_arxiv_translate(job_id: str):
    """查询翻译任务状态。"""
    try:
        return await get_arxiv_translate_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"查询任务失败: {exc}")


@router.get("/arxiv-translate/jobs", response_model=ArxivTranslateHistoryResponse)
async def get_arxiv_translate_jobs(limit: int = 30, statuses: str | None = None):
    """查询翻译任务列表（按更新时间倒序，可按状态过滤）。"""
    try:
        status_filters = None
        if statuses:
            status_filters = [s.strip() for s in statuses.split(",") if s.strip()]
        return await list_arxiv_translate_jobs(limit=limit, statuses=status_filters)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"查询历史任务失败: {exc}")


@router.post("/arxiv-translate/jobs/{job_id}/cancel", response_model=ArxivTranslateJobResponse)
async def cancel_arxiv_translate(job_id: str):
    """取消翻译任务。"""
    try:
        return await cancel_arxiv_translate_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"取消任务失败: {exc}")
