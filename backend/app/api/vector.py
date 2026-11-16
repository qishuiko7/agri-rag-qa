"""向量库接口：状态、构建、进度、重置、已入库来源。"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.api.schemas import BuildRequest
from app.config import settings
from app.core import ingest, vectorstore

router = APIRouter(prefix="/api/vector", tags=["vector-store"])
logger = logging.getLogger(__name__)


@router.get("/stats")
def stats() -> dict:
    """向量库当前状态。"""
    st = vectorstore.stats()
    return {
        "ready": st.ready,
        "chunks": st.chunks,
        "collection": st.collection,
        "embedding_provider": st.embedding_provider,
        "embedding_model": st.embedding_model,
        "dim": st.dim,
        "size_mb": st.size_mb,
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
    }


@router.post("/build")
def build(req: BuildRequest) -> dict:
    """启动后台入库任务。"""
    started = ingest.build(
        rebuild=req.rebuild,
        category=req.category,
        chunk_size=req.chunk_size,
        chunk_overlap=req.chunk_overlap,
    )
    if not started:
        raise HTTPException(409, "已有入库任务正在执行，请等待完成")
    return {"ok": True, "message": "入库任务已启动，可轮询 /api/vector/progress 查看进度"}


@router.get("/progress")
def progress() -> dict:
    """入库进度快照。"""
    return ingest.get_state()


@router.post("/reset")
def reset() -> dict:
    """清空向量库。"""
    state = ingest.get_state()
    if state.get("running"):
        raise HTTPException(409, "入库任务执行中，无法重置")
    vectorstore.reset_store()
    return {"ok": True, "message": "向量库已清空"}


@router.get("/sources")
def sources() -> dict:
    """已入库的语料来源及片段数。"""
    items = vectorstore.list_sources()
    return {"total": len(items), "items": items}


@router.post("/search")
def search(q: str, k: int = 5) -> dict:
    """检索调试：直接查看某个问题命中的片段。"""
    try:
        hits = vectorstore.search(q, k=k)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"检索失败：{exc}") from exc
    return {
        "query": q,
        "hits": [
            {
                "title": d.metadata.get("title") or d.metadata.get("source"),
                "category": settings.categories.get(d.metadata.get("category", ""), "通用农技"),
                "score": round(float(s), 4),
                "content": d.page_content[:400],
            }
            for d, s in hits
        ],
    }
