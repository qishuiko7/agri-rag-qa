"""Markdown -> DOCX 转换。

把 docs/软件工程文档.md 渲染为排版规范的 Word 文档：
- 封面页（标题 / 版本 / 日期）
- 分级标题、正文首行缩进、表格样式、代码块底纹
- 中文字体统一为微软雅黑 / 宋体

用法：python scripts/md2docx.py [输入.md] [输出.docx]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor, Cm

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SRC = ROOT / "docs" / "软件工程文档.md"
DEFAULT_OUT = ROOT / "docs" / "农业智能问答助手-软件工程文档.docx"

GREEN = RGBColor(0x1F, 0x6B, 0x3F)
DARK = RGBColor(0x1C, 0x2A, 0x22)
GREY = RGBColor(0x5F, 0x6F, 0x66)


def set_font(run, name: str = "微软雅黑", size: float | None = None,
             bold: bool | None = None, color: RGBColor | None = None) -> None:
    """设置中西文字体，避免中文回退成默认字体。"""
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color


def shade(element, hex_color: str) -> None:
    """给段落或单元格加底纹。"""
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    element.get_or_add_tcPr().append(shd) if hasattr(element, "get_or_add_tcPr") else \
        element.get_or_add_pPr().append(shd)


def add_bottom_border(paragraph, color: str = "1F6B3F", size: int = 8) -> None:
    """段落底部横线，用于章节标题。"""
    p_pr = paragraph._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), str(size))
    bottom.set(qn("w:space"), "4")
    bottom.set(qn("w:color"), color)
    borders.append(bottom)
    p_pr.append(borders)


def build_cover(doc: Document, title: str) -> None:
    """封面页。"""
    for _ in range(6):
        doc.add_paragraph()

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_font(p.add_run(title), size=28, bold=True, color=GREEN)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(12)
    set_font(p.add_run("项目计划书 · 需求规格说明书 · 概要设计说明书"), size=12, color=GREY)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_font(p.add_run("测试用例 · 测试报告 · 用户使用手册"), size=12, color=GREY)

    for _ in range(8):
        doc.add_paragraph()

    for line in ("文档版本：V1.0", "编写日期：2026 年 10 月", "项目性质：高校软件工程综合实习"):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(6)
        set_font(p.add_run(line), size=11, color=GREY)

    doc.add_page_break()


def add_heading(doc: Document, text: str, level: int) -> None:
    """分级标题。"""
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_before = Pt(18 if level == 1 else 12)
    pf.space_after = Pt(8)
    pf.keep_with_next = True

    if level == 1:
        set_font(p.add_run(text), size=18, bold=True, color=GREEN)
        add_bottom_border(p)
    elif level == 2:
        set_font(p.add_run(text), size=14.5, bold=True, color=DARK)
    else:
        set_font(p.add_run(text), size=12.5, bold=True, color=DARK)

    # 让导航窗格能识别标题层级
    p.style = doc.styles[f"Heading {min(level, 9)}"]


def add_para(doc: Document, text: str, indent: bool = True) -> None:
    """正文段落，支持 **粗体** 与 `行内代码`。"""
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
    pf.space_after = Pt(6)
    if indent:
        pf.first_line_indent = Cm(0.74)

    # 拆分粗体与行内代码
    tokens = re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", text)
    for tok in tokens:
        if not tok:
            continue
        if tok.startswith("**") and tok.endswith("**"):
            set_font(p.add_run(tok[2:-2]), size=10.5, bold=True)
        elif tok.startswith("`") and tok.endswith("`"):
            r = p.add_run(tok[1:-1])
            set_font(r, name="Consolas", size=9.5, color=RGBColor(0x8B, 0x2E, 0x2E))
        else:
            set_font(p.add_run(tok), size=10.5)


def add_bullet(doc: Document, text: str, ordered: bool = False) -> None:
    """列表项。"""
    p = doc.add_paragraph(style="List Number" if ordered else "List Bullet")
    pf = p.paragraph_format
    pf.space_after = Pt(3)
    pf.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE

    tokens = re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", text)
    for tok in tokens:
        if not tok:
            continue
        if tok.startswith("**") and tok.endswith("**"):
            set_font(p.add_run(tok[2:-2]), size=10.5, bold=True)
        elif tok.startswith("`") and tok.endswith("`"):
            set_font(p.add_run(tok[1:-1]), name="Consolas", size=9.5)
        else:
            set_font(p.add_run(tok), size=10.5)


def add_code_block(doc: Document, lines: list[str]) -> None:
    """代码块：等宽字体 + 浅灰底纹。"""
    for line in lines:
        p = doc.add_paragraph()
        pf = p.paragraph_format
        pf.space_after = Pt(0)
        pf.space_before = Pt(0)
        pf.left_indent = Cm(0.6)
        pf.line_spacing = 1.15
        shade(p._p, "F5F7F5")
        set_font(p.add_run(line or " "), name="Consolas", size=9)

    # 代码块后留白
    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_after = Pt(4)


def add_table(doc: Document, rows: list[list[str]]) -> None:
    """表格：首行为表头，带底纹与边框。"""
    if not rows:
        return
    cols = max(len(r) for r in rows)
    table = doc.add_table(rows=len(rows), cols=cols)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    for i, row in enumerate(rows):
        for j in range(cols):
            cell = table.cell(i, j)
            text = row[j] if j < len(row) else ""
            text = text.replace("**", "").replace("`", "")
            cell.text = ""
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(2)
            p.paragraph_format.space_before = Pt(2)
            set_font(p.add_run(text), size=9.5, bold=(i == 0),
                     color=RGBColor(0xFF, 0xFF, 0xFF) if i == 0 else None)
            if i == 0:
                shade(cell._tc, "2F7D4F")

    doc.add_paragraph().paragraph_format.space_after = Pt(4)


def parse_table_block(lines: list[str]) -> list[list[str]]:
    """解析 Markdown 表格。"""
    rows = []
    for line in lines:
        if re.match(r"^\|[\s\-:|]+\|$", line.strip()):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        rows.append(cells)
    return rows


def convert(src: Path, out: Path) -> None:
    text = src.read_text(encoding="utf-8")
    lines = text.split("\n")

    doc = Document()

    # 页面设置：A4 + 合理页边距
    section = doc.sections[0]
    section.page_width = Cm(21)
    section.page_height = Cm(29.7)
    section.left_margin = Cm(2.8)
    section.right_margin = Cm(2.8)
    section.top_margin = Cm(2.5)
    section.bottom_margin = Cm(2.5)

    # 默认样式
    normal = doc.styles["Normal"]
    normal.font.name = "微软雅黑"
    normal.font.size = Pt(10.5)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")

    build_cover(doc, "农业智能问答助手")

    # 封面已包含标题与版本信息，正文从「第一部分」开始，避免重复
    start = next(
        (k for k, l in enumerate(lines) if l.strip().startswith("# 第一部分")), 0
    )
    i = start
    n = len(lines)
    while i < n:
        line = lines[i].rstrip()

        # 空行
        if not line.strip():
            i += 1
            continue

        # 代码块
        if line.strip().startswith("```"):
            i += 1
            code_lines = []
            while i < n and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i].rstrip())
                i += 1
            i += 1
            add_code_block(doc, code_lines)
            continue

        # 表格
        if line.strip().startswith("|") and i + 1 < n and re.match(r"^\|[\s\-:|]+\|$", lines[i + 1].strip()):
            table_lines = []
            while i < n and lines[i].strip().startswith("|"):
                table_lines.append(lines[i])
                i += 1
            add_table(doc, parse_table_block(table_lines))
            continue

        # 标题
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            title = m.group(2).strip()
            if title.startswith("第") and "部分" in title:
                doc.add_page_break()
                add_heading(doc, title, 1)
            else:
                add_heading(doc, title, min(level, 3))
            i += 1
            continue

        # 分隔线
        if re.match(r"^-{3,}$", line.strip()):
            p = doc.add_paragraph()
            add_bottom_border(p, color="C8D5CD", size=6)
            i += 1
            continue

        # 引用
        if line.strip().startswith(">"):
            p = doc.add_paragraph()
            pf = p.paragraph_format
            pf.left_indent = Cm(0.8)
            pf.space_after = Pt(4)
            set_font(p.add_run(line.strip().lstrip("> ")), size=9.5, color=GREY)
            i += 1
            continue

        # 有序 / 无序列表
        m = re.match(r"^\s*[-*+]\s+(.*)$", line)
        if m:
            add_bullet(doc, m.group(1))
            i += 1
            continue
        m = re.match(r"^\s*\d+[.)]\s+(.*)$", line)
        if m:
            add_bullet(doc, m.group(1), ordered=True)
            i += 1
            continue

        # 普通段落
        add_para(doc, line.strip())
        i += 1

    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out))
    print(f"已生成：{out}")
    print(f"段落数：{len(doc.paragraphs)}  表格数：{len(doc.tables)}")


if __name__ == "__main__":
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SRC
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUT
    convert(src, out)
