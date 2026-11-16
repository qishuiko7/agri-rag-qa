"""对话记录管理。

对齐文档要求：全程文件型存储，不依赖数据库。
- 每轮问答自动追加到 JSONL；
- 支持按时间范围、关键词检索；
- 基础统计（总量、今日量、拦截量、平均耗时、类别分布）；
- CSV 导出（原生 csv 模块，不引入 pandas）；
- 单条 / 批量删除。
"""
from __future__ import annotations

import csv
import io
import json
import logging
import threading
import time
import uuid
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()


def _file() -> Path:
    settings.records_dir.mkdir(parents=True, exist_ok=True)
    return settings.records_dir / "qa_records.jsonl"


def _iter_records() -> list[dict]:
    """读取全部记录；坏行跳过，保证单条脏数据不影响整体。"""
    path = _file()
    if not path.exists():
        return []
    out: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _rewrite(records: list[dict]) -> None:
    """全量重写（删除场景使用）。"""
    path = _file()
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(path)


def add(
    *,
    session_id: str,
    question: str,
    answer: str,
    latency_ms: int,
    mode: str = "rag",
    sources: list[dict] | None = None,
    blocked: bool = False,
    tool_calls: list[dict] | None = None,
) -> dict:
    """追加一条问答记录，返回落盘后的记录对象。"""
    now = time.time()
    record = {
        "id": uuid.uuid4().hex[:12],
        "session_id": session_id,
        "question": question,
        "answer": answer,
        "ts": now,
        "datetime": datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S"),
        "latency_ms": latency_ms,
        "mode": mode,
        "sources": sources or [],
        "blocked": blocked,
        "tool_calls": tool_calls or [],
    }
    # 记录落盘失败不应中断问答主流程（例如磁盘满、文件被占用），
    # 否则流式接口会发不出 done 事件，前端一直转圈
    try:
        with _lock:
            with _file().open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001
        logger.error("写入对话记录失败：%s", exc)
    return record


def _filter(records: list[dict], keyword: str, start: str, end: str) -> list[dict]:
    """按关键词与日期范围筛选（query 与导出共用）。"""
    if keyword:
        kw = keyword.strip().lower()
        records = [
            r
            for r in records
            if kw in r.get("question", "").lower() or kw in r.get("answer", "").lower()
        ]

    if start:
        try:
            ts = datetime.strptime(start, "%Y-%m-%d").timestamp()
            records = [r for r in records if r.get("ts", 0) >= ts]
        except ValueError:
            pass
    if end:
        try:
            ts = (datetime.strptime(end, "%Y-%m-%d") + timedelta(days=1)).timestamp()
            records = [r for r in records if r.get("ts", 0) < ts]
        except ValueError:
            pass
    return records


def query(
    *,
    keyword: str = "",
    start: str = "",
    end: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """条件查询，按时间倒序分页返回。

    Args:
        keyword: 问题/答案关键词
        start / end: 日期字符串 YYYY-MM-DD（含当天）
    """
    records = _filter(_iter_records(), keyword, start, end)
    records.sort(key=lambda r: r.get("ts", 0), reverse=True)

    total = len(records)
    page = max(1, page)
    page_size = min(max(1, page_size), 200)
    start_idx = (page - 1) * page_size
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": records[start_idx : start_idx + page_size],
    }


def query_all(*, keyword: str = "", start: str = "", end: str = "") -> list[dict]:
    """导出用：返回全部匹配记录，不做分页截断。

    直接复用 query 会受 page_size 上限（200）限制，导致导出丢数据。
    """
    records = _filter(_iter_records(), keyword, start, end)
    records.sort(key=lambda r: r.get("ts", 0), reverse=True)
    return records


def stats() -> dict:
    """基础统计，用于历史记录页与首页状态卡。"""
    records = _iter_records()
    today = datetime.now().strftime("%Y-%m-%d")
    today_cnt = sum(1 for r in records if r.get("datetime", "").startswith(today))
    blocked = sum(1 for r in records if r.get("blocked"))
    latencies = [r.get("latency_ms", 0) for r in records if r.get("latency_ms")]
    avg_latency = round(sum(latencies) / len(latencies)) if latencies else 0

    # 按日期聚合最近 7 天
    daily: Counter = Counter()
    for r in records:
        d = r.get("datetime", "")[:10]
        if d:
            daily[d] += 1
    last7 = []
    for i in range(6, -1, -1):
        d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        last7.append({"date": d, "count": daily.get(d, 0)})

    # 语料类别分布（来自 sources）
    cats: Counter = Counter()
    for r in records:
        for s in r.get("sources") or []:
            cats[s.get("category", "general")] += 1

    return {
        "total": len(records),
        "today": today_cnt,
        "blocked": blocked,
        "avg_latency_ms": avg_latency,
        "daily": last7,
        "category_dist": dict(cats),
        "modes": dict(Counter(r.get("mode", "rag") for r in records)),
    }


def export_csv(records: list[dict] | None = None) -> str:
    """导出为 CSV 文本（UTF-8 BOM，Excel 直接打开不乱码）。"""
    rows = records if records is not None else _iter_records()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["时间", "会话ID", "模式", "问题", "回答", "耗时(ms)", "是否拦截", "参考来源"])
    for r in rows:
        writer.writerow(
            [
                r.get("datetime", ""),
                r.get("session_id", ""),
                "Agent" if r.get("mode") == "agent" else "RAG",
                r.get("question", ""),
                r.get("answer", ""),
                r.get("latency_ms", 0),
                "是" if r.get("blocked") else "否",
                "；".join(s.get("title", "") for s in r.get("sources") or []),
            ]
        )
    return "\ufeff" + buf.getvalue()


def delete(ids: list[str]) -> int:
    """按 id 批量删除，返回删除条数。"""
    if not ids:
        return 0
    target = set(ids)
    with _lock:
        records = _iter_records()
        kept = [r for r in records if r.get("id") not in target]
        removed = len(records) - len(kept)
        if removed:
            _rewrite(kept)
    return removed


def clear_all() -> int:
    """清空全部记录（谨慎使用）。"""
    with _lock:
        records = _iter_records()
        _rewrite([])
    return len(records)
