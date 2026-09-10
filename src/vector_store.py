"""
SiliconDreams — ChromaDB 向量存储管理
======================================
- 本地持久化 (SQLite)
- 双 Collection: text_chunks + table_chunks
- 混合检索: 向量相似度 + 元数据过滤
"""

import logging
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.config import Settings as ChromaSettings

from config import RAGConfig, CHROMA_DIR
from src.chunker import Chunk
from src.embedding_manager import EmbeddingManager

logger = logging.getLogger(__name__)


class VectorStore:
    """
    ChromaDB 向量存储管理器。

    用法:
        store = VectorStore()
        store.add_chunks(chunks)
        results = store.search("台积电毛利率", top_k=5)
        results = store.search_tables("资产负债表", top_k=3)
    """

    def __init__(self, persist_dir: Optional[Path] = None):
        """
        Args:
            persist_dir: ChromaDB 持久化目录，默认 config.CHROMA_DIR
        """
        self.persist_dir = str(persist_dir or CHROMA_DIR)
        Path(self.persist_dir).mkdir(parents=True, exist_ok=True)

        self._client = chromadb.PersistentClient(
            path=self.persist_dir,
            settings=ChromaSettings(anonymized_telemetry=False),
        )

        self._embed_model = EmbeddingManager.get_instance()

        # 获取或创建两个 Collection
        self.text_collection = self._client.get_or_create_collection(
            name=RAGConfig.chroma_collection_text,
            metadata={"description": "财报/研报文本块"},
        )
        self.table_collection = self._client.get_or_create_collection(
            name=RAGConfig.chroma_collection_table,
            metadata={"description": "财报表格块（完整不切割）"},
        )

        logger.info(
            f"📂 ChromaDB 就绪: {self.persist_dir} "
            f"(文本: {self.text_collection.count()}, 表格: {self.table_collection.count()})"
        )

    # ── 添加 Chunk ──────────────────────────────────

    def add_chunks(self, chunks: list[Chunk]) -> int:
        """
        批量添加 Chunk 到对应 Collection。

        Args:
            chunks: Chunk 列表

        Returns:
            实际添加的 Chunk 数量
        """
        if not chunks:
            return 0

        # 分离文本和表格
        text_items = {"ids": [], "documents": [], "metadatas": []}
        table_items = {"ids": [], "documents": [], "metadatas": []}

        for chunk in chunks:
            item = {
                "id": chunk.chunk_id,
                "document": chunk.text,
                "metadata": {
                    "source": chunk.source,
                    "page": chunk.page,
                    "section": chunk.section,
                    "char_count": len(chunk.text),
                    **chunk.metadata,
                },
            }
            if chunk.chunk_type == "table":
                for key in item:
                    table_items[key].append(item[key])
            else:
                for key in item:
                    text_items[key].append(item[key])

        added = 0

        if text_items["ids"]:
            # 批量生成 embedding
            embeddings = self._embed_model.get_embeddings(text_items["documents"])
            self.text_collection.add(
                ids=text_items["ids"],
                documents=text_items["documents"],
                metadatas=text_items["metadatas"],
                embeddings=embeddings,
            )
            added += len(text_items["ids"])
            logger.info(f"📝 文本 Collection: +{len(text_items['ids'])} chunks")

        if table_items["ids"]:
            embeddings = self._embed_model.get_embeddings(table_items["documents"])
            self.table_collection.add(
                ids=table_items["ids"],
                documents=table_items["documents"],
                metadatas=table_items["metadatas"],
                embeddings=embeddings,
            )
            added += len(table_items["ids"])
            logger.info(f"📋 表格 Collection: +{len(table_items['ids'])} chunks")

        return added

    # ── 检索 ────────────────────────────────────────

    def search(
        self,
        query: str,
        top_k: int = RAGConfig.similarity_top_k,
        collection: str = "auto",
    ) -> list[dict]:
        """
        向量相似度检索。

        Args:
            query: 查询文本
            top_k: 返回结果数
            collection: "text" | "table" | "auto" (自动判断)

        Returns:
            [{id, text, metadata, score}, ...]
        """
        query_embedding = self._embed_model.get_embedding(query)

        if collection == "auto":
            # 自动判断：含财务关键词 → 优先表格
            finance_keywords = [
                "营收", "毛利率", "净利", "资产", "负债", "现金流",
                "同比", "环比", "增长率", "比率", "ROE", "EPS",
                "收入", "成本", "费用", "利润", "亏损", "盈利",
            ]
            has_finance = any(kw in query for kw in finance_keywords)
            collection = "table" if has_finance else "text"

        col = self.table_collection if collection == "table" else self.text_collection
        results = col.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )

        return self._format_results(results)

    def search_tables(self, query: str, top_k: int = 5) -> list[dict]:
        """仅在表格 Collection 中检索"""
        return self.search(query, top_k=top_k, collection="table")

    def search_texts(self, query: str, top_k: int = 5) -> list[dict]:
        """仅在文本 Collection 中检索"""
        return self.search(query, top_k=top_k, collection="text")

    def search_hybrid(
        self,
        query: str,
        top_k: int = RAGConfig.similarity_top_k,
    ) -> list[dict]:
        """
        混合检索：从文本和表格两个 Collection 各取 top_k 条 → 合并去重 → 重排序。

        当前实现：简单合并（完整 BM25 + Re-rank 留在 retriever.py 中由 LlamaIndex 完成）。
        """
        text_results = self.search_texts(query, top_k=top_k)
        table_results = self.search_tables(query, top_k=top_k)

        # 合并去重
        seen_ids = set()
        merged = []
        for r in text_results + table_results:
            if r["id"] not in seen_ids:
                seen_ids.add(r["id"])
                merged.append(r)

        # 按 score 降序
        merged.sort(key=lambda x: x.get("score", 0), reverse=True)
        return merged[:top_k]

    # ── 管理 ────────────────────────────────────────

    def get_stats(self) -> dict:
        """获取知识库统计信息"""
        return {
            "doc_count": len(self._list_unique_sources()),
            "text_chunks": self.text_collection.count(),
            "table_chunks": self.table_collection.count(),
        }

    def clear(self):
        """清空所有 Collection（危险操作）"""
        self._client.delete_collection(RAGConfig.chroma_collection_text)
        self._client.delete_collection(RAGConfig.chroma_collection_table)
        self.text_collection = self._client.get_or_create_collection(
            name=RAGConfig.chroma_collection_text,
        )
        self.table_collection = self._client.get_or_create_collection(
            name=RAGConfig.chroma_collection_table,
        )
        logger.warning("⚠️ ChromaDB 已清空所有数据")

    def _list_unique_sources(self) -> list[str]:
        """列出所有已索引的文档（去重）"""
        sources = set()
        for col in [self.text_collection, self.table_collection]:
            if col.count() > 0:
                results = col.get(include=["metadatas"])
                for meta in results.get("metadatas", []):
                    if meta and "source" in meta:
                        sources.add(meta["source"])
        return sorted(sources)

    @staticmethod
    def _format_results(raw: dict) -> list[dict]:
        """将 ChromaDB 返回格式化为统一结构"""
        results = []
        ids = raw.get("ids", [[]])[0]
        docs = raw.get("documents", [[]])[0]
        metas = raw.get("metadatas", [[]])[0]
        dists = raw.get("distances", [[]])[0]

        for i in range(len(ids)):
            results.append({
                "id": ids[i],
                "text": docs[i] if i < len(docs) else "",
                "metadata": metas[i] if i < len(metas) else {},
                "score": round(1 - dists[i], 4) if i < len(dists) and dists[i] else 1.0,
            })

        return results


# ── 便捷函数 ──────────────────────────────────────────

def get_vector_store() -> VectorStore:
    """获取 VectorStore 实例"""
    return VectorStore()
