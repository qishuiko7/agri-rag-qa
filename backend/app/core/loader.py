"""多格式语料加载器。

支持 TXT / MD / PDF / CSV，统一产出 LangChain Document。
针对笔记本环境做了两点约束：
1. 逐个文件读取、按批产出，避免一次性把全量语料读进内存；
2. 编码自动探测（utf-8 → gbk → gb18030），损坏文件跳过而不中断整批。
"""
from __future__ import annotations

import csv
import io
import logging
import re
from pathlib import Path
from typing import Iterable, Iterator

from langchain_core.documents import Document
from pypdf import PdfReader

logger = logging.getLogger(__name__)

SUPPORTED = {".txt", ".md", ".pdf", ".csv"}
MAX_FILE_BYTES = 20 * 1024 * 1024  # 单文件 20MB 上限，超出视为异常文件

# 语料文件头部的元信息块：标题/栏目/日期/来源 + 分隔线
_META_LINE = re.compile(r"^(标题|栏目|日期|来源|分类)[：:]\s*(.*)$")
_META_SEP = re.compile(r"^-{10,}\s*$")


def parse_front_matter(text: str) -> tuple[dict, str]:
    """解析文件头部的元信息块，返回 (元信息, 正文)。

    元信息（标题/栏目/日期/来源）不参与向量化——它们对语义检索没有帮助，
    留在正文里只会稀释片段的信息密度、干扰相似度计算。
    若文件没有元信息块，原样返回。
    """
    lines = text.split("\n")
    meta: dict = {}
    body_start = 0

    for i, line in enumerate(lines[:12]):
        stripped = line.strip()
        if not stripped:
            continue
        m = _META_LINE.match(stripped)
        if m:
            meta[m.group(1)] = m.group(2).strip()
            body_start = i + 1
            continue
        if _META_SEP.match(stripped):
            body_start = i + 1
            break
        # 遇到非元信息内容，说明没有元信息块
        break

    if not meta:
        return {}, text

    body = "\n".join(lines[body_start:]).strip()
    return meta, body if body else text


def _read_text(path: Path) -> str:
    """按 utf-8 → gbk → gb18030 顺序尝试解码。"""
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    # 全部失败时容错解码，丢弃非法字节
    return raw.decode("utf-8", errors="ignore")


def _read_pdf(path: Path) -> str:
    """逐页提取 PDF 文本；加密或损坏文件返回空串。"""
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:  # noqa: BLE001
                logger.warning("PDF 加密无法解密，跳过：%s", path.name)
                return ""
        pages = []
        for page in reader.pages:
            try:
                pages.append(page.extract_text() or "")
            except Exception:  # noqa: BLE001
                continue
        return "\n".join(pages)
    except Exception as exc:  # noqa: BLE001
        logger.warning("PDF 解析失败 %s：%s", path.name, exc)
        return ""


def _read_csv(path: Path) -> str:
    """把 CSV 每行拼成「列名: 值」的文本行，便于语义检索。"""
    text = _read_text(path)
    try:
        rows = list(csv.reader(io.StringIO(text)))
    except Exception:  # noqa: BLE001
        return text
    if not rows:
        return ""
    header = rows[0]
    lines = []
    for row in rows[1:]:
        pairs = [f"{h}：{v}" for h, v in zip(header, row) if v.strip()]
        if pairs:
            lines.append("；".join(pairs))
    return "\n".join(lines)


def load_file(path: Path) -> Document | None:
    """加载单个文件，失败返回 None。"""
    if not path.is_file() or path.suffix.lower() not in SUPPORTED:
        return None
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size == 0 or size > MAX_FILE_BYTES:
        logger.warning("跳过异常体积文件 %s（%d 字节）", path.name, size)
        return None

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        content = _read_pdf(path)
    elif suffix == ".csv":
        content = _read_csv(path)
    else:
        content = _read_text(path)

    if not content or len(content.strip()) < 20:
        return None

    # 剥离元信息块，正文只保留实际内容
    meta, body = parse_front_matter(content)
    if len(body.strip()) < 20:
        body = content  # 元信息解析后正文过短，回退到全文

    # 分类优先取元信息里的「分类」字段，其次取父目录名
    category = meta.get("分类") or path.parent.name

    return Document(
        page_content=body,
        metadata={
            "source": path.name,
            "path": str(path),
            "category": category,
            "file_type": suffix.lstrip("."),
            "size": size,
            "title": meta.get("标题", path.stem),
            "column": meta.get("栏目", ""),
            "publish_date": meta.get("日期", ""),
            "origin": meta.get("来源", ""),
        },
    )


def iter_files(root: Path, recursive: bool = True) -> Iterator[Path]:
    """遍历目录下的受支持文件。"""
    pattern = "**/*" if recursive else "*"
    for p in sorted(root.glob(pattern)):
        if p.is_file() and p.suffix.lower() in SUPPORTED:
            yield p


def load_directory(root: Path, recursive: bool = True) -> list[Document]:
    """加载整个目录（小规模场景使用，大规模请走 batch_load）。"""
    docs = []
    for p in iter_files(root, recursive):
        doc = load_file(p)
        if doc:
            docs.append(doc)
    return docs


def batch_load(root: Path, batch_size: int = 30, recursive: bool = True) -> Iterator[list[Document]]:
    """分批加载，每批最多 batch_size 个文档，控制内存峰值。

    对应文档「语料分批加载：每次仅加载 20~50 份文档」的要求。
    """
    buf: list[Document] = []
    for p in iter_files(root, recursive):
        doc = load_file(p)
        if doc is None:
            continue
        buf.append(doc)
        if len(buf) >= batch_size:
            yield buf
            buf = []
    if buf:
        yield buf
