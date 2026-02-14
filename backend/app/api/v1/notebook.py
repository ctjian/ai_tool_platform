"""Notebook APIs."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse, StreamingResponse
from typing import AsyncGenerator
import asyncio
import json
import time
from datetime import datetime, timezone

from app.config import settings
from app.schemas.chat import APIConfig
from app.schemas.notebook import (
    NotebookCreateRequest,
    NotebookNote,
    NotebookNoteListResponse,
    NotebookQaRequest,
)
from app.services.notebook.notebook_service import (
    NotebookNotFoundError,
    NotebookServiceError,
    build_notebook_retrieval_payload,
    create_notebook_note,
    list_notebook_notes,
    load_notebook_note_content,
)
from app.utils.openai_helper import stream_chat_completion

router = APIRouter()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


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
