"""性能基准测试。

测量启动后的检索延迟、问答延迟与进程内存占用，输出可直接填入测试报告的数据。

用法：python scripts/bench.py [baseUrl]
"""
from __future__ import annotations

import json
import statistics
import subprocess
import sys
import time
from urllib.parse import urlencode

import requests

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"

QUERIES = [
    "小麦越冬水什么时候浇",
    "玉米螟怎么防治",
    "番茄叶片发黄是什么原因",
    "大棚蔬菜如何防冻",
    "水稻纹枯病用什么药",
    "马铃薯晚疫病防治",
    "大豆什么时候播种",
    "油菜冬季管理要点",
    "果树修剪最佳时间",
    "土壤板结怎么改良",
]


def bench_search(n: int = 20) -> dict:
    """检索延迟。"""
    lat = []
    for i in range(n):
        q = QUERIES[i % len(QUERIES)]
        t0 = time.perf_counter()
        r = requests.post(f"{BASE}/api/vector/search", params={"q": q, "k": 5}, timeout=30)
        r.raise_for_status()
        lat.append((time.perf_counter() - t0) * 1000)
        time.sleep(0.05)

    return {
        "count": n,
        "avg_ms": round(statistics.mean(lat), 1),
        "p50_ms": round(statistics.median(lat), 1),
        "p95_ms": round(sorted(lat)[int(len(lat) * 0.95) - 1], 1),
        "max_ms": round(max(lat), 1),
        "min_ms": round(min(lat), 1),
    }


def bench_ask(n: int = 5) -> dict:
    """完整问答链路延迟（含检索 + 生成）。"""
    lat = []
    for i in range(n):
        q = QUERIES[i % len(QUERIES)]
        t0 = time.perf_counter()
        r = requests.post(
            f"{BASE}/api/chat/ask",
            json={"question": q, "session_id": f"bench-{i}"},
            timeout=120,
        )
        r.raise_for_status()
        lat.append((time.perf_counter() - t0) * 1000)

    return {
        "count": n,
        "avg_ms": round(statistics.mean(lat), 1),
        "max_ms": round(max(lat), 1),
        "min_ms": round(min(lat), 1),
    }


def bench_agent(n: int = 3) -> dict:
    """Agent 链路延迟。"""
    lat = []
    for i in range(n):
        q = QUERIES[i % len(QUERIES)]
        t0 = time.perf_counter()
        r = requests.post(
            f"{BASE}/api/agent/ask",
            json={"question": q, "session_id": f"bench-a-{i}"},
            timeout=180,
        )
        r.raise_for_status()
        lat.append((time.perf_counter() - t0) * 1000)

    return {
        "count": n,
        "avg_ms": round(statistics.mean(lat), 1),
        "max_ms": round(max(lat), 1),
    }


def process_memory() -> dict:
    """查找 python 进程的内存占用。"""
    try:
        if sys.platform == "win32":
            import csv
            import io

            out = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=10,
            ).stdout
            total = 0.0
            count = 0
            for row in csv.reader(io.StringIO(out)):
                if len(row) < 5:
                    continue
                mem = row[-1].replace("K", "").replace(",", "").replace(" ", "").strip()
                if mem.isdigit():
                    total += int(mem) / 1024
                    count += 1
            return {"processes": count, "total_mb": round(total, 1)}

        out = subprocess.run(["ps", "-o", "rss=", "-C", "python"], capture_output=True, text=True).stdout
        vals = [int(x) for x in out.split() if x.isdigit()]
        return {"processes": len(vals), "total_mb": round(sum(vals) / 1024, 1)}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def store_stats() -> dict:
    try:
        return requests.get(f"{BASE}/api/vector/stats", timeout=10).json()
    except Exception:  # noqa: BLE001
        return {}


def main() -> None:
    print("=" * 56)
    print("性能基准测试")
    print("=" * 56)

    # 服务可用性
    t0 = time.perf_counter()
    try:
        requests.get(f"{BASE}/api/health", timeout=10).raise_for_status()
    except Exception as exc:  # noqa: BLE001
        print(f"服务不可用：{exc}")
        sys.exit(1)
    print(f"健康检查耗时：{(time.perf_counter() - t0) * 1000:.0f} ms\n")

    st = store_stats()
    print(f"向量库：{st.get('chunks', 0)} 片段 · {st.get('size_mb', 0)} MB · "
          f"{st.get('embedding_provider')} / {st.get('embedding_model')}\n")

    print("检索延迟（20 次）…")
    s = bench_search(20)
    print(f"  平均 {s['avg_ms']} ms · P50 {s['p50_ms']} ms · P95 {s['p95_ms']} ms · "
          f"范围 {s['min_ms']}~{s['max_ms']} ms\n")

    print("问答链路（5 次）…")
    a = bench_ask(5)
    print(f"  平均 {a['avg_ms']} ms · 范围 {a['min_ms']}~{a['max_ms']} ms\n")

    print("Agent 链路（3 次）…")
    g = bench_agent(3)
    print(f"  平均 {g['avg_ms']} ms · 最大 {g['max_ms']} ms\n")

    mem = process_memory()
    print(f"Python 进程内存：{mem.get('total_mb', 'N/A')} MB（{mem.get('processes', 0)} 个进程）\n")

    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "vector_store": st,
        "search": s,
        "ask": a,
        "agent": g,
        "memory": mem,
    }
    print("=" * 56)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
