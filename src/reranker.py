"""Singleton multilingual cross-encoder reranker with offline-only runtime loading."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, ClassVar

from config import RAGConfig, RerankerConfig

logger = logging.getLogger(__name__)


class RerankerManager:
    """Load the cross-encoder once and rerank fused retrieval candidates."""

    _instance: ClassVar[RerankerManager | None] = None

    def __new__(cls) -> RerankerManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._model = None
            cls._instance._load_attempted = False
        return cls._instance

    @classmethod
    def get_instance(cls) -> RerankerManager:
        return cls()

    @staticmethod
    def is_available() -> bool:
        path = Path(RerankerConfig.local_path)
        return (path / "config.json").is_file() and (
            (path / "model.safetensors").is_file() or (path / "pytorch_model.bin").is_file()
        )

    def get_model(self):
        if self._model is not None:
            return self._model
        if self._load_attempted or not self.is_available():
            return None
        self._load_attempted = True

        from sentence_transformers import CrossEncoder

        from src.embedding_manager import EmbeddingManager

        device = EmbeddingManager.get_instance().get_device()
        try:
            self._model = CrossEncoder(
                str(RerankerConfig.local_path),
                device=device,
                max_length=RerankerConfig.max_length,
                local_files_only=True,
            )
        except Exception:
            if device == "cpu":
                raise
            logger.warning("Reranker failed on %s; retrying on CPU", device, exc_info=True)
            self._model = CrossEncoder(
                str(RerankerConfig.local_path),
                device="cpu",
                max_length=RerankerConfig.max_length,
                local_files_only=True,
            )
        logger.info("Cross-encoder reranker loaded from %s", RerankerConfig.local_path)
        return self._model

    def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        top_n: int = RAGConfig.rerank_top_n,
    ) -> list[dict[str, Any]]:
        if not candidates:
            return []
        model = self.get_model()
        if model is None:
            return candidates[:top_n]

        pairs = [(query, str(candidate.get("text", ""))) for candidate in candidates]
        scores = model.predict(pairs, show_progress_bar=False)
        ranked = []
        for candidate, score in zip(candidates, scores, strict=True):
            item = dict(candidate)
            item["rerank_score"] = float(score)
            item["score"] = float(score)
            ranked.append(item)
        ranked.sort(key=lambda item: item["rerank_score"], reverse=True)
        return ranked[:top_n]

    @classmethod
    def reset(cls) -> None:
        cls._instance = None
