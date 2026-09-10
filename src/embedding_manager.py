"""
SiliconDreams — BGE-M3 Embedding 单例管理器
=============================================
Apple Silicon MPS 加速 + 全局唯一实例 + 惰性加载。
杜绝每次 PDF 上传重复加载 2GB 模型。
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class EmbeddingManager:
    """
    BGE-M3 Embedding 单例管理器。

    用法:
        manager = EmbeddingManager.get_instance()
        embed_model = manager.get_model()
        embedding = embed_model.get_text_embedding("台积电3nm制程")
    """

    _instance: Optional["EmbeddingManager"] = None
    _model = None
    _device: Optional[str] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def get_instance(cls) -> "EmbeddingManager":
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @staticmethod
    def _detect_device() -> str:
        """检测最佳运行设备：MPS (Apple Silicon GPU) → CPU (fallback)"""
        try:
            import torch
            if torch.backends.mps.is_available():
                logger.info("✅ Embedding 设备: MPS (Apple Silicon GPU)")
                return "mps"
            elif torch.cuda.is_available():
                logger.info("✅ Embedding 设备: CUDA")
                return "cuda"
        except ImportError:
            pass
        logger.info("⚡ Embedding 设备: CPU (MPS 不可用)")
        return "cpu"

    def get_device(self) -> str:
        """获取当前设备（惰性检测）"""
        if self._device is None:
            self._device = self._detect_device()
        return self._device

    # Local cache path (populated by src/tools/download_bge_m3.py)
    LOCAL_CACHE = "~/.cache/silicondreams/models/bge-m3"

    @staticmethod
    def _is_model_cached(model_name: str) -> bool:
        """Check if a HuggingFace model is already cached locally."""
        import os as _os

        # 1. Check local cache (curl_cffi download, preferred on macOS)
        local_path = _os.path.expanduser(EmbeddingManager.LOCAL_CACHE)
        if _os.path.isdir(local_path) and _os.path.isfile(_os.path.join(local_path, "pytorch_model.bin")):
            return True

        # 2. Check standard HuggingFace cache
        safe_name = "models--" + model_name.replace("/", "--")
        cache_dir = _os.path.expanduser(f"~/.cache/huggingface/hub/{safe_name}")
        if _os.path.isdir(cache_dir):
            snapshots = _os.path.join(cache_dir, "snapshots")
            if _os.path.isdir(snapshots) and _os.listdir(snapshots):
                return True
        return False

    @staticmethod
    def _get_model_path(model_name: str) -> str:
        """
        Return the best model path to use. Prefers local curl_cffi cache
        over the HuggingFace model ID (which triggers network access).
        """
        import os as _os
        local_path = _os.path.expanduser(EmbeddingManager.LOCAL_CACHE)
        if _os.path.isfile(_os.path.join(local_path, "pytorch_model.bin")):
            return local_path
        return model_name

    def get_model(self):
        """
        获取 BGE-M3 Embedding 模型（惰性加载，首次调用时下载约 2GB）。

        Returns:
            HuggingFaceEmbedding 实例
        """
        if self._model is not None:
            return self._model

        from config import EmbeddingConfig

        # ── macOS LibreSSL workaround ──────────────────────
        # macOS ships LibreSSL 2.8.3 which can't negotiate modern TLS.
        # If the model is cached (local or HF hub), skip online checks.
        import os as _os
        if self._is_model_cached(EmbeddingConfig.model_name):
            _os.environ.setdefault("HF_HUB_OFFLINE", "1")
            logger.info("📦 BGE-M3 模型已缓存，跳过在线检查（HF_HUB_OFFLINE=1）")
        else:
            logger.info("🔄 首次使用，需要下载 BGE-M3 模型（约 2GB）...")
            logger.info("   如遇 SSL 错误，请运行: python src/tools/download_bge_m3.py")

        device = self.get_device()

        from llama_index.embeddings.huggingface import HuggingFaceEmbedding

        # Use local cache path if available, otherwise HuggingFace model ID
        model_path = self._get_model_path(EmbeddingConfig.model_name)
        logger.info(f"   使用模型路径: {model_path}")

        self._model = HuggingFaceEmbedding(
            model_name=model_path,
            device=device,
            max_length=EmbeddingConfig.max_length,
            trust_remote_code=True,
        )

        logger.info(f"✅ BGE-M3 模型加载完成 (device={device})")
        return self._model

    def get_embedding(self, text: str) -> list[float]:
        """
        获取单条文本的 Embedding 向量。

        Args:
            text: 输入文本

        Returns:
            1024 维浮点向量
        """
        model = self.get_model()
        return model.get_text_embedding(text)

    def get_embeddings(self, texts: list[str]) -> list[list[float]]:
        """
        批量获取 Embedding 向量。

        Args:
            texts: 文本列表

        Returns:
            向量列表
        """
        model = self.get_model()
        return model.get_text_embedding_batch(texts)

    @classmethod
    def reset(cls):
        """重置单例（测试/调试用，释放模型内存）"""
        cls._instance = None
        cls._model = None
        cls._device = None


# ── Embedding 获取函数 ──────────────────────────────
# EmbeddingManager 本身已是 Singleton，确保全局唯一实例

def get_cached_embedding_model():
    """
    获取缓存的 Embedding 模型实例。
    EmbeddingManager 采用 Singleton + 惰性加载模式，
    首次调用时加载 BGE-M3 模型，后续调用复用内存中的实例。
    """
    return EmbeddingManager.get_instance().get_model()
