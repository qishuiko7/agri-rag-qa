"""知识库管理接口：上传、列表、预览、删除、分类调整、异常筛查。"""
from __future__ import annotations

import logging
import os
import shutil
import time
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from app.api.schemas import (
    DeleteRequest,
    DocumentItem,
    ReclassifyRequest,
    UploadResult,
)
from app.config import settings
from app.core import loader

router = APIRouter(prefix="/api/kb", tags=["knowledge-base"])
logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
ALLOWED_EXT = {".txt", ".md", ".pdf", ".csv"}

# 文档清单缓存：598 个文件逐个解析约需 0.7 秒。
# 增删文件会改变目录 mtime，签名立即失效；TTL 只是兜底。
_cache: dict = {"signature": None, "items": [], "ts": 0.0}
_CACHE_TTL = 300.0


def _dir_signature() -> tuple:
    """用各分类目录的 (文件数, mtime) 作为缓存签名。

    用 scandir 只做目录项枚举，不逐个 stat 文件，598 个文件约 2 ms。
    """
    sig = []
    for cat in settings.categories:
        d = settings.corpus_dir / cat
        if not d.exists():
            sig.append((cat, 0, 0.0))
            continue
        try:
            count = sum(1 for e in os.scandir(d) if e.is_file())
            mtime = d.stat().st_mtime
        except OSError:
            count, mtime = 0, 0.0
        sig.append((cat, count, round(mtime, 3)))
    return tuple(sig)


def _all_docs() -> list[DocumentItem]:
    """扫描语料目录，产出文档清单（含异常标记）。"""
    sig = _dir_signature()
    if _cache["signature"] == sig and time.time() - _cache["ts"] < _CACHE_TTL:
        return _cache["items"]

    items: list[DocumentItem] = []
    for cat_key, cat_name in settings.categories.items():
        cat_dir = settings.corpus_dir / cat_key
        if not cat_dir.exists():
            continue
        for p in sorted(cat_dir.iterdir()):
            if not p.is_file() or p.suffix.lower() not in ALLOWED_EXT:
                continue
            size = p.stat().st_size
            abnormal = False
            reason = ""
            chars = 0
            preview = ""

            if size == 0:
                abnormal, reason = True, "空文件"
            elif size > MAX_UPLOAD_BYTES:
                abnormal, reason = True, "超大文件（>20MB）"
            else:
                try:
                    doc = loader.load_file(p)
                    if doc is None:
                        abnormal, reason = True, "无法解析或内容过少"
                    else:
                        chars = len(doc.page_content)
                        preview = doc.page_content[:200].replace("\n", " ")
                        if chars < 100:
                            abnormal, reason = True, "内容过短"
                except UnicodeDecodeError:
                    abnormal, reason = True, "编码异常"
                except Exception as exc:  # noqa: BLE001
                    abnormal, reason = True, f"解析失败：{exc}"

            items.append(
                DocumentItem(
                    name=p.name,
                    category=cat_key,
                    category_name=cat_name,
                    size=size,
                    chars=chars,
                    preview=preview,
                    abnormal=abnormal,
                    abnormal_reason=reason,
                )
            )

    _cache.update(signature=sig, items=items, ts=time.time())
    return items


@router.get("/stats")
def stats() -> dict:
    """知识库总体统计。"""
    docs = _all_docs()
    by_cat: dict[str, dict] = {}
    for key, name in settings.categories.items():
        subset = [d for d in docs if d.category == key]
        by_cat[key] = {
            "name": name,
            "count": len(subset),
            "chars": sum(d.chars for d in subset),
            "abnormal": sum(1 for d in subset if d.abnormal),
        }
    return {
        "total": len(docs),
        "total_chars": sum(d.chars for d in docs),
        "abnormal": sum(1 for d in docs if d.abnormal),
        "by_category": by_cat,
        "categories": settings.categories,
    }


@router.get("/documents")
def documents(
    category: str = Query("", description="按类别过滤"),
    keyword: str = Query("", description="按文件名搜索"),
    only_abnormal: bool = Query(False),
) -> dict:
    docs = _all_docs()
    if category:
        docs = [d for d in docs if d.category == category]
    if keyword:
        kw = keyword.lower()
        docs = [d for d in docs if kw in d.name.lower()]
    if only_abnormal:
        docs = [d for d in docs if d.abnormal]
    return {"total": len(docs), "items": docs}


@router.get("/preview")
def preview(name: str = Query(...), category: str = Query(...)) -> dict:
    """读取单个文档全文预览。"""
    path = settings.corpus_dir / category / name
    if not path.exists() or not path.is_file():
        raise HTTPException(404, "文档不存在")
    doc = loader.load_file(path)
    if doc is None:
        raise HTTPException(400, "文档无法解析")
    return {
        "name": name,
        "category": category,
        "chars": len(doc.page_content),
        "content": doc.page_content[:8000],
        "meta": {
            "title": doc.metadata.get("title", ""),
            "column": doc.metadata.get("column", ""),
            "publish_date": doc.metadata.get("publish_date", ""),
            "origin": doc.metadata.get("origin", ""),
        },
    }


@router.post("/upload", response_model=list[UploadResult])
async def upload(
    files: list[UploadFile] = File(...),
    category: str = Query("general"),
) -> list[UploadResult]:
    """批量上传语料文件到指定分类目录。"""
    if category not in settings.categories:
        raise HTTPException(400, f"未知分类：{category}")
    target_dir = settings.corpus_dir / category
    target_dir.mkdir(parents=True, exist_ok=True)

    results: list[UploadResult] = []
    for f in files:
        name = Path(f.filename or "unnamed.txt").name
        ext = Path(name).suffix.lower()
        if ext not in ALLOWED_EXT:
            results.append(UploadResult(filename=name, ok=False, message=f"不支持的格式 {ext}"))
            continue
        content = await f.read()
        if len(content) == 0:
            results.append(UploadResult(filename=name, ok=False, message="空文件"))
            continue
        if len(content) > MAX_UPLOAD_BYTES:
            results.append(UploadResult(filename=name, ok=False, message="文件超过 20MB"))
            continue

        dest = target_dir / name
        # 同名文件自动加序号，避免覆盖
        if dest.exists():
            stem, suffix = dest.stem, dest.suffix
            i = 1
            while (target_dir / f"{stem}_{i}{suffix}").exists():
                i += 1
            dest = target_dir / f"{stem}_{i}{suffix}"

        dest.write_bytes(content)
        results.append(UploadResult(filename=dest.name, ok=True, message="已导入", size=len(content)))

    logger.info("上传完成：%d 个文件 -> %s", len(results), category)
    return results


@router.post("/reclassify")
def reclassify(req: ReclassifyRequest) -> dict:
    """把文档移动到另一个分类目录。"""
    if req.target_category not in settings.categories:
        raise HTTPException(400, "目标分类不存在")

    moved = 0
    for cat_key in settings.categories:
        src_dir = settings.corpus_dir / cat_key
        if cat_key == req.target_category or not src_dir.exists():
            continue
        for name in req.names:
            src = src_dir / name
            if not src.exists():
                continue
            dst = settings.corpus_dir / req.target_category / name
            if dst.exists():
                dst = dst.with_stem(f"{dst.stem}_{cat_key}")
            shutil.move(str(src), str(dst))
            moved += 1
    return {"ok": True, "moved": moved}


@router.post("/delete")
def delete(req: DeleteRequest) -> dict:
    """批量删除语料文档（不进入系统回收站，直接移除文件）。"""
    removed = 0
    for cat_key in settings.categories:
        cat_dir = settings.corpus_dir / cat_key
        if not cat_dir.exists():
            continue
        for name in req.names:
            p = cat_dir / name
            if p.exists() and p.is_file():
                p.unlink()
                removed += 1
    return {"ok": True, "removed": removed}


@router.get("/report")
def report() -> dict:
    """读取抓取阶段的语料统计报告（若存在）。"""
    import json

    path = settings.data_dir / "corpus_report.json"
    if not path.exists():
        return {"available": False}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["available"] = True
        return data
    except Exception:  # noqa: BLE001
        return {"available": False}
