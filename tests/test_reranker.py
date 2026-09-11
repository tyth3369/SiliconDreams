from src.reranker import RerankerManager


class FakeCrossEncoder:
    @staticmethod
    def predict(pairs, show_progress_bar=False):
        assert show_progress_bar is False
        assert len(pairs) == 3
        return [0.1, 0.9, 0.4]


def test_model_scores_determine_final_order():
    manager = RerankerManager.get_instance()
    manager._model = FakeCrossEncoder()
    candidates = [
        {"id": "a", "text": "first", "score": 0.99},
        {"id": "b", "text": "best", "score": 0.50},
        {"id": "c", "text": "third", "score": 0.10},
    ]
    results = manager.rerank("query", candidates, top_n=2)
    assert [item["id"] for item in results] == ["b", "c"]
    assert results[0]["rerank_score"] == 0.9
    RerankerManager.reset()


def test_missing_model_falls_back_to_fused_order(monkeypatch):
    manager = RerankerManager.get_instance()
    monkeypatch.setattr(manager, "is_available", lambda: False)
    results = manager.rerank(
        "query",
        [{"id": "a", "text": "first"}, {"id": "b", "text": "second"}],
        top_n=1,
    )
    assert [item["id"] for item in results] == ["a"]
    RerankerManager.reset()
