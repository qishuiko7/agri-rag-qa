"""农业语料抓取与清洗脚本。

数据来源：中国农业农村信息网（www.agri.cn）公开农技栏目。
覆盖栏目：农事指导、科技推广、农业气象、生产动态、智慧农业、科技成果。

流程：栏目翻页 -> 收集文章链接 -> 逐篇抓正文 -> 清洗去噪 -> 关键词分类 -> 落盘 txt。

用法：
    python scripts/crawl_corpus.py            # 全量抓取
    python scripts/crawl_corpus.py --limit 50 # 每栏目最多 50 篇，用于快速验证
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# 允许脚本直接运行（不经包安装）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from app.config import settings  # noqa: E402

BASE = "http://www.agri.cn"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# (栏目路径, 栏目中文名, 最多翻页数)
# 只保留农技知识密度高的栏目；专项监测为空页、农业气象是天气预报，
# 后者会污染知识库（用户问天气时召回历史预报），故不纳入。
COLUMNS = [
    ("/sc/nszd/", "农事指导", 25),
    ("/sc/scdt/", "生产动态", 25),
    ("/xxh/zhny/", "智慧农业", 25),
]

# ---------- 分类关键词（按优先级匹配，先命中先归类）----------
CATEGORY_RULES = [
    ("pest", ["病虫", "虫害", "病害", "防控", "防治", "农药", "杀虫", "杀菌",
              "疫病", "蝗虫", "螟", "蚜", "锈病", "赤霉", "稻瘟", "除草", "草害"]),
    ("breeding", ["养殖", "饲养", "畜禽", "生猪", "肉牛", "奶牛", "羊", "蛋鸡",
                  "家禽", "水产", "鱼塘", "饲料", "兽医", "屠宰", "蜂", "蚕"]),
    ("planting", ["种植", "栽培", "播种", "施肥", "灌溉", "田间", "育苗", "定植",
                  "水稻", "小麦", "玉米", "大豆", "油菜", "蔬菜", "果树", "茶园",
                  "马铃薯", "棉花", "花生", "高粱", "杂粮", "品种", "耕作", "秋收"]),
]

# 正文容器候选 class（不同栏目模板略有差异）
CONTENT_SELECTORS = ["div.content", "div.TRS_Editor", "div.article", "div#content", "div.zoom"]

# 页脚/导航噪声行特征
NOISE_PATTERNS = [
    r"^时间[：:]", r"^来源[：:]", r"^作者[：:]", r"^字体[：:]", r"^打印", r"^关闭",
    r"^分享到", r"^扫一扫", r"^上一篇", r"^下一篇", r"^相关链接", r"^责任编辑",
    r"^中华人民共和国.*部$", r"^国家.*委员会$", r"^国务院.*办公室$",
    r"^中国.*网$", r"^版权所有", r"^京ICP", r"^网站标识码", r"^关于我们",
    r"^主办单位", r"^技术支持", r"^地址[：:]", r"^邮编[：:]", r"^电话[：:]",
]


@dataclass
class Doc:
    title: str
    url: str
    column: str
    date: str
    category: str
    content: str

    @property
    def chars(self) -> int:
        return len(self.content)


def _get(url: str, retries: int = 3, timeout: int = 20) -> str | None:
    """带重试的 GET，自动识别编码。"""
    for i in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            if not r.encoding or r.encoding.lower() in ("iso-8859-1", "ascii"):
                r.encoding = r.apparent_encoding or "utf-8"
            return r.text
        except Exception:
            if i == retries - 1:
                return None
            time.sleep(1.5 * (i + 1))
    return None


def collect_links(column_path: str, max_pages: int, limit: int = 0) -> list[tuple[str, str]]:
    """翻页收集某栏目下的文章链接，返回 [(标题, 绝对URL)]。

    limit > 0 时，收集到足够数量即停止翻页，避免无谓请求。
    """
    found: dict[str, str] = {}
    for page in range(max_pages):
        if limit and len(found) >= limit:
            break
        # 第一页是 index.htm，后续是 index_1.htm / index_1.html（不同栏目模板不一致）
        if page == 0:
            page_url = urljoin(BASE, column_path)
            html = _get(page_url)
        else:
            html = None
            for ext in ("htm", "html"):
                page_url = urljoin(BASE, f"{column_path}index_{page}.{ext}")
                html = _get(page_url)
                if html:
                    break
        if not html:
            break
        soup = BeautifulSoup(html, "lxml")
        page_hits = 0
        for a in soup.find_all("a", href=True):
            href = a["href"]
            title = a.get_text(strip=True)
            # 只认形如 .../202610/t20261021_8877789.htm(l) 的详情页
            if not re.search(r"/t\d{8}_\d+\.html?$", href):
                continue
            if len(title) < 8:
                continue
            absolute = urljoin(page_url, href)
            if absolute not in found:
                found[absolute] = title
                page_hits += 1
        if page_hits == 0 and page > 0:
            break  # 没有新文章，说明翻到底了
        time.sleep(0.4)
    return [(t, u) for u, t in found.items()]


def extract_content(html: str) -> tuple[str, str]:
    """从详情页提取正文与发布日期。"""
    soup = BeautifulSoup(html, "lxml")

    # 日期
    date = ""
    m = re.search(r"(\d{4})[-年/](\d{1,2})[-月/](\d{1,2})", soup.get_text(" ", strip=True))
    if m:
        date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    node = None
    for sel in CONTENT_SELECTORS:
        node = soup.select_one(sel)
        if node and len(node.get_text(strip=True)) > 100:
            break
        node = None

    if node is None:
        # 兜底：取文字最多的 div
        divs = soup.find_all("div")
        if divs:
            node = max(divs, key=lambda d: len(d.get_text(strip=True)))
        if node is None:
            return "", date

    # 去脚本样式，按段落取文本
    for tag in node.find_all(["script", "style", "iframe"]):
        tag.decompose()

    lines: list[str] = []
    for p in node.find_all(["p", "div", "li", "h1", "h2", "h3", "h4"]):
        # 只取叶子块级节点：父容器会包含全部子文本，若一并提取会导致正文重复一遍
        if p.find(["p", "div", "li"]):
            continue
        txt = p.get_text(" ", strip=True)
        if not txt:
            continue
        if any(re.match(pat, txt) for pat in NOISE_PATTERNS):
            continue
        lines.append(txt)

    if not lines:
        lines = [node.get_text(" ", strip=True)]

    # 去重保序（父子节点会重复同一段文字）
    seen: set[str] = set()
    cleaned: list[str] = []
    for ln in lines:
        key = re.sub(r"\s+", "", ln)
        if key in seen or len(key) < 6:
            continue
        seen.add(key)
        cleaned.append(ln)

    text = "\n".join(cleaned)
    # 去除中文字符间的多余空格（HTML 节点拼接产生），保留换行
    text = re.sub(r"(?<=[\u4e00-\u9fa5])[ \t]+(?=[\u4e00-\u9fa5])", "", text)
    return text, date


def classify(title: str, content: str) -> str:
    """按标题优先、正文兜底的关键词规则分类。"""
    for cat, words in CATEGORY_RULES:
        if any(w in title for w in words):
            return cat
    head = content[:300]
    for cat, words in CATEGORY_RULES:
        if any(w in head for w in words):
            return cat
    return "general"


def safe_filename(title: str, max_len: int = 60) -> str:
    """把标题转成安全的文件名。"""
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', "", title)
    name = re.sub(r"\s+", "_", name.strip())
    return name[:max_len] or "untitled"


def save(doc: Doc) -> Path:
    """落盘为 txt，头部带元信息，便于后续溯源与统计。"""
    out_dir = settings.corpus_dir / doc.category
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{safe_filename(doc.title)}.txt"
    if path.exists():
        path = out_dir / f"{safe_filename(doc.title)}_{hashlib.md5(doc.url.encode()).hexdigest()[:6]}.txt"
    body = (
        f"标题：{doc.title}\n"
        f"栏目：{doc.column}\n"
        f"日期：{doc.date}\n"
        f"来源：{doc.url}\n"
        f"{'-' * 40}\n"
        f"{doc.content}\n"
    )
    path.write_text(body, encoding="utf-8")
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="每栏目最多抓取篇数，0 表示不限")
    ap.add_argument("--workers", type=int, default=4, help="并发抓取线程数，默认 4")
    args = ap.parse_args()

    settings.ensure_dirs()
    all_docs: list[Doc] = []
    seen_hash: set[str] = set()  # 内容级去重
    write_lock = threading.Lock()

    for col_path, col_name, max_pages in COLUMNS:
        print(f"\n>>> 栏目：{col_name} ({col_path})", flush=True)
        links = collect_links(col_path, max_pages, args.limit)
        print(f"    发现 {len(links)} 篇", flush=True)

        ok = skip = 0
        done = 0

        def fetch_one(item: tuple[str, str]) -> Doc | None:
            """抓取并清洗单篇；失败或重复返回 None。"""
            title, url = item
            html = _get(url)
            if not html:
                return None
            content, date = extract_content(html)
            if len(content) < 150:
                return None

            digest = hashlib.md5(re.sub(r"\s+", "", content).encode()).hexdigest()
            with write_lock:
                if digest in seen_hash:
                    return None
                seen_hash.add(digest)

            cat = classify(title, content)
            doc = Doc(title=title, url=url, column=col_name, date=date,
                      category=cat, content=content)
            with write_lock:
                save(doc)
            return doc

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(fetch_one, item): item for item in links}
            for fut in as_completed(futures):
                done += 1
                try:
                    doc = fut.result()
                except Exception:  # noqa: BLE001
                    doc = None
                if doc is None:
                    skip += 1
                else:
                    all_docs.append(doc)
                    ok += 1
                if done % 20 == 0:
                    print(f"    {done}/{len(links)}  已保存 {ok} 篇，跳过 {skip} 篇", flush=True)

        print(f"    完成：保存 {ok} 篇，跳过 {skip} 篇", flush=True)

    # 汇总报告
    settings.ensure_dirs()
    report = {
        "total": len(all_docs),
        "by_category": {},
        "by_column": {},
        "avg_chars": round(sum(d.chars for d in all_docs) / len(all_docs), 1) if all_docs else 0,
    }
    for d in all_docs:
        report["by_category"][d.category] = report["by_category"].get(d.category, 0) + 1
        report["by_column"][d.column] = report["by_column"].get(d.column, 0) + 1

    (settings.data_dir / "corpus_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\n" + "=" * 50)
    print(f"抓取完成，共 {report['total']} 篇，平均 {report['avg_chars']} 字")
    print(f"分类分布：{report['by_category']}")
    print(f"栏目分布：{report['by_column']}")


if __name__ == "__main__":
    main()
