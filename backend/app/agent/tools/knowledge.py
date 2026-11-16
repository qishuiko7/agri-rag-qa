"""知识库检索工具。

Agent 最主要的工具：把用户问题转成向量检索，返回农业语料片段。
"""
from __future__ import annotations

from app.config import settings
from app.core import rag
from app.agent.tools.base import tool


@tool(
    name="search_knowledge",
    label="农业知识库检索",
    description=(
        "从本地农业知识库中检索与问题最相关的农技资料片段。"
        "凡是涉及种植、病虫害防治、养殖、施肥、田间管理等技术性问题，都应先调用本工具。"
        "可以多次调用，用不同关键词检索以覆盖不同方面。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "检索关键词或问题，尽量具体，例如「小麦越冬水浇灌时间」",
            },
            "category": {
                "type": "string",
                "enum": ["planting", "pest", "breeding", "general"],
                "description": "限定语料类别：planting=种植技术，pest=病虫害防治，breeding=养殖技术，general=通用农技。不确定时留空。",
            },
            "top_k": {
                "type": "integer",
                "description": "返回条数，默认 5，范围 1~8",
                "minimum": 1,
                "maximum": 8,
            },
        },
        "required": ["query"],
    },
    tags=["RAG", "核心"],
)
def search_knowledge(args: dict) -> dict:
    query = (args.get("query") or "").strip()
    if not query:
        return {"ok": False, "error": "检索关键词为空"}

    k = min(int(args.get("top_k") or settings.top_k), 8)
    category = args.get("category") or None

    # 类别下推到向量库过滤，避免「召回后筛掉」浪费名额
    items = rag.retrieve(query, top_k=k, category=category)
    note = ""

    # 限定类别无命中时放宽到全库，并告知模型
    if not items and category:
        items = rag.retrieve(query, top_k=k)
        if items:
            note = f"指定类别 {category} 无命中，已改为全库检索"

    return {
        "query": query,
        "count": len(items),
        "results": [
            {
                "title": i["title"],
                "category": i["category"],
                "content": i["content"][:400],
                "similarity": round(1 - i["score"], 3),
            }
            for i in items
        ],
        "note": note,
        "summary": (
            f"检索到 {len(items)} 条相关片段"
            if items
            else "知识库中未找到相关内容，请基于通用农学常识谨慎回答并说明来源不足"
        ),
    }
