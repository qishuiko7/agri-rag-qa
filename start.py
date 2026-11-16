"""一键启动脚本。

用法：
    python start.py            # 启动服务（默认 127.0.0.1:8000）
    python start.py --reload   # 开发模式，代码热重载
    python start.py --port 8080

启动前会自检：虚拟环境、依赖、前端构建产物、模型配置。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
DIST = ROOT / "frontend" / "dist"

BANNER = r"""
  ___   ____ ____ ___     ___  ____ ____
 / _ \ / ___|  _ \_ _|   / _ \/ ___|  _ \
| |_| | |  _| |_) | |   | | | \___ \ |_) |
|  _  | |_| |  _ <| |   | |_| |___) |  _ <
|_| |_|\____|_| \_\___|   \__\_\____/|_| \_\
"""


def check_env() -> list[str]:
    """启动前自检，返回告警列表（不阻断启动）。"""
    warns: list[str] = []

    if not (ROOT / ".env").exists():
        warns.append("未找到 .env，已回退到 mock 模式（复制 .env.example 可自定义）")

    try:
        import fastapi  # noqa: F401
        import langchain  # noqa: F401
        import chromadb  # noqa: F401
    except ImportError as exc:
        warns.append(f"依赖缺失：{exc}。请先执行 pip install -r backend/requirements.txt")

    if not DIST.exists():
        warns.append("前端尚未构建，访问首页会看到构建提示（cd frontend && npm install && npm run build）")

    corpus = BACKEND / "data" / "corpus"
    exts = {".txt", ".md", ".pdf", ".csv"}
    n = sum(1 for p in corpus.rglob("*") if p.is_file() and p.suffix.lower() in exts) \
        if corpus.exists() else 0
    if n == 0:
        warns.append("语料目录为空，请先导入农业语料或运行 scripts/crawl_corpus.py")

    return warns


def main() -> None:
    ap = argparse.ArgumentParser(description="农业智能问答助手启动器")
    ap.add_argument("--host", default=os.getenv("HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    ap.add_argument("--reload", action="store_true", help="开发模式热重载")
    args = ap.parse_args()

    print(BANNER)
    warns = check_env()
    if warns:
        print("启动前提示：")
        for w in warns:
            print(f"  ! {w}")
        print()

    # 让 backend 成为可导入的根
    os.chdir(BACKEND)
    sys.path.insert(0, str(BACKEND))

    import uvicorn

    print(f"服务地址： http://{args.host}:{args.port}")
    print(f"接口文档： http://{args.host}:{args.port}/docs")
    print("按 Ctrl+C 停止\n")

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
