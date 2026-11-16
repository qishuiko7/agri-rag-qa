"""语料入库编排。

把「扫描 -> 分批加载 -> 清洗 -> 切片 -> 向量化入库」串成可观测的后台任务，
供向量库构建页面轮询进度。

对应文档「入库状态展示」：实时展示入库进度、成功数量、失败数量。
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from app.config import settings
from app.core import cleaner, loader, splitter, vectorstore

logger = logging.getLogger(__name__)


@dataclass
class IngestState:
    """入库任务状态快照。"""

    running: bool = False
    stage: str = "idle"  # idle / scanning / loading / splitting / embedding / done / error
    total_files: int = 0
    processed_files: int = 0
    total_chunks: int = 0
    written_chunks: int = 0
    skipped_files: int = 0
    message: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0
    error: str = ""

    @property
    def percent(self) -> float:
        """按文件数计算进度。

        边切边写时 total_chunks 会持续增长，用它做分母会导致进度回退，
        因此以「已处理文件 / 总文件」为主；若写入还没跟上，则压住进度，
        避免出现「显示 99% 却一直转圈」的观感。
        """
        if not self.running and self.stage == "done":
            return 100.0
        if self.total_files <= 0:
            return 0.0

        pct = self.processed_files / self.total_files * 100
        if self.total_chunks > 0 and self.written_chunks < self.total_chunks:
            pct = min(pct, 95.0)
        return round(min(99.0, pct), 1)

    @property
    def elapsed(self) -> float:
        if not self.started_at:
            return 0.0
        end = self.finished_at or time.time()
        return round(end - self.started_at, 1)

    def snapshot(self) -> dict:
        d = asdict(self)
        d["percent"] = self.percent
        d["elapsed"] = self.elapsed
        return d


_state = IngestState()
_state_lock = threading.Lock()
_thread: threading.Thread | None = None


def get_state() -> dict:
    with _state_lock:
        return _state.snapshot()


def _set(**kwargs) -> None:
    with _state_lock:
        for k, v in kwargs.items():
            setattr(_state, k, v)


def build(
    *,
    rebuild: bool = True,
    category: str | None = None,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> bool:
    """启动后台入库任务。

    Args:
        rebuild: True=清空重建，False=追加到现有库
        category: 仅处理某个类别目录（planting/pest/breeding/general）
        chunk_size / chunk_overlap: 覆盖默认切片参数

    Returns:
        True 表示任务已启动；False 表示已有任务在跑。
    """
    global _thread, _state

    with _state_lock:
        if _state.running:
            return False
        # 重新绑定为新实例，比调用 __init__ 重置更清晰，也不会漏掉字段
        _state = IngestState(running=True, stage="scanning", started_at=time.time())

    def worker() -> None:
        try:
            _run(rebuild=rebuild, category=category,
                 chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        except Exception as exc:  # noqa: BLE001
            logger.exception("入库任务失败")
            _set(running=False, stage="error", error=str(exc),
                 message=f"入库失败：{exc}", finished_at=time.time())

    _thread = threading.Thread(target=worker, daemon=True, name="ingest")
    _thread.start()
    return True


def _run(
    *,
    rebuild: bool,
    category: str | None,
    chunk_size: int | None,
    chunk_overlap: int | None,
) -> None:
    settings.ensure_dirs()

    root = settings.corpus_dir
    dirs = [root / category] if category else [root / k for k in settings.categories]
    dirs = [d for d in dirs if d.exists()]

    files = [p for d in dirs for p in loader.iter_files(d)]
    _set(total_files=len(files), stage="loading", message=f"发现 {len(files)} 个语料文件")

    if not files:
        _set(running=False, stage="done", message="语料目录为空，请先导入文档",
             finished_at=time.time())
        return

    if rebuild:
        vectorstore.reset_store()
        _set(message="已清空旧向量库，准备重新构建")

    processed = 0
    skipped = 0
    written = 0
    generated = 0
    failed_batches = 0
    batch_size = settings.batch_size

    # 单遍处理：每批「加载 -> 清洗 -> 切片 -> 立即写入」。
    # 不把全部切片攒在内存里，内存占用只与单批大小相关，与语料总量无关。
    for start in range(0, len(files), batch_size):
        batch_paths = files[start : start + batch_size]
        docs = []
        for p in batch_paths:
            doc = loader.load_file(p)
            if doc is None:
                skipped += 1
                continue
            docs.append(doc)
        processed += len(batch_paths)

        cleaned = cleaner.clean_documents(docs)
        skipped += len(docs) - len(cleaned)
        chunks = splitter.split_documents(
            cleaned, chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )
        generated += len(chunks)

        _set(
            stage="embedding",
            processed_files=processed,
            skipped_files=skipped,
            total_chunks=generated,
            message=f"已处理 {processed}/{len(files)} 篇，生成 {generated} 个片段",
        )

        if chunks:
            try:
                written += vectorstore.add_documents(chunks)
            except Exception as exc:  # noqa: BLE001
                failed_batches += 1
                logger.error("第 %d 批写入失败：%s", start // batch_size + 1, exc)
                _set(error=f"{failed_batches} 个批次写入失败：{exc}")

        _set(written_chunks=written)

    if generated == 0:
        _set(running=False, stage="done", message="没有可入库的有效文本",
             finished_at=time.time())
        return

    if failed_batches:
        message = (
            f"入库完成但有 {failed_batches} 个批次失败："
            f"有效文档 {processed - skipped} 篇，成功写入 {written}/{generated} 个片段"
        )
        _set(error=f"{failed_batches} 个批次写入失败", message=message)
    else:
        _set(message=f"入库完成：{processed - skipped} 篇有效文档，{written} 个片段")

    _set(running=False, stage="done", written_chunks=written, finished_at=time.time())
