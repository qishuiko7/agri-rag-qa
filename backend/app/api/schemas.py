"""Pydantic 请求/响应模型。"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ---------- 对话 ----------
class AskRequest(BaseModel):
    question: str = Field(..., description="用户问题")
    session_id: str = Field("", description="会话 ID，为空则新建")
    top_k: int | None = Field(None, ge=1, le=20, description="召回条数")
    mode: str = Field("rag", description="rag | agent")


class SourceItem(BaseModel):
    title: str
    category: str
    category_key: str = "general"
    source: str = ""
    content: str = ""
    score: float = 0.0


class AskResponse(BaseModel):
    answer: str
    sources: list[SourceItem] = []
    blocked: bool = False
    latency_ms: int = 0
    session_id: str = ""
    mode: str = "rag"
    tool_calls: list[dict[str, Any]] = []


# ---------- 知识库 ----------
class UploadResult(BaseModel):
    filename: str
    ok: bool
    message: str = ""
    size: int = 0


class DocumentItem(BaseModel):
    name: str
    category: str
    category_name: str
    size: int
    chars: int = 0
    preview: str = ""
    abnormal: bool = False
    abnormal_reason: str = ""


class ReclassifyRequest(BaseModel):
    names: list[str]
    target_category: str


class DeleteRequest(BaseModel):
    names: list[str]


# ---------- 向量库 ----------
class BuildRequest(BaseModel):
    rebuild: bool = True
    category: str | None = None
    chunk_size: int | None = Field(None, ge=100, le=2000)
    chunk_overlap: int | None = Field(None, ge=0, le=500)


# ---------- 历史记录 ----------
class HistoryQuery(BaseModel):
    keyword: str = ""
    start: str = ""
    end: str = ""
    page: int = 1
    page_size: int = 20


class DeleteRecordsRequest(BaseModel):
    ids: list[str]


# ---------- 设置 ----------
class SettingsUpdate(BaseModel):
    llm_provider: str | None = None
    llm_model: str | None = None
    embedding_provider: str | None = None
    embedding_model: str | None = None
    dashscope_api_key: str | None = None
    zhipu_api_key: str | None = None
    chunk_size: int | None = None
    chunk_overlap: int | None = None
    top_k: int | None = None
    memory_rounds: int | None = None
