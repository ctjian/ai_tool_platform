"""Notebook APIs."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse, StreamingResponse
from typing import Any, AsyncGenerator, Dict, List
import asyncio
import json
import re
import time
from datetime import datetime, timezone

from app.config import settings
from app.schemas.chat import APIConfig
from app.schemas.notebook import (
    NotebookCreateRequest,
    NotebookDeleteResponse,
    NotebookGenerateRequest,
    NotebookGenerateResponse,
    NotebookNote,
    NotebookNoteListResponse,
    NotebookQaRequest,
)
from app.services.notebook.notebook_service import (
    NotebookNotFoundError,
    NotebookServiceError,
    build_notebook_retrieval_payload,
    create_notebook_note,
    delete_notebook_note,
    list_notebook_notes,
    load_notebook_note_content,
)
from app.utils.openai_helper import stream_chat_completion

router = APIRouter()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _strip_markdown_text(text: str) -> str:
    cleaned = re.sub(r"[#>*`~\[\]\(\)\-]", " ", str(text or ""))
    return " ".join(cleaned.replace("\r", "\n").split())


def _normalize_tags(tags: Any) -> List[str]:
    if not isinstance(tags, list):
        return []
    output: List[str] = []
    seen: set[str] = set()
    for raw in tags:
        tag = str(raw or "").strip()[:30]
        if not tag or tag in seen:
            continue
        seen.add(tag)
        output.append(tag)
        if len(output) >= 5:
            break
    return output


def _extract_json_payload(text: str) -> Dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        raise NotebookServiceError("模型未返回有效内容")

    fenced_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, flags=re.IGNORECASE)
    if fenced_match:
        raw = fenced_match.group(1).strip()

    try:
        payload = json.loads(raw)
    except Exception:
        first = raw.find("{")
        last = raw.rfind("}")
        if first < 0 or last <= first:
            raise NotebookServiceError("模型返回格式不是有效 JSON")
        try:
            payload = json.loads(raw[first : last + 1])
        except Exception as exc:
            raise NotebookServiceError("模型返回 JSON 解析失败") from exc

    if not isinstance(payload, dict):
        raise NotebookServiceError("模型返回 JSON 结构错误")
    return payload


@router.get("/notebook/notes", response_model=NotebookNoteListResponse)
async def get_notebook_notes():
    try:
        notes = list_notebook_notes(settings)
        return {"notes": notes}
    except NotebookServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/notebook/notes/{note_id}/content", response_class=PlainTextResponse)
async def get_notebook_note_content(note_id: str):
    try:
        content = load_notebook_note_content(settings, note_id)
        return PlainTextResponse(content=content)
    except NotebookNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except NotebookServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/notebook/notes", response_model=NotebookNote, status_code=201)
async def create_note(payload: NotebookCreateRequest):
    try:
        return create_notebook_note(
            settings=settings,
            title=payload.title,
            summary=payload.summary or "",
            tags=payload.tags,
            content=payload.content,
        )
    except NotebookServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/notebook/notes/{note_id}", response_model=NotebookDeleteResponse)
async def delete_note(note_id: str):
    try:
        deleted_id = delete_notebook_note(settings, note_id)
        return {"success": True, "note_id": deleted_id}
    except NotebookNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except NotebookServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/notebook/notes/generate", response_model=NotebookGenerateResponse)
async def generate_note(payload: NotebookGenerateRequest):
    draft = str(payload.draft or "").strip()
    model = str(payload.model or "gpt-4o-mini").strip() or "gpt-4o-mini"
    if not draft:
        raise HTTPException(status_code=400, detail="草稿不能为空")

    available_tags = _normalize_tags(list(payload.available_tags or []))
    available_tag_text = "、".join(available_tags) if available_tags else "无"
    json_example = {
        "title": "Ubuntu 日志暴涨排查：journalctl 占满磁盘",
        "summary": "定位 /var/log/journal 占用异常，通过清理历史日志并配置 journald 配额解决问题，附带验证与回滚步骤。",
        "tags": ["系统运维", "开发排错"],
        "markdown": "# Ubuntu 日志暴涨排查：journalctl 占满磁盘\n\n## 一、问题背景\n...\n",
    }
    system_prompt = (
        "你是技术笔记整理助手。"
        "你只可以基于用户提供的草稿整理内容，不允许编造未出现的事实、命令、版本号或路径。"
        "请将结果整理成可检索、可执行的 Markdown 笔记。"
        "命令/配置必须使用 fenced code block（尽量标注语言，如 bash/yaml/python）。"
        "如果信息不足，明确写“待补充”，不要臆测。"
        "你必须只输出 JSON，且字段必须为 title、summary、tags、markdown。"
        "不要输出 JSON 以外的任何解释。"
    )
    user_prompt = (
        "请把下面草稿整理为结构化笔记。\n\n"
        f"【可用标签池】\n{available_tag_text}\n\n"
        f"【草稿内容】\n{draft}\n\n"
        "【Markdown模板】\n"
        "# {标题}\n\n"
        "## 一、问题背景\n"
        "## 二、现象与关键信息\n"
        "## 三、分析与定位\n"
        "## 四、解决步骤\n"
        "## 五、验证结果\n"
        "## 六、风险与回滚\n"
        "## 七、附录（命令/配置/日志片段）\n\n"
        "约束：\n"
        "1) title 8-40 字；summary 40-140 字；tags 2-5 个并去重。\n"
        "2) tags 优先从可用标签池选择，不足时可补充少量新标签。\n"
        "3) markdown 必须完整并符合模板，不适用项写“待补充”。\n"
        "4) 只返回 JSON。\n\n"
        f"【JSON返回示例】\n{json.dumps(json_example, ensure_ascii=False, indent=2)}"
    )

    try:
        api_cfg = APIConfig(
            api_key=str(payload.api_key or ""),
            base_url=str(payload.base_url or settings.OPENAI_BASE_URL or ""),
            model=model,
            temperature=0.2,
            max_tokens=1800,
            top_p=1.0,
            frequency_penalty=0.0,
            presence_penalty=0.0,
        )

        full_text = ""
        async for chunk in stream_chat_completion(
            api_config=api_cfg,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        ):
            if not isinstance(chunk, dict):
                continue
            ctype = str(chunk.get("type") or "")
            if ctype == "token":
                token = str(chunk.get("content") or "")
                if token:
                    full_text += token
            elif ctype == "error":
                err = str(chunk.get("error") or "生成笔记失败")
                raise NotebookServiceError(err)

        parsed = _extract_json_payload(full_text)
        title = str(parsed.get("title") or "").strip()[:200]
        summary = str(parsed.get("summary") or "").strip()[:500]
        markdown = str(parsed.get("markdown") or "").strip()
        tags = _normalize_tags(parsed.get("tags") or [])

        if not markdown:
            raise NotebookServiceError("模型未返回有效 markdown")
        if not title:
            title = (_strip_markdown_text(markdown)[:40] or "未命名笔记").strip()
        if not summary:
            summary = _strip_markdown_text(markdown)[:140]
        if not tags:
            tags = available_tags[:2] if available_tags else ["未分类"]

        return {
            "title": title,
            "summary": summary,
            "tags": tags,
            "markdown": markdown,
        }
    except NotebookServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/notebook/qa/stream")
async def notebook_qa_stream(payload: NotebookQaRequest):
    async def event_generator() -> AsyncGenerator[str, None]:
        query = str(payload.query or "").strip()
        model = str(payload.model or "gpt-4o-mini").strip() or "gpt-4o-mini"
        if not query:
            yield _sse("error", {"error": "问题不能为空"})
            return

        # step: created
        yield _sse(
            "status",
            {
                "step_id": "s1",
                "key": "queued",
                "status": "done",
                "message": "任务已创建，等待执行",
                "at": _now_iso(),
            },
        )

        # step: retrieval
        retrieval_started = time.perf_counter()
        yield _sse(
            "status",
            {
                "step_id": "s2",
                "key": "retrieve",
                "status": "running",
                "message": "正在检索笔记库",
                "at": _now_iso(),
            },
        )
        try:
            retrieval = await asyncio.to_thread(
                build_notebook_retrieval_payload,
                settings=settings,
                query=query,
            )
        except NotebookServiceError as exc:
            yield _sse(
                "status",
                {
                    "step_id": "s2",
                    "key": "retrieve",
                    "status": "error",
                    "message": "检索失败",
                    "at": _now_iso(),
                    "elapsed_ms": int((time.perf_counter() - retrieval_started) * 1000),
                },
            )
            yield _sse("error", {"error": str(exc)})
            return

        sources = retrieval.get("sources") or []
        yield _sse(
            "status",
            {
                "step_id": "s2",
                "key": "retrieve",
                "status": "done",
                "message": "检索完成",
                "at": _now_iso(),
                "elapsed_ms": int((time.perf_counter() - retrieval_started) * 1000),
            },
        )

        if not sources:
            answer = "没有检索到明确相关的笔记内容。建议更换关键词后再试。"
            yield _sse(
                "done",
                {
                    "answer_markdown": answer,
                    "model": model,
                    "query": query,
                    "sources": [],
                },
            )
            return

        # step: answer generation stream
        answer_started = time.perf_counter()
        yield _sse(
            "status",
            {
                "step_id": "s3",
                "key": "answer",
                "status": "running",
                "message": "正在生成回答",
                "at": _now_iso(),
            },
        )

        system_prompt = (
            "你是一个笔记库问答助手。"
            "你将收到检索到的笔记片段，请仅基于这些片段回答。"
            "如果片段不足以支持结论，请明确说明不确定。"
            "回答用简体中文，结构清晰，优先给出可执行建议。"
        )
        user_prompt = (
            f"用户问题：\n{query}\n\n"
            f"检索片段（来源标记为 S1/S2...）：\n{str(retrieval.get('context_text') or '')}\n\n"
            "请输出 Markdown 答案，必要时引用来源标记（如 [S1]）。"
        )
        api_cfg = APIConfig(
            api_key=str(payload.api_key or ""),
            base_url=str(payload.base_url or settings.OPENAI_BASE_URL or ""),
            model=model,
            temperature=0.2,
            max_tokens=1200,
            top_p=1.0,
            frequency_penalty=0.0,
            presence_penalty=0.0,
        )

        full_text = ""
        async for chunk in stream_chat_completion(
            api_config=api_cfg,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        ):
            if not isinstance(chunk, dict):
                continue
            ctype = str(chunk.get("type") or "")
            if ctype == "token":
                token = str(chunk.get("content") or "")
                if token:
                    full_text += token
                    yield _sse("token", {"content": token})
            elif ctype == "error":
                err = str(chunk.get("error") or "问答模型调用失败")
                yield _sse(
                    "status",
                    {
                        "step_id": "s3",
                        "key": "answer",
                        "status": "error",
                        "message": "回答生成失败",
                        "at": _now_iso(),
                        "elapsed_ms": int((time.perf_counter() - answer_started) * 1000),
                    },
                )
                yield _sse("error", {"error": err})
                return

        if not full_text.strip():
            full_text = "未生成有效回答，请稍后重试。"

        yield _sse(
            "status",
            {
                "step_id": "s3",
                "key": "answer",
                "status": "done",
                "message": "回答生成完成",
                "at": _now_iso(),
                "elapsed_ms": int((time.perf_counter() - answer_started) * 1000),
            },
        )
        yield _sse(
            "done",
            {
                "answer_markdown": full_text,
                "model": model,
                "query": query,
                "sources": sources,
            },
        )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
