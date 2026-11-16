"""文本切片器。

严格对齐文档第七章节能策略：chunk_size=500、chunk_overlap=50。
在默认递归分隔符基础上补充中文标点，保证断句落在语义边界上。
"""
from __future__ import annotations

import logging
import re
from typing import Iterable

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import settings

logger = logging.getLogger(__name__)

# 中文优先的分隔符序列：段落 -> 换行 -> 句末标点 -> 分句标点 -> 字符
SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", "…", "，", "、", " ", ""]


def build_splitter(chunk_size: int | None = None, chunk_overlap: int | None = None):
    """构建切片器，参数缺省时读取全局配置。"""
    size = chunk_size or settings.chunk_size
    overlap = chunk_overlap if chunk_overlap is not None else settings.chunk_overlap
    if overlap >= size:
        overlap = max(0, size // 10)
    return RecursiveCharacterTextSplitter(
        chunk_size=size,
        chunk_overlap=overlap,
        separators=SEPARATORS,
        length_function=len,
        keep_separator=True,
    )


def split_documents(
    docs: Iterable[Document],
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[Document]:
    """切片并补齐 metadata。

    每个切片带上 chunk_index 与所属文档标题，便于前端展示引用来源。
    """
    splitter = build_splitter(chunk_size, chunk_overlap)
    chunks: list[Document] = []
    doc_list = list(docs) if not isinstance(docs, list) else docs

    for doc in doc_list:
        pieces = splitter.split_text(doc.page_content)
        # 标题由 loader 从元信息块解析，缺失时退回文件名
        title = doc.metadata.get("title") or doc.metadata.get("source", "")

        for idx, piece in enumerate(pieces):
            # keep_separator 会把分隔符留在片段首尾，去掉行首孤立标点
            text = re.sub(r"^[。！？；，、…：\s]+", "", piece).strip()
            if len(text) < 20:  # 过短碎片直接丢弃
                continue
            chunks.append(
                Document(
                    page_content=text,
                    metadata={
                        **doc.metadata,
                        "title": title,
                        "chunk_index": idx,
                        "chunk_chars": len(text),
                    },
                )
            )

    logger.info("切片完成：%d 篇文档 -> %d 个片段", len(doc_list), len(chunks))
    return chunks
