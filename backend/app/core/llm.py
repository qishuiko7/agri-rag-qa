"""模型客户端封装：统一对话与向量化入口。

设计要点：
1. 统一走 OpenAI 兼容协议，一份代码支持阿里云百炼（DashScope）与智谱；
2. 嵌入请求内置分批与指数退避重试，规避单次批量上限与偶发 429；
3. 提供 Mock 实现，无密钥时仍可跑通完整链路（用于演示与自测）。

百炼兼容端点：https://dashscope.aliyuncs.com/compatible-mode/v1
智谱兼容端点：https://open.bigmodel.cn/api/paas/v4
"""
from __future__ import annotations

import hashlib
import logging
import math
import re
import time
from typing import Iterable, Sequence

from langchain_core.embeddings import Embeddings
from openai import OpenAI

from app.config import settings

logger = logging.getLogger(__name__)

# 各提供方的 OpenAI 兼容端点
BASE_URLS = {
    "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
}

# 单次嵌入请求的最大文本条数（百炼 text-embedding-v3 限制 10 条）
EMBED_BATCH = {"dashscope": 10, "zhipu": 32, "mock": 64}


class ModelNotConfigured(RuntimeError):
    """密钥缺失或提供方非法时抛出。"""


def _api_key(provider: str) -> str:
    if provider == "dashscope":
        return settings.dashscope_api_key
    if provider == "zhipu":
        return settings.zhipu_api_key
    return ""


def get_chat_client() -> OpenAI:
    """返回对话用客户端。"""
    provider = settings.llm_provider
    if provider == "mock":
        raise ModelNotConfigured("当前为 mock 模式，未启用真实对话模型")
    key = _api_key(provider)
    if not key:
        raise ModelNotConfigured(
            f"未配置 {provider} 的 API Key，请在项目根目录 .env 中填写后重启"
        )
    return OpenAI(api_key=key, base_url=BASE_URLS[provider], timeout=60.0, max_retries=2)


class RemoteEmbeddings(Embeddings):
    """基于 OpenAI 兼容接口的嵌入实现，自带分批与重试。"""

    def __init__(self, provider: str, model: str, dim: int) -> None:
        self.provider = provider
        self.model = model
        self.dim = dim
        self._batch = EMBED_BATCH.get(provider, 10)
        key = _api_key(provider)
        if not key:
            raise ModelNotConfigured(f"未配置 {provider} 的 API Key")
        self.client = OpenAI(
            api_key=key, base_url=BASE_URLS[provider], timeout=60.0, max_retries=0
        )

    # ---------- 内部 ----------
    def _embed_batch(self, texts: Sequence[str], is_query: bool) -> list[list[float]]:
        """单批请求，带 3 次指数退避。"""
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                kwargs = {"model": self.model, "input": list(texts)}
                # 百炼 v3 与智谱 embedding-3 均支持显式维度
                if self.provider in ("dashscope", "zhipu"):
                    kwargs["dimensions"] = self.dim
                resp = self.client.embeddings.create(**kwargs)
                # 按 index 排序，防止服务端乱序返回
                items = sorted(resp.data, key=lambda d: d.index)
                return [list(item.embedding) for item in items]
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                wait = 2 ** attempt
                logger.warning("嵌入请求失败（第 %d 次）：%s，%ds 后重试", attempt + 1, exc, wait)
                time.sleep(wait)
        raise RuntimeError(f"嵌入请求连续失败：{last_err}")

    # ---------- LangChain 接口 ----------
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        total = len(texts)
        for start in range(0, total, self._batch):
            chunk = texts[start : start + self._batch]
            out.extend(self._embed_batch(chunk, is_query=False))
            if start + self._batch < total:
                time.sleep(0.05)  # 轻微限速，避免触发 QPS 限制
        return out

    def embed_query(self, text: str) -> list[float]:
        return self._embed_batch([text], is_query=True)[0]


class MockEmbeddings(Embeddings):
    """无密钥时的确定性伪嵌入。

    用中文 2-gram + 3-gram 哈希到固定维度，并做 L2 归一化。
    相比单纯 2-gram，3-gram 显著降低哈希碰撞，字面相近的文本向量更接近。
    它不具备真实语义理解能力（同义改写无法匹配），仅用于跑通链路与离线演示。
    """

    def __init__(self, dim: int = 1024) -> None:
        self.dim = dim

    _VALID = re.compile(r"[\u4e00-\u9fa5A-Za-z0-9]")

    def _vec(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        clean = re.sub(r"\s+", "", text)
        n_len = len(clean)
        if n_len < 2:
            return vec

        for n, weight in ((2, 1.0), (3, 1.6)):
            for i in range(n_len - n + 1):
                gram = clean[i : i + n]
                # 跳过纯标点片段，避免标点主导相似度
                if not self._VALID.search(gram):
                    continue
                h = int(hashlib.md5(gram.encode("utf-8")).hexdigest()[:8], 16)
                vec[h % self.dim] += weight

        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0:
            return vec
        return [v / norm for v in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


_embedder: Embeddings | None = None


def get_embeddings() -> Embeddings:
    """单例返回嵌入器。"""
    global _embedder
    if _embedder is not None:
        return _embedder

    provider = settings.embedding_provider
    if provider == "mock":
        logger.info("嵌入模型为 mock 模式（无真实语义能力，仅用于链路演示）")
        _embedder = MockEmbeddings(dim=settings.embedding_dim)
    elif not _api_key(provider):
        logger.warning("未配置 %s 密钥，嵌入模型降级为 mock", provider)
        _embedder = MockEmbeddings(dim=settings.embedding_dim)
    else:
        _embedder = RemoteEmbeddings(provider, settings.embedding_model, settings.embedding_dim)
    return _embedder


def chat(
    messages: list[dict],
    temperature: float = 0.3,
    max_tokens: int = 1200,
    stream: bool = False,
):
    """统一的对话调用。

    stream=True 时返回生成器，逐块产出增量文本。
    """
    if settings.llm_provider == "mock":
        return _mock_chat(messages, stream=stream)

    client = get_chat_client()
    kwargs = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if not stream:
        resp = client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""

    kwargs["stream"] = True
    stream_resp = client.chat.completions.create(**kwargs)

    def gen() -> Iterable[str]:
        for chunk in stream_resp:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content

    return gen()


def _mock_chat(messages: list[dict], stream: bool = False) -> str | Iterable[str]:
    """Mock 对话：回显检索到的上下文，用于无密钥演示。"""
    user_q = ""
    context = ""

    for m in messages:
        if m.get("role") != "user":
            continue
        content = m.get("content", "")
        user_q = content
        # 有检索结果：模板形如「【参考资料】...【用户问题】...请依据...」
        if "【参考资料】" in content:
            after = content.split("【参考资料】", 1)[1]
            if "【用户问题】" in after:
                ctx_part, q_part = after.split("【用户问题】", 1)
                context = ctx_part.strip()[:400]
                user_q = q_part
            else:
                context = after.strip()[:400]
                user_q = ""
        # 无检索结果：模板形如「【用户问题】...知识库中未检索到...」
        elif "【用户问题】" in content:
            user_q = content.split("【用户问题】", 1)[1]

        if user_q:
            user_q = re.split(r"\n\s*\n|请依据|知识库中未检索", user_q)[0].strip()
        break

    answer = (
        "【Mock 模式回复】当前未配置真实大模型密钥，以下为链路演示，"
        "配置 .env 中的 DASHSCOPE_API_KEY 后重启即可获得真实农业解答。\n\n"
        f"你的问题：{user_q}\n\n"
        f"检索命中片段（截断）：\n{context or '（知识库无命中）'}"
    )
    if stream:
        def gen() -> Iterable[str]:
            for i in range(0, len(answer), 20):
                yield answer[i : i + 20]
                time.sleep(0.02)

        return gen()
    return answer
