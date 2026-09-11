from src.retriever import Retriever


class FakeVectorStore:
    def search_hybrid(self, _query, top_k):
        assert top_k >= 20
        return [
            {
                "id": "chunk-a",
                "text": "dense result",
                "metadata": {"vector_id": "chunk-a", "chunk_type": "text", "page": 1},
                "score": 0.9,
            },
            {
                "id": "chunk-b",
                "text": "second dense result",
                "metadata": {"vector_id": "chunk-b", "chunk_type": "table", "page": 2},
                "score": 0.8,
            },
        ]


class FakeDatabase:
    def search_chunks_bm25(self, _query, limit):
        assert limit >= 20
        return [
            {
                "id": "chunk-b",
                "vector_id": "chunk-b",
                "text": "second lexical result",
                "chunk_type": "table",
                "page": 2,
                "original_filename": "report.pdf",
                "bm25_score": 4.2,
            },
            {
                "id": "chunk-c",
                "vector_id": "chunk-c",
                "text": "lexical only",
                "chunk_type": "text",
                "page": 3,
                "original_filename": "report.pdf",
                "bm25_score": 2.1,
            },
        ]


def test_rrf_rewards_candidates_found_by_both_paths():
    retriever = Retriever(vector_store=FakeVectorStore(), database=FakeDatabase())
    results = retriever.retrieve("台积电", top_k=3, rerank=False)
    assert results[0]["id"] == "chunk-b"
    assert results[0]["dense_score"] == 0.8
    assert results[0]["bm25_score"] == 4.2
    assert results[0]["metadata"]["source"] == "report.pdf"


def test_financial_query_boosts_table_candidates():
    retriever = Retriever(vector_store=FakeVectorStore(), database=FakeDatabase())
    results = retriever.retrieve("台积电毛利率", top_k=3, rerank=False)
    assert results[0]["source_type"] == "table"


def test_empty_query_skips_backends():
    retriever = Retriever(vector_store=FakeVectorStore(), database=FakeDatabase())
    assert retriever.retrieve("   ") == []
