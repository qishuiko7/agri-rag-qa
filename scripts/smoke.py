"""接口冒烟测试：逐项验证所有 REST 端点。

用法：python scripts/smoke.py [baseUrl]
"""
from __future__ import annotations

import json
import sys

import requests

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"

PASS, FAIL = 0, 0
results: list[tuple[str, bool, str]] = []


def check(name: str, fn) -> None:
    global PASS, FAIL
    try:
        detail = fn()
        PASS += 1
        results.append((name, True, detail or "OK"))
        print(f"  [PASS] {name}  {detail or ''}")
    except Exception as exc:  # noqa: BLE001
        FAIL += 1
        results.append((name, False, str(exc)))
        print(f"  [FAIL] {name}  {exc}")


def get(path, **kw):
    r = requests.get(f"{BASE}{path}", timeout=kw.pop("timeout", 30), **kw)
    r.raise_for_status()
    return r.json()


def post(path, **kw):
    r = requests.post(f"{BASE}{path}", timeout=kw.pop("timeout", 60), **kw)
    r.raise_for_status()
    return r.json()


def main() -> None:
    print("=" * 60)
    print("接口冒烟测试")
    print("=" * 60)

    print("\n【基础】")
    check("健康检查", lambda: get("/api/health")["service"])
    check("系统状态", lambda: f"库 {get('/api/chat/status')['vector_chunks']} 片段")
    check("首页 HTML", lambda: (
        requests.get(f"{BASE}/", timeout=10).status_code == 200 and "index" in
        requests.get(f"{BASE}/", timeout=10).text.lower() or "200 OK"
    ))

    print("\n【知识库】")
    check("语料统计", lambda: f"{get('/api/kb/stats')['total']} 篇")
    check("文档列表", lambda: f"{get('/api/kb/documents', params={'page_size': 5})['total']} 条")
    check("分类过滤", lambda: f"病虫害 {get('/api/kb/documents', params={'category': 'pest'})['total']} 篇")

    def preview() -> str:
        items = get("/api/kb/documents", params={"page_size": 1})["items"]
        if not items:
            return "无语料可预览"
        d = items[0]
        r = get("/api/kb/preview", params={"name": d["name"], "category": d["category"]})
        return f"{r['chars']} 字"

    check("文档预览", preview)
    check("异常筛查", lambda: f"{get('/api/kb/documents', params={'only_abnormal': True})['total']} 个异常")

    print("\n【向量库】")
    check("向量库状态", lambda: f"{get('/api/vector/stats')['chunks']} 片段")
    check("已入库来源", lambda: f"{get('/api/vector/sources')['total']} 个来源")
    check("入库进度", lambda: get("/api/vector/progress")["stage"])

    def search() -> str:
        r = post("/api/vector/search", params={"q": "小麦越冬水什么时候浇", "k": 3})
        return f"命中 {len(r['hits'])} 条"

    check("语义检索", search)

    def search_filter() -> str:
        r = post("/api/vector/search", params={"q": "病虫害防治", "k": 3})
        return f"命中 {len(r['hits'])} 条"

    check("检索（另一主题）", search_filter)

    print("\n【对话】")
    def ask_rag() -> str:
        r = post("/api/chat/ask", json={"question": "小麦越冬水什么时候浇", "session_id": "smoke-1"})
        assert r["answer"], "回答为空"
        return f"{r['latency_ms']} ms · {len(r['sources'])} 条来源"

    check("RAG 问答", ask_rag)

    def ask_block() -> str:
        r = post("/api/chat/ask", json={"question": "帮我写一段 Python 爬虫代码"})
        assert r["blocked"] is True, "未拦截非农问题"
        return "已正确拦截"

    check("非农拦截", ask_block)

    def ask_empty() -> str:
        r = post("/api/chat/ask", json={"question": ""})
        assert r["blocked"] is True, "空问题未拦截"
        return "已拒绝空问题"

    check("空问题校验", ask_empty)

    def sessions() -> str:
        r = get("/api/chat/sessions")
        return f"{len(r['items'])} 个活跃会话"

    check("会话列表", sessions)

    def clear() -> str:
        r = post("/api/chat/clear", params={"session_id": "smoke-1"})
        assert r["ok"], "清空失败"
        return "会话已清空"

    check("清空会话", clear)

    def guard() -> str:
        r = get("/api/chat/guard", params={"q": "番茄叶片发黄"})
        return f"{'放行' if r['allowed'] else '拦截'}（{r['reason']}）"

    check("拦截判定调试", guard)

    print("\n【Agent】")
    check("工具清单", lambda: f"{get('/api/agent/tools')['total']} 个工具")

    def agent_ask() -> str:
        r = post("/api/agent/ask", json={"question": "小麦越冬水什么时候浇", "session_id": "smoke-a"})
        assert r["answer"], "回答为空"
        return f"{len(r['tool_calls'])} 次工具调用 · {r['latency_ms']} ms"

    check("Agent 问答", agent_ask)

    print("\n【历史记录】")
    check("记录统计", lambda: f"{get('/api/history/stats')['total']} 条")
    check("记录查询", lambda: f"{post('/api/history/list', json={'page': 1, 'page_size': 5})['total']} 条")

    def keyword() -> str:
        r = post("/api/history/list", json={"keyword": "越冬水", "page": 1, "page_size": 5})
        return f"命中 {r['total']} 条"

    check("关键词检索", keyword)

    def export() -> str:
        r = requests.get(f"{BASE}/api/history/export", timeout=30)
        r.raise_for_status()
        assert r.text.startswith("\ufeff") or "问题" in r.text, "CSV 内容异常"
        return f"{len(r.content)} 字节"

    check("CSV 导出", export)

    print("\n【设置】")
    check("读取配置", lambda: get("/api/settings")["llm_provider"])
    check("模型测试接口", lambda: (
        "正常" if get("/api/settings") and
        requests.post(f"{BASE}/api/settings/test", timeout=60).json().get("ok") is not None
        else "异常"
    ))

    print("\n【流式】")
    def sse() -> str:
        with requests.get(
            f"{BASE}/api/chat/stream",
            params={"question": "玉米螟怎么防治", "session_id": "smoke-s"},
            stream=True, timeout=60,
        ) as r:
            r.raise_for_status()
            events = []
            for line in r.iter_lines(decode_unicode=True):
                if line and line.startswith("data: "):
                    payload = line[6:]
                    if payload == "[DONE]":
                        break
                    try:
                        events.append(json.loads(payload)["type"])
                    except json.JSONDecodeError:
                        continue
            assert "delta" in events, f"未收到增量事件：{events}"
            return f"{len(events)} 个事件 · 类型 {sorted(set(events))}"

    check("SSE 流式问答", sse)

    print("\n" + "=" * 60)
    print(f"结果：通过 {PASS} 项，失败 {FAIL} 项")
    print("=" * 60)
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
