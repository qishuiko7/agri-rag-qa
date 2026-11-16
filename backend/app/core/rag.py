"""RAG 问答编排。

把「校验 -> 领域拦截 -> 检索 -> 提示词组装 -> 生成 -> 记录」串成一条链路，
供 API 层直接调用。流式与非流式共用同一套前置逻辑。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Iterable

from app.config import settings
from app.core import guard, history, llm, prompts, vectorstore
from app.core.memory import history_for, memory

logger = logging.getLogger(__name__)


@dataclass
class RagResult:
    """一次问答的完整结果。"""

    answer: str
    sources: list[dict] = field(default_factory=list)
    blocked: bool = False
    latency_ms: int = 0
    mode: str = "rag"


def _to_sources(hits: list) -> list[dict]:
    """把检索结果转成前端可直接渲染的来源结构。"""
    out = []
    for doc, score in hits:
        meta = doc.metadata or {}
        out.append(
            {
                "title": meta.get("title") or meta.get("source", "未知来源"),
                "category": settings.categories.get(meta.get("category", ""), "通用农技"),
                "category_key": meta.get("category", "general"),
                "source": meta.get("source", ""),
                "content": doc.page_content[:300],
                "score": round(float(score), 4),
            }
        )
    return out


def retrieve(question: str, top_k: int | None = None, category: str | None = None) -> list[dict]:
    """纯检索（Agent 工具复用）。

    category 下推到向量库层面过滤，而不是召回后再筛——
    否则筛掉后可能不足 k 条，等于浪费了召回名额。
    """
    try:
        hits = vectorstore.search(
            question, k=top_k or settings.top_k, category=category
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("检索异常：%s", exc)
        return []
    return _to_sources(hits)


def answer(
    question: str,
    session_id: str = "",
    top_k: int | None = None,
    save_record: bool = True,
) -> RagResult:
    """非流式问答。"""
    t0 = time.perf_counter()
    q = (question or "").strip()

    # 1. 空问题
    if not q:
        return RagResult(answer="请输入你的问题后再提交。", blocked=True, mode="rag")

    # 2. 领域拦截
    verdict = guard.check_question(q)
    if not verdict.allowed:
        latency = int((time.perf_counter() - t0) * 1000)
        if save_record:
            history.add(
                session_id=session_id or "anonymous",
                question=q,
                answer=prompts.REJECT_MESSAGE,
                latency_ms=latency,
                mode="rag",
                blocked=True,
            )
        return RagResult(answer=prompts.REJECT_MESSAGE, blocked=True, latency_ms=latency)

    # 3. 检索（寒暄类问题跳过，避免白调一次嵌入接口）
    hits = []
    if verdict.reason != "寒暄":
        try:
            hits = vectorstore.search(q, k=top_k or settings.top_k)
        except Exception as exc:  # noqa: BLE001
            logger.warning("向量库检索失败：%s", exc)
            msg = "知识库尚未初始化或暂时不可用，请先到「向量库构建」页面完成入库后再提问。"
            latency = int((time.perf_counter() - t0) * 1000)
            if save_record:
                history.add(
                    session_id=session_id or "anonymous",
                    question=q,
                    answer=msg,
                    latency_ms=latency,
                    mode="rag",
                )
            return RagResult(answer=msg, blocked=False, latency_ms=latency)

    sources = _to_sources(hits)

    # 4. 组装消息并生成
    msgs = prompts.build_messages(q, sources, history_for(session_id))
    try:
        text = llm.chat(msgs)
    except Exception as exc:  # noqa: BLE001
        logger.error("大模型调用失败：%s", exc)
        text = f"大模型接口调用失败：{exc}。请检查网络、密钥额度或稍后重试。"
        latency = int((time.perf_counter() - t0) * 1000)
        if save_record:
            history.add(
                session_id=session_id or "anonymous",
                question=q,
                answer=text,
                latency_ms=latency,
                mode="rag",
                sources=sources,
            )
        return RagResult(answer=text, sources=sources, latency_ms=latency)

    latency = int((time.perf_counter() - t0) * 1000)

    # 5. 记忆 + 记录
    if session_id:
        memory.append(session_id, q, text)
    if save_record:
        history.add(
            session_id=session_id or "anonymous",
            question=q,
            answer=text,
            latency_ms=latency,
            mode="rag",
            sources=sources,
        )

    return RagResult(answer=text, sources=sources, latency_ms=latency)


def answer_stream(question: str, session_id: str = "", top_k: int | None = None) -> Iterable[dict]:
    """流式问答。

    产出事件序列：
        {"type": "sources", "data": [...]}   # 先给来源
        {"type": "delta", "data": "..."}     # 增量文本
        {"type": "done", "data": {...}}      # 收尾信息
        {"type": "error", "data": "..."}     # 异常
    """
    t0 = time.perf_counter()
    q = (question or "").strip()

    if not q:
        yield {"type": "error", "data": "请输入你的问题后再提交。"}
        return

    verdict = guard.check_question(q)
    if not verdict.allowed:
        yield {"type": "sources", "data": []}
        yield {"type": "delta", "data": prompts.REJECT_MESSAGE}
        latency = int((time.perf_counter() - t0) * 1000)
        history.add(
            session_id=session_id or "anonymous",
            question=q,
            answer=prompts.REJECT_MESSAGE,
            latency_ms=latency,
            mode="rag",
            blocked=True,
        )
        yield {"type": "done", "data": {"latency_ms": latency, "blocked": True}}
        return

    hits = []
    if verdict.reason != "寒暄":
        try:
            hits = vectorstore.search(q, k=top_k or settings.top_k)
        except Exception as exc:  # noqa: BLE001
            logger.warning("检索失败：%s", exc)
            hits = []

    sources = _to_sources(hits)
    yield {"type": "sources", "data": sources}

    msgs = prompts.build_messages(q, sources, history_for(session_id))
    acc: list[str] = []
    try:
        for piece in llm.chat(msgs, stream=True):
            acc.append(piece)
            yield {"type": "delta", "data": piece}
    except Exception as exc:  # noqa: BLE001
        logger.error("流式生成失败：%s", exc)
        err = f"\n\n[生成中断] {exc}"
        acc.append(err)
        yield {"type": "delta", "data": err}

    text = "".join(acc)
    latency = int((time.perf_counter() - t0) * 1000)

    if session_id:
        memory.append(session_id, q, text)
    history.add(
        session_id=session_id or "anonymous",
        question=q,
        answer=text,
        latency_ms=latency,
        mode="rag",
        sources=sources,
    )
    yield {"type": "done", "data": {"latency_ms": latency, "blocked": False}}
