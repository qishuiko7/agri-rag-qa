"""系统设置接口：参数读取、更新、模型连通性测试。"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter

from app.api.schemas import SettingsUpdate
from app.config import PROJECT_DIR, settings
from app.core import llm

router = APIRouter(prefix="/api/settings", tags=["settings"])
logger = logging.getLogger(__name__)

ENV_PATH = PROJECT_DIR / ".env"


def _mask(key: str) -> str:
    """密钥脱敏：只显示首尾各 4 位。"""
    if not key:
        return ""
    if len(key) <= 10:
        return "*" * len(key)
    return f"{key[:4]}{'*' * 8}{key[-4:]}"


def _write_env(updates: dict[str, str]) -> None:
    """把键值写回 .env，保留原有注释与顺序。"""
    lines: list[str] = []
    existing: dict[str, int] = {}

    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                k = stripped.split("=", 1)[0].strip()
                existing[k] = len(lines)
            lines.append(line)
    else:
        lines = ["# 农业智能问答助手 - 环境配置", ""]

    for key, value in updates.items():
        if key in existing:
            lines[existing[key]] = f"{key}={value}"
        else:
            lines.append(f"{key}={value}")

    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


@router.get("")
def read_settings() -> dict:
    """读取当前配置（密钥脱敏）。"""
    return {
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,
        "embedding_provider": settings.embedding_provider,
        "embedding_model": settings.embedding_model,
        "embedding_dim": settings.embedding_dim,
        "dashscope_api_key": _mask(settings.dashscope_api_key),
        "zhipu_api_key": _mask(settings.zhipu_api_key),
        "has_dashscope_key": bool(settings.dashscope_api_key),
        "has_zhipu_key": bool(settings.zhipu_api_key),
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
        "top_k": settings.top_k,
        "memory_rounds": settings.memory_rounds,
        "batch_size": settings.batch_size,
        "collection": settings.collection_name,
        "env_path": str(ENV_PATH),
    }


@router.post("")
def update_settings(req: SettingsUpdate) -> dict:
    """更新配置。

    检索类参数（chunk/top_k/memory）立即生效；
    模型与密钥变更写入 .env，需要重启服务才会重建客户端。
    """
    runtime_keys = {"chunk_size", "chunk_overlap", "top_k", "memory_rounds"}
    env_updates: dict[str, str] = {}
    hot: dict = {}

    payload = req.model_dump(exclude_none=True)
    for key, value in payload.items():
        if key in runtime_keys:
            hot[key] = value
            # 同时落盘，否则重启后参数会退回默认值
            env_updates[key.upper()] = str(value)
        elif key == "dashscope_api_key":
            if value and not value.startswith("*"):
                env_updates["DASHSCOPE_API_KEY"] = value
        elif key == "zhipu_api_key":
            if value and not value.startswith("*"):
                env_updates["ZHIPU_API_KEY"] = value
        else:
            env_updates[key.upper()] = str(value)

    applied = settings.update_runtime(**hot)
    if env_updates:
        _write_env(env_updates)

    needs_restart = bool(
        {"LLM_PROVIDER", "LLM_MODEL", "EMBEDDING_PROVIDER", "EMBEDDING_MODEL",
         "DASHSCOPE_API_KEY", "ZHIPU_API_KEY"} & set(env_updates)
    )

    return {
        "ok": True,
        "applied_now": applied,
        "saved_to_env": list(env_updates.keys()),
        "need_restart": needs_restart,
        "message": "已保存，模型相关配置需重启服务生效" if needs_restart else "已保存并即时生效",
    }


@router.post("/test")
def test_model() -> dict:
    """测试对话模型连通性。"""
    try:
        reply = llm.chat([{"role": "user", "content": "回复两个字：正常"}], max_tokens=16)
        return {"ok": True, "reply": reply, "provider": settings.llm_provider,
                "model": settings.llm_model}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "provider": settings.llm_provider,
                "model": settings.llm_model}


@router.post("/test-embedding")
def test_embedding() -> dict:
    """测试嵌入模型连通性与维度。"""
    try:
        emb = llm.get_embeddings()
        vec = emb.embed_query("小麦越冬水什么时候浇")
        return {
            "ok": True,
            "provider": settings.embedding_provider,
            "model": settings.embedding_model,
            "dim": len(vec),
            "sample": [round(v, 4) for v in vec[:5]],
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
