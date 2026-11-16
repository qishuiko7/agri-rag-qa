"""Agent 接口：工具清单与 Agent 问答。"""
from __future__ import annotations

import logging

from fastapi import APIRouter

from app.agent.tools import registry
from app.api.schemas import AskRequest, AskResponse, SourceItem

router = APIRouter(prefix="/api/agent", tags=["agent"])
logger = logging.getLogger(__name__)


@router.get("/tools")
def list_tools() -> dict:
    """返回 Agent 可用工具清单。"""
    return {"total": len(registry.all()), "items": registry.describe()}


@router.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    """Agent 模式问答（非流式，含工具调用轨迹）。"""
    from app.agent.executor import run_agent

    session_id = req.session_id or "anonymous"
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
