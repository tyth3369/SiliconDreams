from src.retriever import Retriever


class FakeVectorStore:
    def search_hybrid(self, _query, top_k, sources=None):
        assert top_k >= 64
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
    def search_chunks_bm25(self, _query, limit, sources=None):
        assert limit >= 64
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


def test_english_financial_route_is_case_insensitive():
    assert Retriever._route_query("Revenue and Gross Margin") == "table_first"


def test_empty_query_skips_backends():
    retriever = Retriever(vector_store=FakeVectorStore(), database=FakeDatabase())
    assert retriever.retrieve("   ") == []


def test_query_expansion_adds_company_and_metric_aliases():
    expanded = Retriever._expand_query("中芯国际2025年毛利率")

    assert "gross margin" in expanded


def test_named_company_scoping_removes_other_company_results():
    results = [
        {"metadata": {"source": "TSMC-2025-Annual-Report.pdf"}},
        {"metadata": {"source": "SMIC-2025-Annual-Report.pdf"}},
    ]

    scoped = Retriever._scope_to_named_companies("中芯国际毛利率", results)

    assert len(scoped) == 1
    assert scoped[0]["metadata"]["source"].startswith("SMIC")


def test_lexical_rank_fusion_rewards_results_found_by_both_queries():
    primary = [{"id": "shared"}, {"id": "primary-only"}]
    secondary = [{"id": "secondary-only"}, {"id": "shared"}]

    merged = Retriever._merge_rankings(primary, secondary, limit=3)

    assert {item["id"] for item in merged} == {"shared", "primary-only", "secondary-only"}


def test_answer_evidence_prioritizes_requested_metric():
    candidates = [
        {"id": "generic", "text": "The company performed well in 2025."},
        {"id": "answer", "text": "Gross margin increased to 21% in 2025."},
    ]

    ranked = Retriever._prioritize_answer_evidence("What was the gross margin?", candidates)

    assert ranked[0]["id"] == "answer"
