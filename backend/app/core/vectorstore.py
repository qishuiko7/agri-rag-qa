"""Chroma 文件型向量库管理。

对齐文档要求：
- 纯文件存储、无独立服务进程；
- 支持「新建库」与「追加数据」两种入库模式；
- 支持一键清空 / 重建；
- 关闭遥测与冗余日志，降低内存与磁盘开销。
"""
from __future__ import annotations

import logging
import shutil
import threading
import time
from dataclasses import dataclass
from typing import Sequence

from langchain_chroma import Chroma
from langchain_core.documents import Document

from app.config import settings
from app.core.llm import get_embeddings

logger = logging.getLogger(__name__)

# Chroma 全局只允许初始化一次 Settings，因此在此集中关闭遥测
try:  # pragma: no cover - 依赖版本差异保护
    from chromadb.config import Settings as ChromaSettings

    _ = ChromaSettings(anonymized_telemetry=False, allow_reset=True)
except Exception:  # noqa: BLE001
    pass


@dataclass
class StoreStats:
    """向量库状态快照。"""

    ready: bool
    chunks: int
    collection: str
    embedding_provider: str
    embedding_model: str
    dim: int
    size_mb: float


_lock = threading.Lock()
_store: Chroma | None = None

# 已入库来源聚合结果缓存，按片段总数失效
_sources_cache: dict = {"count": -1, "items": None}


def _collection() -> str:
    return settings.collection_name


def get_store() -> Chroma:
    """获取（并按需惰性创建）向量库实例。"""
    global _store
    if _store is not None:
        return _store

    with _lock:
        if _store is not None:
            return _store
        settings.ensure_dirs()
        _store = Chroma(
            collection_name=_collection(),
            embedding_function=get_embeddings(),
            persist_directory=str(settings.chroma_dir),
            collection_metadata={"hnsw:space": "cosine"},
        )
        logger.info("向量库已加载：%s", _collection())
    return _store


def reset_store() -> None:
    """清空向量库（删除底层持久化目录后重建）。"""
    global _store
    with _lock:
        try:
            if _store is not None:
                _store.reset_collection()
        except Exception:  # noqa: BLE001
            pass
        _store = None
        _sources_cache.update(count=-1, items=None)

        # 兜底：物理清理残留目录，避免旧维度数据干扰
        if settings.chroma_dir.exists():
            for _ in range(3):  # Windows 下文件可能被短暂占用，重试几次
                shutil.rmtree(settings.chroma_dir, ignore_errors=True)
                if not settings.chroma_dir.exists():
                    break
                time.sleep(0.3)
        settings.chroma_dir.mkdir(parents=True, exist_ok=True)
    logger.info("向量库已重置")


def add_documents(docs: Sequence[Document], batch_size: int = 32) -> int:
    """分批写入向量库，返回写入片段数。"""
    if not docs:
        return 0
    store = get_store()
    total = 0
    for start in range(0, len(docs), batch_size):
        batch = list(docs[start : start + batch_size])
        ids = [
            f"{d.metadata.get('content_hash', '')[:8]}-{d.metadata.get('chunk_index', i)}-{start + i}"
            for i, d in enumerate(batch)
        ]
        store.add_documents(batch, ids=ids)
        total += len(batch)
    return total


def _keyword_overlap(query: str, text: str) -> float:
    """查询与片段的中文 2-gram 覆盖率，作为字面匹配信号。

    纯向量检索在专有名词（作物名、病虫名）上容易漂移，
    叠加字面覆盖度能显著提升「问什么就召回什么」的稳定性。
    """
    q = "".join(query.split())
    t = "".join(text.split())
    if len(q) < 2:
        return 0.0
    q_grams = {q[i : i + 2] for i in range(len(q) - 1)}
    t_grams = {t[i : i + 2] for i in range(len(t) - 1)}
    if not q_grams:
        return 0.0
    return len(q_grams & t_grams) / len(q_grams)


def search(
    query: str,
    k: int | None = None,
    category: str | None = None,
    hybrid: bool = True,
):
    """相似度检索（带混合重排）。

    Args:
        query: 用户问题
        k: 召回条数，默认取配置 TOP_K
        category: 可选，限定语料类别（planting/pest/breeding/general）
        hybrid: 是否叠加关键词覆盖率重排

    Returns:
        [(Document, score)]，score 为余弦距离（越小越相似），按相关性降序
    """
    store = get_store()
    top_k = k or settings.top_k
    where = {"category": category} if category else None

    try:
        if not hybrid:
            return store.similarity_search_with_score(query, k=top_k, filter=where)

        # 先多取候选，再按「向量相似度 + 字面覆盖率」重排
        candidates = store.similarity_search_with_score(
            query, k=max(top_k * 3, 10), filter=where
        )
        if not candidates:
            return []

        ranked = []
        for doc, dist in candidates:
            vector_sim = 1.0 - float(dist)          # 距离转相似度
            literal = _keyword_overlap(query, doc.page_content)
            score = 0.65 * vector_sim + 0.35 * literal
            ranked.append((doc, dist, score, literal))

        ranked.sort(key=lambda x: -x[2])

        # Mock 嵌入没有语义能力，全靠字面重叠；若字面几乎不重叠，
        # 说明这条召回纯属噪声，宁可返回空让上层走「无相关内容」兜底，
        # 也不要把不相关片段喂给模型生成错误答案。
        if settings.embedding_provider == "mock":
            ranked = [x for x in ranked if x[3] >= 0.04]

        return [(doc, dist) for doc, dist, _, _ in ranked[:top_k]]
    except Exception as exc:  # noqa: BLE001
        # 空库或维度不匹配时给出明确异常，交由上层转成友好提示
        logger.warning("检索失败：%s", exc)
        raise


def count() -> int:
    """当前库内片段数。"""
    try:
        return get_store()._collection.count()  # noqa: SLF001 - LangChain 未暴露公开计数
    except Exception:  # noqa: BLE001
        return 0


def stats() -> StoreStats:
    """向量库状态，供前端「系统运行状态」展示。"""
    settings.ensure_dirs()
    chunks = count()

    # 只有库内有数据时才统计磁盘占用，避免残留目录造成「0 片段却占 14MB」的误解
    size = 0
    if chunks and settings.chroma_dir.exists():
        for p in settings.chroma_dir.rglob("*"):
            if p.is_file():
                try:
                    size += p.stat().st_size
                except OSError:
                    continue

    return StoreStats(
        ready=chunks > 0,
        chunks=chunks,
        collection=_collection(),
        embedding_provider=settings.embedding_provider,
        embedding_model=settings.embedding_model,
        dim=settings.embedding_dim,
        size_mb=round(size / 1024 / 1024, 2),
    )


def list_sources() -> list[dict]:
    """列出库内已入库的语料来源及片段数（用于知识库页面展示）。

    需要拉取全量 metadata（2270 条约 200 ms），按片段总数做缓存，
    入库后总数变化才重新聚合。
    """
    current = count()
    if _sources_cache["count"] == current and _sources_cache["items"] is not None:
        return _sources_cache["items"]

    try:
        data = get_store()._collection.get(include=["metadatas"])  # noqa: SLF001
    except Exception:  # noqa: BLE001
        return []

    agg: dict[str, dict] = {}
    for meta in data.get("metadatas") or []:
        if not meta:
            continue
        key = meta.get("source", "未知")
        item = agg.setdefault(
            key,
            {
                "source": key,
                "title": meta.get("title", key),
                "category": meta.get("category", "general"),
                "chunks": 0,
            },
        )
        item["chunks"] += 1

    result = sorted(agg.values(), key=lambda x: -x["chunks"])
    _sources_cache.update(count=current, items=result)
    return result
