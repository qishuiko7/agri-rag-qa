"""FastAPI 应用入口。

启动方式：
    uvicorn app.main:app --host 127.0.0.1 --port 8000
或直接运行项目根目录的 start.py / start.bat。
"""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.config import PROJECT_DIR, settings

# ---------- 日志：仅保留错误级，减少磁盘写入（对齐文档「日志精简」）----------
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

DIST_DIR = PROJECT_DIR / "frontend" / "dist"


def _prewarm_kb_cache() -> None:
    """后台预热知识库清单缓存。

    首次扫描 598 个文件需 1~2 秒，放在后台线程里做，
    用户打开知识库页时就能直接命中缓存，不必等待。
    """
    try:
        from app.api.kb import _all_docs

        items = _all_docs()
        logger.warning("知识库缓存预热完成：%d 个文档", len(items))
    except Exception as exc:  # noqa: BLE001
        logger.warning("知识库缓存预热失败：%s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    threading.Thread(target=_prewarm_kb_cache, daemon=True, name="kb-prewarm").start()
    logger.warning("服务启动：语料目录 %s", settings.corpus_dir)
    yield
    logger.warning("服务关闭")


app = FastAPI(
    title="农业智能问答助手",
    description="基于 LangChain RAG 的农业垂直领域问答系统，支持升级为 Agent 模式",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- 路由注册 ----------
from app.api import chat, history, kb, settings as settings_api, vector  # noqa: E402

app.include_router(chat.router)
app.include_router(kb.router)
app.include_router(vector.router)
app.include_router(history.router)
app.include_router(settings_api.router)

# Agent 路由在模块就绪后注册，缺失时不影响 RAG 主链路
try:
    from app.api import agent as agent_api  # noqa: E402

    app.include_router(agent_api.router)
except Exception as exc:  # noqa: BLE001
    logger.warning("Agent 模块未启用：%s", exc)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "service": "agri-rag-qa", "version": app.version}


# ---------- 前端静态资源 ----------
if DIST_DIR.exists():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        """SPA 兜底：非 API 路径统一返回 index.html，交给前端路由处理。"""
        if full_path.startswith("api/"):
            return HTMLResponse("Not Found", status_code=404)
        candidate = DIST_DIR / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(DIST_DIR / "index.html")
else:
    @app.get("/")
    def placeholder() -> HTMLResponse:
        return HTMLResponse(
            """
            <html><head><meta charset="utf-8"><title>农业智能问答助手</title></head>
            <body style="font-family:system-ui;padding:48px;max-width:720px;margin:auto;line-height:1.8">
            <h2>后端已启动，但前端尚未构建</h2>
            <p>请在 <code>frontend</code> 目录执行：</p>
            <pre style="background:#f5f5f5;padding:16px;border-radius:8px">npm install
npm run build</pre>
            <p>构建完成后刷新本页即可。API 文档见
            <a href="/docs">/docs</a>。</p>
            </body></html>
            """
        )
