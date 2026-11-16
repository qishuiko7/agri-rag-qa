"""对话接口：单轮 / 流式 / 会话管理。"""
from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.api.schemas import AskRequest, AskResponse, SourceItem
from app.config import settings
from app.core import guard, llm, rag, vectorstore
from app.core.memory import memory

router = APIRouter(prefix="/api/chat", tags=["chat"])
logger = logging.getLogger(__name__)


@router.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    """非流式问答。"""
    session_id = req.session_id or uuid.uuid4().hex[:12]

    if req.mode == "agent":
        # 延迟导入，避免 Agent 模块未就绪时影响 RAG 主链路
        from app.agent.executor import run_agent

        result = run_agent(req.question, session_id=session_id)
        return AskResponse(
            answer=result["answer"],
            sources=[SourceItem(**s) for s in result.get("sources", [])],
            blocked=result.get("blocked", False),
            latency_ms=result.get("latency_ms", 0),
            session_id=session_id,
            mode="agent",
            tool_calls=result.get("tool_calls", []),
        )

    result = rag.answer(req.question, session_id=session_id, top_k=req.top_k)
    return AskResponse(
        answer=result.answer,
        sources=[SourceItem(**s) for s in result.sources],
        blocked=result.blocked,
        latency_ms=result.latency_ms,
        session_id=session_id,
        mode="rag",
    )


@router.get("/stream")
def stream(
    question: str = Query(..., description="用户问题"),
    session_id: str = Query("", description="会话 ID"),
    top_k: int | None = Query(None, ge=1, le=20),
    mode: str = Query("rag"),
):
    """SSE 流式问答。事件类型：sources / delta / done / error / tool。"""

    def event_stream():
        sid = session_id or uuid.uuid4().hex[:12]
        try:
            if mode == "agent":
                from app.agent.executor import run_agent_stream

                for evt in run_agent_stream(question, session_id=sid):
                    yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
            else:
                for evt in rag.answer_stream(question, session_id=sid, top_k=top_k):
                    yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001
            logger.exception("流式接口异常")
            payload = {"type": "error", "data": str(exc)}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        # 结束标记，前端据此关闭连接
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/clear")
def clear(session_id: str = Query(...)) -> dict:
    """清空指定会话的上下文记忆。"""
    ok = memory.clear(session_id)
    return {"ok": True, "cleared": ok, "message": "会话已清空" if ok else "会话不存在或已过期"}


@router.get("/sessions")
def sessions() -> dict:
    return {"items": memory.list_sessions()}


@router.get("/guard")
def guard_check(q: str = Query(...)) -> dict:
    """调试用：查看领域拦截判定依据。"""
    v = guard.check_question(q)
    return {"allowed": v.allowed, "reason": v.reason, "hit_words": list(v.hit_words)}


@router.get("/status")
def status() -> dict:
    """系统运行状态，供前端顶部状态条展示。"""
    st = vectorstore.stats()
    llm_ready = settings.llm_provider != "mock" and bool(
        settings.dashscope_api_key if settings.llm_provider == "dashscope" else settings.zhipu_api_key
    )
    return {
        "vector_ready": st.ready,
        "vector_chunks": st.chunks,
        "vector_size_mb": st.size_mb,
        "embedding_provider": st.embedding_provider,
        "embedding_model": st.embedding_model,
        "embedding_dim": st.dim,
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,
        "llm_ready": llm_ready,
        "mode": "真实模型" if llm_ready else "Mock 演示",
        "top_k": settings.top_k,
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
        "memory_rounds": settings.memory_rounds,
    }


@router.get("/ping-model")
def ping_model() -> dict:
    """连通性自检：发一条极短请求验证密钥与网络。"""
    try:
        text = llm.chat([{"role": "user", "content": "回复两个字：正常"}], max_tokens=16)
        return {"ok": True, "reply": text}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
