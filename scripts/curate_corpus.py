"""语料后处理：新闻过滤 + 重新分类 + 统计报告。

抓取阶段按「标题关键词首次命中」分类，粒度较粗，且会混入新闻报道类内容。
本脚本做三件事：
1. 剔除新闻/活动报道类文本（标题特征词 + 正文新闻标记）；
2. 按关键词在全文中的出现频次重新归类，比首次命中更准确；
3. 输出分布报告，便于判断语料是否均衡。

用法：
    python scripts/curate_corpus.py            # 干跑，只报告不移动
    python scripts/curate_corpus.py --apply    # 实际执行移动
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from app.config import settings  # noqa: E402

# ---------- 新闻类特征 ----------
NEWS_TITLE_PATTERNS = [
    "喜迎", "庆祝", "开幕", "闭幕", "举行", "举办", "召开", "现场会", "观摩会",
    "调研", "座谈", "签约", "启动仪式", "开镰", "丰收节", "丰收季",
    "侧记", "纪实", "专访", "访谈", "通讯", "见闻", "剪影",
    "荣获", "获奖", "表彰", "揭牌", "挂牌", "奠基", "竣工",
    "培训班", "宣讲", "主题党日", "党建", "党史",
]

NEWS_BODY_MARKERS = ["本报讯", "记者", "通讯员", "摄", "本网记者", "融媒体"]

# ---------- 分类词表（按命中次数竞争）----------
CATEGORY_WORDS = {
    "pest": [
        "病虫", "病害", "虫害", "防治", "防控", "农药", "杀虫", "杀菌", "除草",
        "杀菌剂", "杀虫剂", "除草剂", "疫病", "检疫", "测报", "统防统治",
        "稻瘟", "纹枯", "赤霉", "锈病", "白粉", "霜霉", "枯萎", "青枯", "根腐",
        "蚜虫", "飞虱", "螟虫", "玉米螟", "棉铃虫", "红蜘蛛", "蓟马", "粉虱",
        "地老虎", "蛴螬", "线虫", "鼠害", "螺", "螨",
    ],
    "breeding": [
        "养殖", "饲养", "畜禽", "生猪", "母猪", "仔猪", "育肥猪", "肉牛", "奶牛",
        "犊牛", "肉羊", "奶羊", "山羊", "绵羊", "蛋鸡", "肉鸡", "鸡舍", "孵化",
        "育雏", "肉鸭", "蛋鸭", "肉鹅", "兔", "鸽", "水产", "鱼塘", "池塘",
        "养鱼", "草鱼", "鲤鱼", "鲫鱼", "罗非鱼", "对虾", "小龙虾", "河蟹",
        "贝类", "海参", "饲料", "饲草", "青贮", "兽药", "疫苗", "防疫",
        "免疫", "消毒", "非洲猪瘟", "口蹄疫", "禽流感", "布病", "养蜂", "养蚕",
        "圈舍", "栏舍", "牧场", "屠宰", "畜产品", "生鲜乳",
    ],
    "planting": [
        "种植", "栽培", "播种", "施肥", "灌溉", "田间", "育苗", "定植", "移栽",
        "水稻", "小麦", "玉米", "大豆", "油菜", "马铃薯", "棉花", "花生",
        "蔬菜", "果树", "茶园", "茶园", "高粱", "谷子", "杂粮", "薯类",
        "品种", "耕作", "秋收", "春耕", "三夏", "三秋", "墒情", "地膜",
        "大棚", "温室", "设施农业", "中耕", "除草", "整地", "收获",
        "有机肥", "化肥", "氮肥", "磷肥", "钾肥", "复合肥", "水肥",
    ],
}


def read_head(path: Path, n: int = 40) -> tuple[str, str]:
    """读取标题与正文（前 n 行作为头部）。"""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return path.stem, ""

    title = path.stem
    lines = text.split("\n")
    for line in lines[:6]:
        if line.startswith("标题："):
            title = line[3:].strip()
            break
    return title, text


def is_news(title: str, body: str) -> tuple[bool, str]:
    """判断是否为新闻/活动报道。"""
    for kw in NEWS_TITLE_PATTERNS:
        if kw in title:
            return True, f"标题含新闻词「{kw}」"

    # 正文前 300 字出现多个新闻标记
    head = body[:300]
    hits = sum(1 for m in NEWS_BODY_MARKERS if m in head)
    if hits >= 2:
        return True, f"正文含 {hits} 个新闻标记"

    # 标题很短且正文很短，多为简讯
    if len(body) < 400:
        return True, "正文过短（<400 字），信息量不足"

    return False, ""


def classify_by_frequency(text: str) -> str:
    """按关键词出现频次归类，取最高分。

    pest 词表最长且「病虫害」在种植类文章里也常被顺带提及，
    因此对 pest 分数降权，避免「秸秆还田」这类文本被误判为病虫害防治。
    """
    scores: Counter = Counter()
    for cat, words in CATEGORY_WORDS.items():
        score = sum(text.count(w) for w in words)
        if cat == "pest":
            score *= 0.6
        scores[cat] = score

    if not scores:
        return "general"

    best, score = scores.most_common(1)[0]
    if score < 3:
        return "general"
    return best


# 标题强信号：标题命中即定类，优先于正文频次
TITLE_SIGNALS = {
    "pest": ["病虫", "病害", "虫害", "防治", "防控", "农药", "除草", "检疫", "疫情", "疫病防治"],
    "breeding": ["养殖", "饲养", "畜禽", "生猪", "母猪", "仔猪", "水产", "饲料", "兽医", "牧场"],
    "planting": ["种植", "栽培", "播种", "施肥", "还田", "田间", "育苗", "耕作", "收获", "品种"],
}


def classify(title: str, body: str) -> str:
    """先看标题强信号，再用正文频次兜底。"""
    for cat, words in TITLE_SIGNALS.items():
        if any(w in title for w in words):
            return cat
    return classify_by_frequency(body)


# 只匹配空格与制表符；若用 \s 会把段落换行一起吞掉
_CJK_SPACE = re.compile(r"(?<=[\u4e00-\u9fa5])[ \t\u3000]+(?=[\u4e00-\u9fa5])")


def normalize_spaces(path: Path, text: str) -> str:
    """去除中文之间的多余空格（网页提取噪声），原地重写文件。"""
    fixed = _CJK_SPACE.sub("", text)
    if fixed != text:
        path.write_text(fixed, encoding="utf-8")
    return fixed


def clean_name(name: str) -> str:
    """清理文件名：去掉前导序号、特殊符号。"""
    stem = re.sub(r"^[\+\-\d]+[\.\、\s]+", "", name)
    stem = re.sub(r'[\\/:*?"<>|]', "", stem)
    return stem.strip() or name


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="实际移动文件")
    args = ap.parse_args()

    settings.ensure_dirs()
    corpus = settings.corpus_dir
    rejected_dir = settings.data_dir / "corpus_rejected"

    files = [p for p in corpus.rglob("*.txt") if p.is_file()]
    print(f"扫描到 {len(files)} 个语料文件\n")

    kept = 0
    rejected = 0
    moved = 0
    before: Counter = Counter()
    after: Counter = Counter()
    reject_reasons: Counter = Counter()

    for path in files:
        before[path.parent.name] += 1
        title, body = read_head(path)

        news, reason = is_news(title, body)
        if news:
            rejected += 1
            reject_reasons[reason] += 1
            if args.apply:
                rejected_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), str(rejected_dir / path.name))
            continue

        kept += 1
        if args.apply:
            body = normalize_spaces(path, body)

        new_cat = classify(title, body)
        after[new_cat] += 1

        if new_cat != path.parent.name and args.apply:
            target = corpus / new_cat
            target.mkdir(parents=True, exist_ok=True)
            dest = target / path.name
            if dest.exists():
                dest = target / f"{path.stem}_{new_cat}.txt"
            shutil.move(str(path), str(dest))
            moved += 1

    print("=" * 52)
    print(f"保留 {kept} 篇，剔除 {rejected} 篇")
    if reject_reasons:
        print("\n剔除原因：")
        for r, c in reject_reasons.most_common():
            print(f"  {r}: {c} 篇")
    print(f"\n分类前后对比：")
    print(f"  调整前：{dict(before)}")
    print(f"  调整后：{dict(after)}")
    if args.apply:
        print(f"\n实际移动文件 {moved} 个")
    else:
        print("\n（干跑模式，未改动文件。加 --apply 执行）")

    report = {
        "total_scanned": len(files),
        "kept": kept,
        "rejected": rejected,
        "reject_reasons": dict(reject_reasons),
        "before": dict(before),
        "after": dict(after),
        "moved": moved if args.apply else 0,
    }
    (settings.data_dir / "curate_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
