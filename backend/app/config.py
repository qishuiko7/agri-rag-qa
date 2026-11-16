"""全局配置：集中管理路径、模型参数与 RAG 超参。

所有可调项优先从环境变量 / .env 读取，缺省值对齐《案例5》文档第七章
「笔记本专属运行优化策略」中给出的推荐值。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# 项目根目录：backend/ 的上一级
BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent
DATA_DIR = BACKEND_DIR / "data"

# 依次加载：项目根 .env → backend/.env，后加载的覆盖先加载的
for candidate in (PROJECT_DIR / ".env", BACKEND_DIR / ".env"):
    if candidate.exists():
        load_dotenv(candidate, override=True)


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except (TypeError, ValueError):
        return default


@dataclass
class Settings:
    """配置对象。进程启动时构建一次，部分字段支持运行期热更新。"""

    # ---------- 目录 ----------
    data_dir: Path = DATA_DIR
    corpus_dir: Path = DATA_DIR / "corpus"
    chroma_dir: Path = DATA_DIR / "chroma"
    records_dir: Path = DATA_DIR / "records"
    upload_dir: Path = DATA_DIR / "uploads"

    # ---------- 模型 ----------
    dashscope_api_key: str = field(default_factory=lambda: os.getenv("DASHSCOPE_API_KEY", "").strip())
    zhipu_api_key: str = field(default_factory=lambda: os.getenv("ZHIPU_API_KEY", "").strip())

    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "dashscope").strip().lower())
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "qwen-plus").strip())

    embedding_provider: str = field(
        default_factory=lambda: os.getenv("EMBEDDING_PROVIDER", "dashscope").strip().lower()
    )
    embedding_model: str = field(
        default_factory=lambda: os.getenv("EMBEDDING_MODEL", "text-embedding-v3").strip()
    )
    embedding_dim: int = field(default_factory=lambda: _int("EMBEDDING_DIM", 1024))

    # ---------- RAG 超参 ----------
    chunk_size: int = field(default_factory=lambda: _int("CHUNK_SIZE", 500))
    chunk_overlap: int = field(default_factory=lambda: _int("CHUNK_OVERLAP", 50))
    top_k: int = field(default_factory=lambda: _int("TOP_K", 5))
    memory_rounds: int = field(default_factory=lambda: _int("MEMORY_ROUNDS", 5))
    batch_size: int = field(default_factory=lambda: _int("BATCH_SIZE", 30))

    # ---------- 服务 ----------
    host: str = field(default_factory=lambda: os.getenv("HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _int("PORT", 8000))

    # ---------- 语料分类 ----------
    # key 为磁盘目录名（避免中文路径在部分工具链下的编码问题），value 为展示名
    categories: dict = field(
        default_factory=lambda: {
            "planting": "种植技术",
            "pest": "病虫害防治",
            "breeding": "养殖技术",
            "general": "通用农技",
        }
    )

    @property
    def collection_name(self) -> str:
        """Chroma collection 名称，随嵌入模型变化而隔离，避免维度冲突。"""
        return f"agri_{self.embedding_provider}_{self.embedding_dim}"

    def ensure_dirs(self) -> None:
        """确保运行期所需目录存在。"""
        for d in (self.corpus_dir, self.chroma_dir, self.records_dir, self.upload_dir):
            d.mkdir(parents=True, exist_ok=True)
        for key in self.categories:
            (self.corpus_dir / key).mkdir(parents=True, exist_ok=True)

    # 可在运行期热更新、无需重启的字段
    RUNTIME_KEYS = ("chunk_size", "chunk_overlap", "top_k", "memory_rounds", "batch_size")

    def update_runtime(self, **kwargs) -> dict:
        """热更新检索/切片参数，返回实际生效的字段。"""
        applied: dict = {}
        for key, value in kwargs.items():
            if key not in self.RUNTIME_KEYS or value is None:
                continue
            try:
                setattr(self, key, int(value))
                applied[key] = int(value)
            except (TypeError, ValueError):
                continue
        return applied


settings = Settings()
