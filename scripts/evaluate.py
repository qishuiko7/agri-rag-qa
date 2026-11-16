"""RAG 系统量化评测。

把「准确率」拆成三个可独立度量的指标，分别对应链路上的三个环节：

1. 检索命中率  —— 给定问题，标准答案所在文档是否出现在 top-k 里（Recall@k / MRR）
2. 回答要点覆盖 —— 生成内容是否包含人工标注的关键要点（要点覆盖率）
3. 领域拦截准确率 —— 农业问题是否放行、非农问题是否拦截（准确率 / 精确率 / 召回率）

测试集为人工构造：问题用农户口吻，不照抄文档标题；期望文档与要点由语料实际内容确定。

用法：
    python scripts/evaluate.py                # 全量评测
    python scripts/evaluate.py --skip-answer  # 只跑检索与拦截（快，不消耗生成额度）
    python scripts/evaluate.py --json out.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

BASE = "http://127.0.0.1:8000"

# ============================================================
# 检索评测集：25 题，覆盖四类语料
#   expect —— 标题包含任一关键词即算命中（多篇同类文档时给多个关键词）
#   points —— 回答应包含的要点，用于回答质量评测
# ============================================================
RETRIEVAL_CASES = [
    # ---------- 种植技术 ----------
    {"id": "R01", "cat": "种植", "q": "小麦返青拔节期什么时候追肥，施多少",
     "expect": ["冬小麦春季田间管理"], "points": ["返青", "拔节", "追肥"]},
    {"id": "R02", "cat": "种植", "q": "冬油菜秸秆还田要注意哪些问题",
     "expect": ["冬油菜秸秆科学还田"], "points": ["秸秆", "还田"]},
    {"id": "R03", "cat": "种植", "q": "茶园夏天高温干旱该怎么管理",
     "expect": ["茶园防灾减灾"], "points": ["高温", "干旱"]},
    {"id": "R04", "cat": "种植", "q": "小麦播种深度多少合适，播量怎么定",
     "expect": ["小麦秋冬种"], "points": ["播种深度", "播量"]},
    {"id": "R05", "cat": "种植", "q": "夏玉米怎么提高单产",
     "expect": ["夏玉米单产提升"], "points": ["密度", "施肥"]},
    {"id": "R06", "cat": "种植", "q": "马铃薯科学施肥怎么施",
     "expect": ["马铃薯"], "points": ["施肥"]},
    {"id": "R07", "cat": "种植", "q": "冬天设施蔬菜怎么保温防冻",
     "expect": ["设施蔬菜冬季生产"], "points": ["保温", "防冻"]},
    {"id": "R08", "cat": "种植", "q": "果树遇到持续雨雪天气怎么办",
     "expect": ["果树茶叶应对持续雨雪"], "points": ["雨雪"]},
    {"id": "R09", "cat": "种植", "q": "小麦越冬水什么时候浇合适",
     "expect": ["小麦秋冬种", "冬前管理"], "points": ["越冬水"]},
    {"id": "R10", "cat": "种植", "q": "玉米什么时候追肥效果最好",
     "expect": ["玉米"], "points": ["追肥"]},

    # ---------- 病虫害防治 ----------
    {"id": "R11", "cat": "病虫害", "q": "小麦条锈病怎么防控",
     "expect": ["条锈病"], "points": ["条锈病"]},
    {"id": "R12", "cat": "病虫害", "q": "水稻稻飞虱用什么药防治",
     "expect": ["水稻重大病虫害"], "points": ["稻飞虱"]},
    {"id": "R13", "cat": "病虫害", "q": "小麦赤霉病什么时候打药",
     "expect": ["小麦春季重大病虫害"], "points": ["赤霉病"]},
    {"id": "R14", "cat": "病虫害", "q": "大豆玉米带状复合种植怎么除草",
     "expect": ["带状复合种植除草剂"], "points": ["除草"]},
    {"id": "R15", "cat": "病虫害", "q": "玉米螟怎么防治",
     "expect": ["玉米"], "points": ["玉米螟"]},
    {"id": "R16", "cat": "病虫害", "q": "除草剂打多了出现药害怎么补救",
     "expect": ["除草剂"], "points": ["药害"]},
    {"id": "R17", "cat": "病虫害", "q": "地下害虫蛴螬怎么防治",
     "expect": ["地下害虫", "蛴螬", "病虫"], "points": ["蛴螬"]},
    {"id": "R18", "cat": "病虫害", "q": "大棚蔬菜灰霉病怎么治",
     "expect": ["灰霉", "设施蔬菜"], "points": ["灰霉"]},

    # ---------- 养殖技术 ----------
    {"id": "R19", "cat": "养殖", "q": "养猪要注意哪些关键理念",
     "expect": ["养猪必须"], "points": ["养猪"]},
    {"id": "R20", "cat": "养殖", "q": "肉牛养殖怎么降低成本提高效益",
     "expect": ["肉牛养殖降本"], "points": ["肉牛", "成本"]},
    {"id": "R21", "cat": "养殖", "q": "斑点叉尾鮰亲鱼怎么分期培育",
     "expect": ["斑点叉尾鮰"], "points": ["亲鱼"]},
    {"id": "R22", "cat": "养殖", "q": "秋收秸秆怎么做成饲料喂牛羊",
     "expect": ["秸秆饲料化"], "points": ["秸秆", "饲料"]},

    # ---------- 通用农技 ----------
    {"id": "R23", "cat": "通用", "q": "秋粮遇到灾害怎么减灾保丰收",
     "expect": ["科学防灾减灾"], "points": ["防灾", "减灾"]},
    {"id": "R24", "cat": "通用", "q": "智慧农业在实际生产中有哪些应用",
     "expect": ["智慧农业"], "points": ["智慧农业"]},
    {"id": "R25", "cat": "通用", "q": "小麦冬前怎么管理才能培育壮苗",
     "expect": ["冬前管理", "小麦秋冬种", "冬小麦春季田间管理"], "points": ["冬前", "壮苗"]},
]

# 回答质量评测：从上面抽 10 题（覆盖四类），实际调生成接口
ANSWER_IDS = ["R01", "R04", "R09", "R11", "R13", "R18", "R19", "R20", "R22", "R23"]

# ============================================================
# 领域拦截评测集：正样本 15 个（农业，应放行）+ 负样本 15 个（非农，应拦截）
# ============================================================
GUARD_POSITIVE = [
    "小麦返青后什么时候追肥",
    "番茄叶子发黄卷曲是什么原因",
    "玉米螟用什么药防治效果好",
    "母猪产后不吃食怎么办",
    "大棚蔬菜冬天怎么保温",
    "水稻插秧后水层怎么管理",
    "果树修剪的最佳时间是什么时候",
    "茶园夏季高温怎么管理",
    "马铃薯薯块变绿了还能吃吗",
    "肉牛育肥期饲料怎么配",
    "土壤板结怎么改良",
    "小麦条锈病怎么识别",
    "蛋鸡产蛋率下降是什么原因",
    "秸秆还田要注意什么",
    "农药安全间隔期是多久",
]

GUARD_NEGATIVE = [
    "帮我写一段 Python 爬虫代码",
    "今天股票行情怎么样",
    "推荐几部好看的电影",
    "北京到上海的高铁要多久",
    "如何学习机器学习算法",
    "我的电脑开不了机怎么办",
    "给我讲个笑话",
    "比特币现在多少钱",
    "怎么写一份简历",
    "世界杯冠军是谁",
    "怎么减肥最快",
    "手机电池不耐用怎么修",
    "明天天气适合爬山吗",
    "帮我翻译一段英文",
    "这个数学题怎么解",
]


def _post(path: str, **kw) -> dict:
    r = requests.post(f"{BASE}{path}", timeout=kw.pop("timeout", 120), **kw)
    r.raise_for_status()
    return r.json()


def _get(path: str, **kw) -> dict:
    r = requests.get(f"{BASE}{path}", timeout=kw.pop("timeout", 60), **kw)
    r.raise_for_status()
    return r.json()


# ============================================================
# 1. 检索命中率
# ============================================================
def eval_retrieval(k: int = 5) -> dict:
    print(f"\n{'='*62}")
    print(f"【1】检索命中率（top-{k}）")
    print(f"{'='*62}")
    print("  口径：召回文档的标题包含期望关键词即算命中（严格，不认可类文档替代）")

    hits_at = {1: 0, 3: 0, k: 0}
    rr_sum = 0.0
    details = []
    misses = []

    for case in RETRIEVAL_CASES:
        try:
            res = _post("/api/vector/search", params={"q": case["q"], "k": k})
            hits = res.get("hits", [])
        except Exception as exc:  # noqa: BLE001
            print(f"  [{case['id']}] 检索失败：{exc}")
            details.append({**case, "hit_rank": None, "error": str(exc)})
            continue

        titles = [h.get("title", "") for h in hits]
        rank = None
        for i, title in enumerate(titles, 1):
            if any(kw in title for kw in case["expect"]):
                rank = i
                break

        if rank:
            rr_sum += 1.0 / rank
            for kk in hits_at:
                if rank <= kk:
                    hits_at[kk] += 1

        details.append({**case, "hit_rank": rank, "top_titles": titles[:3]})

        if rank:
            print(f"  [{case['id']}] ✓ 第{rank}位  {case['q'][:30]}")
        else:
            print(f"  [{case['id']}] ✗ 未命中   {case['q'][:30]}")
            print(f"        实际召回：{titles[0][:42] if titles else '（空）'}")
            misses.append({
                "id": case["id"],
                "question": case["q"],
                "expected": case["expect"],
                "got": titles[:3],
            })

    total = len(RETRIEVAL_CASES)
    result = {
        "total": total,
        "recall@1": round(hits_at[1] / total * 100, 1),
        "recall@3": round(hits_at[3] / total * 100, 1),
        f"recall@{k}": round(hits_at[k] / total * 100, 1),
        "mrr": round(rr_sum / total, 3),
        "misses": misses,
        "details": details,
    }
    print(f"\n  Recall@1 = {result['recall@1']}%  Recall@3 = {result['recall@3']}%  "
          f"Recall@{k} = {result[f'recall@{k}']}%  MRR = {result['mrr']}")
    return result


# ============================================================
# 2. 回答要点覆盖
# ============================================================
def eval_answer() -> dict:
    print(f"\n{'='*62}")
    print(f"【2】回答要点覆盖（{len(ANSWER_IDS)} 题）")
    print(f"{'='*62}")

    cases = [c for c in RETRIEVAL_CASES if c["id"] in ANSWER_IDS]
    details = []
    total_cov = 0.0
    src_hit = 0
    latencies = []

    for case in cases:
        t0 = time.perf_counter()
        try:
            res = _post("/api/chat/ask", json={
                "question": case["q"],
                "session_id": f"eval-{case['id']}",
            })
        except Exception as exc:  # noqa: BLE001
            print(f"  [{case['id']}] 生成失败：{exc}")
            details.append({**case, "coverage": 0, "covered": [], "error": str(exc)})
            continue
        latency = int((time.perf_counter() - t0) * 1000)
        latencies.append(latency)

        answer = res.get("answer", "")
        covered = [p for p in case["points"] if p in answer]
        cov = len(covered) / len(case["points"]) if case["points"] else 0
        total_cov += cov

        # 来源是否包含期望文档（回答有没有建立在正确资料上）
        src_titles = [s.get("title", "") for s in res.get("sources", [])]
        has_src = any(any(kw in t for kw in case["expect"]) for t in src_titles)
        if has_src:
            src_hit += 1

        details.append({
            **case,
            "coverage": round(cov, 2),
            "covered": covered,
            "missing": [p for p in case["points"] if p not in answer],
            "answer_len": len(answer),
            "latency_ms": latency,
            "sources_ok": has_src,
            "answer_preview": answer[:160],
        })

        print(f"  [{case['id']}] 要点 {len(covered)}/{len(case['points'])} "
              f"({'/'.join(covered) or '无'}) · 来源{'✓' if has_src else '✗'} · {latency}ms")

    n = len(cases)
    result = {
        "total": n,
        "coverage_avg": round(total_cov / n * 100, 1) if n else 0,
        "full_coverage": sum(1 for d in details if d.get("coverage") == 1.0),
        "sources_correct": src_hit,
        "avg_latency_ms": round(sum(latencies) / len(latencies)) if latencies else 0,
        "details": details,
    }
    print(f"\n  平均要点覆盖率 = {result['coverage_avg']}%  "
          f"要点全覆盖 = {result['full_coverage']}/{n}  "
          f"来源正确 = {src_hit}/{n}")
    return result


# ============================================================
# 3. 领域拦截准确率
# ============================================================
def eval_guard() -> dict:
    print(f"\n{'='*62}")
    print("【3】领域拦截准确率")
    print(f"{'='*62}")

    tp = tn = fp = fn = 0
    errors = []

    for q in GUARD_POSITIVE:
        v = _get("/api/chat/guard", params={"q": q})
        if v["allowed"]:
            tp += 1
        else:
            fn += 1
            errors.append(("误拦", q, v["reason"]))

    for q in GUARD_NEGATIVE:
        v = _get("/api/chat/guard", params={"q": q})
        if not v["allowed"]:
            tn += 1
        else:
            fp += 1
            errors.append(("漏放", q, v["reason"]))

    total = tp + tn + fp + fn
    acc = (tp + tn) / total * 100 if total else 0
    precision = tp / (tp + fp) * 100 if (tp + fp) else 0
    recall = tp / (tp + fn) * 100 if (tp + fn) else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0

    print(f"  农业问题放行 {tp}/{len(GUARD_POSITIVE)} · 非农问题拦截 {tn}/{len(GUARD_NEGATIVE)}")
    if errors:
        for kind, q, reason in errors:
            print(f"    {kind}：{q}（{reason}）")
    else:
        print("    无错判")

    result = {
        "total": total,
        "tp": tp, "tn": tn, "fp": fp, "fn": fn,
        "accuracy": round(acc, 1),
        "precision": round(precision, 1),
        "recall": round(recall, 1),
        "f1": round(f1, 1),
        "errors": [{"type": k, "question": q, "reason": r} for k, q, r in errors],
    }
    print(f"\n  准确率 = {acc:.1f}%  精确率 = {precision:.1f}%  "
          f"召回率 = {recall:.1f}%  F1 = {f1:.1f}%")
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-answer", action="store_true", help="跳过生成评测（不消耗模型额度）")
    ap.add_argument("--json", default="", help="结果写入 JSON 文件")
    args = ap.parse_args()

    print("=" * 62)
    print("RAG 系统量化评测")
    print(f"时间：{datetime.now():%Y-%m-%d %H:%M:%S}")
    print("=" * 62)

    try:
        st = _get("/api/chat/status")
        print(f"模式：{st['mode']} · {st['llm_model']} + {st['embedding_model']}")
        print(f"知识库：{st['vector_chunks']} 片段 · top_k={st['top_k']}")
    except Exception as exc:  # noqa: BLE001
        print(f"服务不可用：{exc}")
        sys.exit(1)

    report = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "retrieval": eval_retrieval(5),
        "guard": eval_guard(),
    }
    if not args.skip_answer:
        report["answer"] = eval_answer()

    print(f"\n{'='*62}")
    print("汇总")
    print(f"{'='*62}")
    r = report["retrieval"]
    g = report["guard"]
    print(f"  检索命中率        Recall@1 {r['recall@1']}% · Recall@3 {r['recall@3']}% · "
          f"Recall@5 {r['recall@5']}% · MRR {r['mrr']}")
    print(f"  拦截准确率        {g['accuracy']}%（精确率 {g['precision']}% · "
          f"召回率 {g['recall']}% · F1 {g['f1']}%）")
    if "answer" in report:
        a = report["answer"]
        print(f"  回答要点覆盖 {a['coverage_avg']}%（全覆盖 {a['full_coverage']}/{a['total']}）")

    if args.json:
        Path(args.json).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n  详细结果已写入：{args.json}")


if __name__ == "__main__":
    main()
