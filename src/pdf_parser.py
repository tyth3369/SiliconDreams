"""
SiliconDreams — PDF 双引擎解析器
================================
- PyMuPDF4LLM (主力): PDF → Markdown（表格结构完整保留）
- pdfplumber (辅助): 复杂表格 → DataFrame → Markdown 表格
- 输出: ParsedDocument { text_chunks, table_chunks, metadata }
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════


@dataclass
class TableBlock:
    """单个表格块"""

    markdown: str  # Markdown 格式的表格
    page: int  # 页码 (1-indexed)
    bbox: tuple  # 表格在页面中的位置 (x0, y0, x1, y1)
    rows: int = 0  # 行数
    cols: int = 0  # 列数
    raw_df: pd.DataFrame | None = None  # 原始 DataFrame（pdfplumber 提取）


@dataclass
class ParsedDocument:
    """PDF 解析结果"""

    filename: str  # 文件名
    total_pages: int  # 总页数
    full_markdown: str  # 完整 Markdown 文本
    text_sections: list[dict] = field(default_factory=list)  # [{text, page, section}]
    tables: list[TableBlock] = field(default_factory=list)  # 提取出的表格
    metadata: dict = field(default_factory=dict)  # {author, title, date, ...}
    parse_errors: list[str] = field(default_factory=list)  # 解析中的错误/警告


# ═══════════════════════════════════════════════════
# 引擎 1: PyMuPDF4LLM (主力)
# ═══════════════════════════════════════════════════


def parse_with_pymupdf4llm(
    filepath: str | Path, original_filename: str | None = None
) -> ParsedDocument:
    """
    使用 PyMuPDF4LLM 将 PDF 转为 Markdown。
    表格结构由 pymupdf4llm 自动识别并保留为 Markdown 表格格式。

    Args:
        filepath: PDF 文件路径

    Returns:
        ParsedDocument 对象
    """
    import fitz  # pymupdf
    import pymupdf4llm

    filepath = Path(filepath)
    display_name = original_filename or filepath.name
    logger.info("[PyMuPDF4LLM] 开始解析: %s", display_name)

    # 获取 PDF 基本信息
    doc = fitz.open(str(filepath))
    total_pages = doc.page_count
    metadata = {
        "title": doc.metadata.get("title", ""),
        "author": doc.metadata.get("author", ""),
        "subject": doc.metadata.get("subject", ""),
        "date": doc.metadata.get("creationDate", ""),
    }
    doc.close()

    # PyMuPDF4LLM 转换
    try:
        # write_images=False: 不提取图片，减小输出体积
        page_chunks = pymupdf4llm.to_markdown(
            str(filepath),
            write_images=False,
            table_strategy="lines_strict",
            page_chunks=True,
            show_progress=False,
        )
    except Exception as e:
        logger.error(f"PyMuPDF4LLM 解析失败: {e}")
        return ParsedDocument(
            filename=display_name,
            total_pages=total_pages,
            full_markdown="",
            metadata=metadata,
            parse_errors=[str(e)],
        )

    text_sections = []
    tables = []
    page_texts = []
    for index, page_chunk in enumerate(page_chunks, 1):
        page = int(page_chunk.get("metadata", {}).get("page", index))
        page_text = str(page_chunk.get("text", ""))
        page_texts.append(f"<!-- page {page} -->\n{page_text}")
        text_sections.extend(_split_page_sections(page_text, page))
        tables.extend(_extract_tables_from_markdown(page_text, page=page))

    full_markdown = "\n\n".join(page_texts)

    logger.info(
        f"[PyMuPDF4LLM] 解析完成: "
        f"{total_pages} 页, {len(full_markdown)} 字符, "
        f"{len(tables)} 个表格, {len(text_sections)} 个文本段"
    )

    return ParsedDocument(
        filename=display_name,
        total_pages=total_pages,
        full_markdown=full_markdown,
        text_sections=text_sections,
        tables=tables,
        metadata=metadata,
    )


# ═══════════════════════════════════════════════════
# 引擎 2: pdfplumber (辅助, 复杂表格)
# ═══════════════════════════════════════════════════


def extract_tables_with_pdfplumber(
    filepath: str | Path,
    pages: list[int] | None = None,
) -> list[TableBlock]:
    """
    使用 pdfplumber 提取复杂表格（返回 DataFrame）。
    用于 PyMuPDF4LLM 无法处理的嵌套/无边框表格。

    Args:
        filepath: PDF 文件路径
        pages: 指定页码列表（1-indexed），None = 全部页

    Returns:
        TableBlock 列表（含 raw_df）
    """
    import pdfplumber

    filepath = Path(filepath)
    logger.info(f"[pdfplumber] 开始提取表格: {filepath.name}")

    tables = []
    with pdfplumber.open(str(filepath)) as pdf:
        target_pages = pages or range(1, len(pdf.pages) + 1)

        for page_num in target_pages:
            page = pdf.pages[page_num - 1]
            extracted = page.extract_tables()

            for _idx, table_data in enumerate(extracted):
                if not table_data or len(table_data) < 2:
                    continue  # 空表或只有表头

                # 清理：移除全空行
                table_data = [
                    row for row in table_data if any(cell and str(cell).strip() for cell in row)
                ]
                if len(table_data) < 2:
                    continue

                # DataFrame
                try:
                    df = pd.DataFrame(table_data[1:], columns=table_data[0])
                    df = df.dropna(how="all")
                except Exception:
                    df = pd.DataFrame(table_data)

                # 转 Markdown
                markdown_table = (
                    df.to_markdown(index=False) if hasattr(df, "to_markdown") else _df_to_md(df)
                )

                tables.append(
                    TableBlock(
                        markdown=markdown_table,
                        page=page_num,
                        bbox=(0, 0, page.width, page.height),
                        rows=len(df),
                        cols=len(df.columns),
                        raw_df=df,
                    )
                )

    logger.info(f"[pdfplumber] 提取完成: {len(tables)} 个表格")
    return tables


# ═══════════════════════════════════════════════════
# 双引擎协调
# ═══════════════════════════════════════════════════


def parse_pdf(filepath: str | Path, original_filename: str | None = None) -> ParsedDocument:
    """
    双引擎 PDF 解析。

    策略:
    1. 主力: PyMuPDF4LLM 快速转换（含表格）
    2. 辅助: 对 PyMuPDF4LLM 解析失败的页，用 pdfplumber 重试
    3. 合并结果

    Args:
        filepath: PDF 文件路径

    Returns:
        ParsedDocument（含双引擎最优结果）
    """
    filepath = Path(filepath)

    if not filepath.exists():
        raise FileNotFoundError(f"PDF 文件不存在: {filepath}")

    # Step 1: PyMuPDF4LLM 主力解析
    doc = parse_with_pymupdf4llm(filepath, original_filename=original_filename)

    # Step 2: 检查表格质量 → 决定是否启用 pdfplumber
    tables_need_fix = _check_table_quality(doc.tables)

    if tables_need_fix:
        logger.info("部分表格格式异常，启用 pdfplumber 辅助引擎...")
        try:
            pdfplumber_tables = extract_tables_with_pdfplumber(filepath)
            doc.tables = _merge_tables(doc.tables, pdfplumber_tables)
            logger.info(f"双引擎合并完成: {len(doc.tables)} 个表格")
        except Exception as e:
            logger.warning(f"pdfplumber 辅助引擎失败: {e}")
            doc.parse_errors.append(f"pdfplumber: {e}")

    return doc


# ═══════════════════════════════════════════════════
# 内部辅助函数
# ═══════════════════════════════════════════════════


def _extract_tables_from_markdown(md_text: str, page: int) -> list[TableBlock]:
    """从 Markdown 文本中提取所有表格块"""
    import re

    tables = []

    # 匹配 Markdown 表格: 包含 |---|---| 分隔行的块
    pattern = r"(\|.+\|\n\|[-| :]+\|\n(?:\|.+\|\n?)+)"
    matches = re.finditer(pattern, md_text)

    for _idx, match in enumerate(matches):
        table_md = match.group(1).strip()
        # 计算行数和列数
        lines = table_md.split("\n")
        header_cols = len(lines[0].split("|")) - 2  # 去掉首尾空列
        data_rows = len(lines) - 2  # 去掉表头和分隔行

        tables.append(
            TableBlock(
                markdown=table_md,
                page=page,
                bbox=(0, 0, 0, 0),
                rows=data_rows,
                cols=header_cols,
            )
        )

    return tables


def _split_page_sections(md_text: str, page: int) -> list[dict]:
    """Split one page by Markdown headings while preserving its exact page number."""
    import re

    sections = []

    # 按 ## 或 # 标题分割
    pattern = r"^(#{1,3}\s+.+)$"
    parts = re.split(pattern, md_text, flags=re.MULTILINE)

    current_section = "正文"
    current_text = ""

    for part in parts:
        if re.match(pattern, part):
            if current_text.strip():
                sections.append(
                    {
                        "text": current_text.strip(),
                        "section": current_section,
                        "page": page,
                    }
                )
            current_section = part.strip("# ").strip()
            current_text = ""
        else:
            current_text += part + "\n"

    if current_text.strip():
        sections.append(
            {
                "text": current_text.strip(),
                "section": current_section,
                "page": page,
            }
        )

    return sections


def _check_table_quality(tables: list[TableBlock]) -> bool:
    """
    检查表格质量：
    - 列数 < 2 或 行数 < 1 → 需要修复
    - 包含异常字符（如大量连续空格） → 需要修复
    """
    if not tables:
        return False

    bad_count = 0
    for t in tables:
        if t.cols < 2 or t.rows < 1:
            bad_count += 1
    return bad_count > len(tables) * 0.3  # 超过30%异常 → 触发辅助引擎


def _merge_tables(
    primary: list[TableBlock],
    secondary: list[TableBlock],
) -> list[TableBlock]:
    """
    合并两套表格结果：
    - pdfplumber 表格覆盖同页 PyMuPDF4LLM 异常表格
    """
    # 简单策略：保留 primary，替换同页异常项
    # （更复杂的对齐逻辑留到后续迭代）
    merged = []

    for t in primary:
        if t.cols < 2 and t.page > 0:
            # 尝试从 secondary 找同页替代
            replacement = next(
                (s for s in secondary if abs(s.page - t.page) <= 1 and s.cols >= t.cols),
                None,
            )
            if replacement:
                merged.append(replacement)
                continue
        merged.append(t)

    # 添加 secondary 中独有的表格
    primary_pages = {t.page for t in primary}
    for s in secondary:
        if s.page not in primary_pages:
            merged.append(s)

    return merged


def _df_to_md(df: pd.DataFrame) -> str:
    """DataFrame → 简易 Markdown 表格"""
    lines = []
    # 表头
    lines.append("| " + " | ".join(str(c) for c in df.columns) + " |")
    # 分隔行
    lines.append("| " + " | ".join("---" for _ in df.columns) + " |")
    # 数据行
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(str(v) for v in row.values) + " |")
    return "\n".join(lines)
