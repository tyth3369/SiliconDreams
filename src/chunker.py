"""
SiliconDreams — 智能分块器
==========================
- 文本块: 语义分块（按 Markdown 标题/段落）, chunk_size=512, overlap=64
- 表格块: 完整保留（一个表格 = 一个 chunk，不切割）
- 元数据: {type, source, page, section, chunk_id}
"""

import re
import hashlib
import logging
from dataclasses import dataclass, field
from typing import Optional

from config import RAGConfig
from src.pdf_parser import ParsedDocument, TableBlock

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════

@dataclass
class Chunk:
    """通用文档块"""
    chunk_id: str                       # 唯一 ID (hash)
    text: str                           # 块内容
    chunk_type: str                     # "text" | "table"
    source: str                         # 来源文件名
    page: int                           # 页码 (1-indexed)
    section: str = ""                   # 章节标题
    metadata: dict = field(default_factory=dict)


# ═══════════════════════════════════════════════════
# 文本分块
# ═══════════════════════════════════════════════════

def chunk_text(
    text: str,
    source: str,
    page: int = 0,
    section: str = "",
    chunk_size: int = RAGConfig.text_chunk_size,
    overlap: int = RAGConfig.text_chunk_overlap,
) -> list[Chunk]:
    """
    将长文本按语义边界分块。
    优先在段落/句子边界处切割，避免切断语义。

    Args:
        text: 输入文本
        source: 来源文件名
        page: 页码
        section: 章节标题
        chunk_size: 块大小（字符数）
        overlap: 块间重叠（字符数）

    Returns:
        Chunk 列表
    """
    if not text.strip():
        return []

    chunks = []
    paragraphs = _split_by_paragraph(text)

    current_chunk = ""
    current_len = 0

    for para in paragraphs:
        para_len = len(para)

        # 如果单个段落超过 chunk_size，按句子强制分割
        if para_len > chunk_size:
            # 先保存当前 chunk
            if current_chunk:
                chunks.append(_make_chunk(current_chunk, source, page, section))
                current_chunk = ""
                current_len = 0

            # 强制按句子切分长段落
            sentences = _split_by_sentence(para)
            for sent in sentences:
                if current_len + len(sent) > chunk_size and current_chunk:
                    chunks.append(_make_chunk(current_chunk, source, page, section))
                    # 重叠：保留最后一个句子
                    last_sent = sentences[sentences.index(sent) - 1] if sentences.index(sent) > 0 else ""
                    current_chunk = last_sent[-overlap:] if overlap > 0 else ""
                    current_len = len(current_chunk)
                current_chunk += sent
                current_len += len(sent)
            continue

        # 正常追加段落
        if current_len + para_len > chunk_size and current_chunk:
            chunks.append(_make_chunk(current_chunk, source, page, section))
            # 重叠策略
            if overlap > 0:
                overlap_start = max(0, current_len - overlap)
                current_chunk = current_chunk[overlap_start:]
                current_len = len(current_chunk)
            else:
                current_chunk = ""
                current_len = 0

        current_chunk += para
        current_len += para_len

    # 保存最后一个 chunk
    if current_chunk.strip():
        chunks.append(_make_chunk(current_chunk, source, page, section))

    logger.debug(f"文本分块: {len(paragraphs)} 段 → {len(chunks)} 块 (source={source}, page={page})")
    return chunks


# ═══════════════════════════════════════════════════
# 表格分块（整体保留）
# ═══════════════════════════════════════════════════

def chunk_tables(
    tables: list[TableBlock],
    source: str,
) -> list[Chunk]:
    """
    将表格转为 Chunk，每个表格 = 一个完整 Chunk（不切割）。

    为提升检索准确性，在表格前添加简短上下文：
    "来自 {source} 第 {page} 页的表格："

    Args:
        tables: TableBlock 列表
        source: 来源文件名

    Returns:
        Chunk 列表 (type="table")
    """
    chunks = []
    for i, table in enumerate(tables):
        # 添加上下文前缀
        prefix = f"[表格 {i+1}] 来源: {source}, 第 {table.page} 页\n"
        full_text = prefix + table.markdown

        chunks.append(Chunk(
            chunk_id=_gen_id(f"{source}_table_{table.page}_{i}"),
            text=full_text,
            chunk_type="table",
            source=source,
            page=table.page,
            section="表格",
            metadata={
                "table_index": i,
                "rows": table.rows,
                "cols": table.cols,
                "bbox": table.bbox,
            },
        ))

    logger.info(f"表格分块: {len(tables)} 个表格 → {len(chunks)} 个 Chunk (source={source})")
    return chunks


# ═══════════════════════════════════════════════════
# 主入口：解析后的文档 → Chunk 列表
# ═══════════════════════════════════════════════════

def chunk_document(doc: ParsedDocument) -> list[Chunk]:
    """
    将 ParsedDocument 转为 Chunk 列表（文本块 + 表格块）。

    Args:
        doc: ParsedDocument 对象

    Returns:
        所有 Chunk 的列表
    """
    all_chunks = []

    # 1. 文本分块
    for section in doc.text_sections:
        text_chunks = chunk_text(
            text=section["text"],
            source=doc.filename,
            page=section.get("page_estimate", 0),
            section=section.get("section", ""),
        )
        all_chunks.extend(text_chunks)

    # 如果 text_sections 为空（解析异常），对整个 full_markdown 分块
    if not doc.text_sections and doc.full_markdown:
        text_chunks = chunk_text(
            text=doc.full_markdown,
            source=doc.filename,
        )
        all_chunks.extend(text_chunks)

    # 2. 表格分块
    table_chunks = chunk_tables(doc.tables, doc.filename)
    all_chunks.extend(table_chunks)

    logger.info(
        f"📦 文档分块完成: {doc.filename} → "
        f"{len(all_chunks)} 个 Chunk "
        f"(文本: {len(all_chunks) - len(table_chunks)}, 表格: {len(table_chunks)})"
    )

    return all_chunks


# ═══════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════

def _split_by_paragraph(text: str) -> list[str]:
    """按段落分割（双换行符或 Markdown 标题）"""
    # 先在 Markdown 标题前断行
    text = re.sub(r'(\n#{1,3}\s)', r'\n\n\1', text)
    # 按双换行分割
    parts = re.split(r'\n\n+', text)
    return [p.strip() for p in parts if p.strip()]


def _split_by_sentence(text: str) -> list[str]:
    """按句子分割（中文句号/问号/感叹号, 英文句点）"""
    # 中英文句子边界
    pattern = r'(?<=[。！？.!?\n])\s*'
    parts = re.split(pattern, text)
    return [p for p in parts if p.strip()]


def _make_chunk(text: str, source: str, page: int, section: str) -> Chunk:
    """创建 Chunk 对象"""
    return Chunk(
        chunk_id=_gen_id(f"{source}_{page}_{section}_{hash(text) & 0xffff}"),
        text=text.strip(),
        chunk_type="text",
        source=source,
        page=page,
        section=section,
        metadata={
            "char_count": len(text),
            "source_file": source,
        },
    )


def _gen_id(seed: str) -> str:
    """生成短唯一 ID"""
    return hashlib.md5(seed.encode()).hexdigest()[:12]
