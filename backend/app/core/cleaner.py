"""语料清洗器。

对应文档「数据清洗」要求：过滤空白文本、重复内容、乱码字符，简易识别并剔除
广告类无效文本。全部使用 Python 原生字符串与正则，不引入重型 NLP 依赖。
"""
from __future__ import annotations

import hashlib
import re
from typing import Iterable

from langchain_core.documents import Document

# 控制字符（保留 \n \t）
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# 连续空白
_SPACES = re.compile(r"[ \t\u3000]{2,}")
# 中文字符之间的空格（网页 HTML 提取常见噪声，如「长江中下游 及华南 地区」）
# 注意：只匹配空格与制表符，绝不能匹配 \s，否则会把段落换行一并吞掉
_CJK_SPACE = re.compile(r"(?<=[\u4e00-\u9fa5])[ \t\u3000]+(?=[\u4e00-\u9fa5])")
# 连续空行
_BLANK_LINES = re.compile(r"\n{3,}")

# 广告 / 导流噪声
AD_PATTERNS = [
    r"扫码关注", r"扫描二维码", r"微信公众号", r"点击关注", r"关注我们",
    r"广告", r"推广合作", r"商务合作", r"投稿邮箱", r"免责声明",
    r"本文仅代表作者", r"转载请注明", r"版权归.*所有",
    r"客服电话", r"咨询热线", r"加盟代理",
]

# 页面结构噪声（导航、版权、分享栏）
NOISE_LINE = re.compile(
    r"^(首页|上一页|下一页|返回顶部|打印本页|关闭窗口|分享到|收藏|"
    r"主办单位|承办单位|技术支持|网站地图|联系我们|关于我们|版权声明|"
    r"ICP备|京公网安备|网站标识码|浏览总量|访问量)[:：]?.*$"
)


def clean_text(text: str) -> str:
    """单篇文本清洗。"""
    if not text:
        return ""

    # 1. 去掉控制字符与零宽字符
    text = _CTRL.sub("", text)
    text = text.replace("\u200b", "").replace("\ufeff", "").replace("\xa0", " ")

    # 2. 统一换行，压缩空白
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _SPACES.sub(" ", text)
    # 去掉中文字符之间的多余空格（不影响中英文混排）
    text = _CJK_SPACE.sub("", text)

    # 3. 按行去噪
    kept: list[str] = []
    seen: set[str] = set()
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            kept.append("")
            continue
        # 纯符号 / 纯数字行丢弃
        if not re.search(r"[\u4e00-\u9fa5A-Za-z]", line):
            continue
        # 结构噪声行
        if NOISE_LINE.match(line):
            continue
        # 广告行
        if any(re.search(p, line) for p in AD_PATTERNS):
            continue
        # 段落级去重（同一行重复出现只保留一次）
        key = re.sub(r"\s+", "", line)
        if key in seen:
            continue
        seen.add(key)
        kept.append(line)

    result = "\n".join(kept)
    result = _BLANK_LINES.sub("\n\n", result).strip()
    return result


def content_hash(text: str) -> str:
    """内容指纹，用于跨文档去重。"""
    normalized = re.sub(r"\s+", "", text)
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


def is_low_quality(text: str, min_chars: int = 100) -> bool:
    """判断是否为低质量文本。

    规则：过短、汉字占比过低、重复字符占比过高。
    """
    if len(text) < min_chars:
        return True
    han = len(re.findall(r"[\u4e00-\u9fa5]", text))
    if han / max(len(text), 1) < 0.15:
        return True
    # 单一字符重复超过 30% 视为乱码
    if text and max(text.count(c) for c in set(text[:200])) / len(text) > 0.3:
        return True
    return False


def clean_documents(docs: Iterable[Document], min_chars: int = 100) -> list[Document]:
    """批量清洗 + 跨文档去重。

    返回清洗后的文档列表；重复与低质量文档被丢弃。
    """
    out: list[Document] = []
    seen: set[str] = set()
    for doc in docs:
        cleaned = clean_text(doc.page_content)
        if is_low_quality(cleaned, min_chars):
            continue
        h = content_hash(cleaned)
        if h in seen:
            continue
        seen.add(h)
        out.append(
            Document(
                page_content=cleaned,
                metadata={**doc.metadata, "content_hash": h, "chars": len(cleaned)},
            )
        )
    return out
