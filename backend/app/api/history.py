"""历史记录接口：查询、统计、导出、删除。"""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Query
from fastapi.responses import Response

from app.api.schemas import DeleteRecordsRequest, HistoryQuery
from app.core import history

router = APIRouter(prefix="/api/history", tags=["history"])


@router.post("/list")
def list_records(req: HistoryQuery) -> dict:
    """条件查询历史问答。"""
    return history.query(
        keyword=req.keyword,
        start=req.start,
        end=req.end,
        page=req.page,
        page_size=req.page_size,
    )


@router.get("/stats")
def stats() -> dict:
    """基础统计：总量、今日量、拦截量、平均耗时、近 7 日趋势。"""
    return history.stats()


@router.get("/export")
def export(
    keyword: str = Query(""),
    start: str = Query(""),
    end: str = Query(""),
) -> Response:
    """导出 CSV（按当前筛选条件，导出全部匹配记录，不受分页限制）。"""
    records = history.query_all(keyword=keyword, start=start, end=end)
    csv_text = history.export_csv(records)
    filename = "农业问答记录.csv"
    return Response(
        content=csv_text.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        },
    )


@router.post("/delete")
def delete(req: DeleteRecordsRequest) -> dict:
    """批量删除记录。"""
    removed = history.delete(req.ids)
    return {"ok": True, "removed": removed}


@router.post("/clear")
def clear() -> dict:
    """清空全部记录。"""
    removed = history.clear_all()
    return {"ok": True, "removed": removed}
