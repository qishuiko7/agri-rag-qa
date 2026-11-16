"""核心模块自测脚本。

不依赖大模型与向量库，直接验证纯逻辑模块的正确性：
清洗、切片、领域拦截、会话记忆、记录持久化、工具计算。

用法：python scripts/selftest.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from langchain_core.documents import Document  # noqa: E402

from app.core import cleaner, guard, splitter  # noqa: E402

PASS, FAIL = 0, 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


def test_cleaner() -> None:
    print("\n【1】语料清洗")
    raw = """
    扫码关注我们的公众号，获取更多资讯！

    小麦越冬水应在日均温 3~5℃ 时浇灌，夜冻昼消为宜。

    小麦越冬水应在日均温 3~5℃ 时浇灌，夜冻昼消为宜。

    主办单位：某某农业局
    """
    out = cleaner.clean_text(raw)
    check("过滤广告行", "扫码关注" not in out)
    check("过滤导航行", "主办单位" not in out)
    check("去除重复行", out.count("小麦越冬水") == 1, f"实际出现 {out.count('小麦越冬水')} 次")
    check("保留正文", "夜冻昼消" in out)

    check("低质量判定：过短", cleaner.is_low_quality("太短了", min_chars=100))
    check("低质量判定：正常文本", not cleaner.is_low_quality(
        "小麦越冬水应在日均温三到五摄氏度时浇灌，夜冻昼消为宜，墒情不足的地块应提前造墒。" * 3
    ))


def test_splitter() -> None:
    print("\n【2】文本切片")
    text = "小麦越冬水管理要点。" * 60
    docs = [Document(page_content=text, metadata={"source": "test.txt", "category": "planting"})]
    chunks = splitter.split_documents(docs, chunk_size=500, chunk_overlap=50)

    check("产生多个切片", len(chunks) > 1, f"实际 {len(chunks)} 个")
    check("切片不超长", all(len(c.page_content) <= 560 for c in chunks),
          f"最长 {max(len(c.page_content) for c in chunks)}")
    check("保留元数据", all(c.metadata.get("category") == "planting" for c in chunks))
    check("带 chunk_index", all("chunk_index" in c.metadata for c in chunks))
    check("无空切片", all(c.page_content.strip() for c in chunks))


def test_guard() -> None:
    print("\n【3】领域拦截")
    cases = [
        ("小麦越冬水什么时候浇", True),
        ("番茄叶片发黄怎么办", True),
        ("母猪产后不吃食怎么处理", True),
        ("帮我写一段 Python 爬虫代码", False),
        ("今天股票行情怎么样", False),
        ("推荐几部好看的电影", False),
        ("你好", True),
        ("", False),
    ]
    for q, expect in cases:
        v = guard.check_question(q)
        check(f"「{q[:16]}」-> {'放行' if expect else '拦截'}",
              v.allowed == expect, f"实际 {'放行' if v.allowed else '拦截'}（{v.reason}）")


def test_memory() -> None:
    print("\n【4】多轮会话记忆")
    from app.core.memory import MemoryStore

    store = MemoryStore(max_sessions=3)
    s1 = store.create("sess-a")
    store.append("sess-a", "问题1", "回答1")
    store.append("sess-a", "问题2", "回答2")
    store.append("sess-a", "问题3", "回答3")

    s = store.get("sess-a")
    check("会话创建", s is not None)
    check("轮次累计", len(s.turns) == 3, f"实际 {len(s.turns)}")

    msgs = s.history_messages(2)
    check("记忆截断为最近 2 轮", len(msgs) == 4, f"实际 {len(msgs)} 条消息")
    check("记忆顺序正确", msgs[0]["content"] == "问题2" and msgs[-1]["content"] == "回答3")

    check("清空会话", store.clear("sess-a") and len(store.get("sess-a").turns) == 0)

    # 会话隔离
    store.append("sess-b", "另一个问题", "另一个回答")
    check("会话隔离", len(store.get("sess-a").turns) == 0 and len(store.get("sess-b").turns) == 1)

    # 会话数上限淘汰
    for i in range(5):
        store.create(f"tmp-{i}")
        store.append(f"tmp-{i}", "q", "a")
    check("超出上限自动淘汰", len(store.list_sessions()) <= 3,
          f"实际 {len(store.list_sessions())} 个")


def test_history() -> None:
    print("\n【5】对话记录持久化")
    from app.config import settings

    # 用临时目录，避免污染真实记录
    original = settings.records_dir
    tmp = Path(tempfile.mkdtemp())
    settings.records_dir = tmp
    try:
        from app.core import history

        r1 = history.add(session_id="s1", question="小麦怎么施肥", answer="分基肥和追肥",
                         latency_ms=1200, sources=[{"title": "小麦施肥", "category": "种植技术"}])
        r2 = history.add(session_id="s2", question="番茄叶子黄了", answer="可能缺氮",
                         latency_ms=800, blocked=False)
        history.add(session_id="s3", question="写代码", answer="已拦截", latency_ms=10, blocked=True)

        res = history.query()
        check("写入 3 条", res["total"] == 3, f"实际 {res['total']}")

        res = history.query(keyword="施肥")
        check("关键词检索", res["total"] == 1 and "小麦" in res["items"][0]["question"])

        st = history.stats()
        check("统计总数", st["total"] == 3)
        check("统计拦截数", st["blocked"] == 1)
        check("统计平均耗时", st["avg_latency_ms"] == round((1200 + 800 + 10) / 3),
              f"实际 {st['avg_latency_ms']}")

        csv_text = history.export_csv()
        check("CSV 导出含表头", "问题" in csv_text and "回答" in csv_text)
        check("CSV 行数正确", len(csv_text.strip().split("\n")) == 4)

        removed = history.delete([r1["id"]])
        check("按 id 删除", removed == 1 and history.query()["total"] == 2)

        history.clear_all()
        check("清空全部", history.query()["total"] == 0)
    finally:
        settings.records_dir = original


def test_tools() -> None:
    print("\n【6】Agent 工具计算")
    from app.agent.tools import registry
    import app.agent.tools  # noqa: F401  触发注册

    check("工具注册数量", len(registry.all()) >= 6, f"实际 {len(registry.all())} 个")

    # 施肥计算
    r = registry.get("calc_fertilizer").run({"crop": "小麦", "target_yield": 500, "soil_level": "中"})
    check("施肥计算成功", r.get("ok") is True)
    urea = r.get("product_equivalent_kg", {}).get("尿素(46%N)", 0)
    check("尿素量在合理区间", 10 < urea < 60, f"实际 {urea} 公斤/亩")

    # 农药稀释
    r = registry.get("calc_dilution").run({"water_liters": 15, "dilution_ratio": 1000})
    check("稀释计算", r.get("ok") is True and abs(r["dose_ml_or_g"] - 15) < 0.1,
          f"实际 {r.get('dose_ml_or_g')} 毫升")

    # ppm 法
    r = registry.get("calc_dilution").run(
        {"water_liters": 15, "target_ppm": 100, "product_percent": 10}
    )
    check("ppm 计算", r.get("ok") is True and abs(r["dose_ml_or_g"] - 15) < 0.1,
          f"实际 {r.get('dose_ml_or_g')} 克")

    # 农事日历
    r = registry.get("crop_calendar").run({"crop": "小麦", "month": 12})
    check("农事日历", r.get("ok") is True and len(r.get("tasks", [])) > 0)

    # 症状初诊
    r = registry.get("diagnose_symptom").run({"symptoms": "番茄下部叶片发黄，叶背有白色小虫"})
    check("症状初诊命中", r.get("ok") is True and r.get("matched", 0) > 0)

    # 未知作物
    r = registry.get("calc_fertilizer").run({"crop": "榴莲", "target_yield": 100})
    check("未知作物给出明确错误", r.get("ok") is False and "暂未收录" in str(r.get("error", "")))


def main() -> None:
    print("=" * 56)
    print("农业智能问答助手 · 核心模块自测")
    print("=" * 56)

    test_cleaner()
    test_splitter()
    test_guard()
    test_memory()
    test_history()
    test_tools()

    print("\n" + "=" * 56)
    print(f"结果：通过 {PASS} 项，失败 {FAIL} 项")
    print("=" * 56)
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
