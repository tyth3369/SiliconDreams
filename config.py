"""
SiliconDreams — 全局配置
=======================
环境变量加载、路径常量、LLM/Embedding 配置。
所有模块从此处读取配置，不直接访问 os.environ。
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# ── 项目根目录 ─────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent

# ── 加载 .env ──────────────────────────────────────────
env_path = ROOT_DIR / ".env"
if env_path.exists():
    load_dotenv(env_path)
else:
    # 开发阶段仅警告，不阻断（允许先跑 UI 后配 Key）
    print("[config] .env file not found. Run: cp .env.example .env")

# ── 路径常量 ───────────────────────────────────────────
DATA_DIR = ROOT_DIR / "data"
PDF_DIR = DATA_DIR / "pdfs"
CHROMA_DIR = DATA_DIR / "chroma_db"
REPORTS_DIR = DATA_DIR / "reports"
DATABASE_FILE = DATA_DIR / "silicondreams.db"
TERMINOLOGY_FILE = DATA_DIR / "terminology.json"
STYLES_DIR = ROOT_DIR / "styles"
DEVLOG_DIR = ROOT_DIR / "devlog"


# ── DeepSeek API 配置 ──────────────────────────────────
class LLMConfig:
    """LLM API 配置"""

    api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    api_base: str = os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com")
    model: str = os.getenv("LLM_MODEL", "deepseek-chat")
    reasoner_model: str = "deepseek-reasoner"  # R1，复杂推理时切换

    max_tokens: int = 4096
    temperature: float = 0.3  # 金融分析场景，低温度保证一致性
    streaming: bool = True

    @classmethod
    def is_configured(cls) -> bool:
        return bool(cls.api_key and cls.api_key != "sk-your-deepseek-api-key-here")


# ── Web Search API 配置 ──────────────────────────────────
class SearchConfig:
    """Tavily Search API 配置"""

    api_key: str = os.getenv("TAVILY_API_KEY", "")
    api_url: str = "https://api.tavily.com/search"
    max_results: int = 5
    search_depth: str = "basic"  # "basic" or "advanced"
    timeout: int = 10  # seconds

    @classmethod
    def is_configured(cls) -> bool:
        return bool(cls.api_key and cls.api_key != "tvly-dev-your-key-here")


# ── Embedding 配置 ─────────────────────────────────────
class EmbeddingConfig:
    """BGE-M3 本地 Embedding 配置"""

    model_name: str = "BAAI/bge-m3"
    max_length: int = 8192
    # device 由 EmbeddingManager 运行时自动检测 (mps/cpu)

    @staticmethod
    def get_device() -> str:
        """检测 Apple Silicon MPS 是否可用"""
        try:
            import torch

            if torch.backends.mps.is_available():
                return "mps"
        except ImportError:
            pass
        return "cpu"


# ── RAG 配置 ───────────────────────────────────────────
class RAGConfig:
    """RAG 分块与检索配置"""

    # 分块
    text_chunk_size: int = 512
    text_chunk_overlap: int = 64
    table_chunk_size: int = 2048  # 表格不分块，这只是上限
    table_chunk_overlap: int = 0

    # 检索
    similarity_top_k: int = 8
    rerank_top_n: int = 4
    hybrid_weight_vector: float = 0.7  # 向量权重
    hybrid_weight_bm25: float = 0.3  # BM25 权重

    # ChromaDB
    chroma_collection_text: str = "text_chunks"
    chroma_collection_table: str = "table_chunks"


# ── App 配置 ───────────────────────────────────────────
class AppConfig:
    """应用配置"""

    name: str = "SiliconDreams"
    version: str = "0.7.0"
    sidebar_width: int = 300  # px
    max_upload_size_mb: int = 50
    supported_pdf_types: list = ["pdf"]

    # Prompt templates by language
    _system_prompts = {
        "zh": (
            "你是 SiliconDreams，一位专注于电子/半导体行业的 AI 助理分析师。\n\n"
            "## 核心能力\n"
            "1. 精确检索财报中的数据（表格、数字、比率）\n"
            "2. 结合半导体技术知识分析商业影响\n"
            "3. 生成结构化的行业研究报告\n\n"
            "## 可用工具\n"
            "- web_search: 搜索互联网获取实时信息、最新新闻\n"
            "- search_reports: 在已上传的PDF财报中检索数据\n"
            "- lookup_terms: 查询半导体专业术语的定义\n"
            "- get_company_data: 获取台积电/中芯国际的结构化财务数据\n"
            "- financial_calculator: 执行精确的财务计算（必须使用，禁止心算）\n\n"
            "## 引用规则\n"
            "- 引用术语库时，使用 [引用自：术语名] 格式\n"
            "- 引用财报PDF时，使用 [来源：文件名 p页码] 格式\n"
            "- 引用公司财务数据时，使用 [引用自：公司名 财务数据] 格式\n"
            "- 引用网络搜索结果时，使用 [来源：网页标题] 格式\n"
            "- 如果知识库中没有相关信息，诚实告知或尝试 web_search\n\n"
            "## 行内引用格式\n"
            "- 在回答中使用 [1]、[2] 等数字上标在句末标注引用来源\n"
            "- 每个数字对应引用溯源面板中的来源编号\n"
            "- 示例：「台积电2025年Q4营收为$33.73B[1]，毛利率62.3%[2]」\n\n"
            "## 重要规则\n"
            "- 当你已经收集到足够回答用户问题的信息后，立即停止调用工具，直接生成最终回答\n"
            "- 如果某个工具多次返回空结果或相同信息，不要继续尝试，直接用已有知识回答\n\n"
            "## 风格\n"
            "- 回答使用中文，专业术语可保留英文\n"
            "- 回答末尾如有合适的数据支撑，请举一个具体的代工厂例证"
        ),
        "en": (
            "You are SiliconDreams, an AI investment research analyst specializing "
            "in the electronics/semiconductor industry.\n\n"
            "## Core Capabilities\n"
            "1. Precisely retrieve data from financial reports (tables, figures, ratios)\n"
            "2. Analyze business impact with semiconductor technology expertise\n"
            "3. Generate structured industry research reports\n\n"
            "## Available Tools\n"
            "- web_search: Search the internet for real-time information and news\n"
            "- search_reports: Search uploaded PDF financial reports\n"
            "- lookup_terms: Look up semiconductor terminology definitions\n"
            "- get_company_data: Get structured financial data for TSMC/SMIC\n"
            "- financial_calculator: Perform precise financial calculations (MUST use, NO mental math)\n\n"
            "## Citation Rules\n"
            "- When citing terminology: use [from: TermName] format\n"
            "- When citing reports: use [source: filename pN] format\n"
            "- When citing company data: use [from: CompanyName financials] format\n"
            "- When citing web results: use [from: Page Title] format\n"
            "- If information is unavailable, honestly say so or try web_search\n\n"
            "## Inline Citation Format\n"
            "- Use [1], [2] numeric superscript markers to cite sources in your answer\n"
            "- Each number corresponds to a source in the citation panel\n"
            '- Example: "TSMC Q4 2025 revenue reached $33.73B[1] with 62.3% gross margin[2]"\n\n'
            "## Important Rules\n"
            "- Once you have enough information from tools to answer the user's question, stop calling tools immediately and generate the final answer\n"
            "- If a tool returns empty results or the same information multiple times, don't keep trying — answer with what you have\n\n"
            "## Style\n"
            "- Respond in English; technical terms may retain their original language\n"
            "- When appropriate, include a concrete foundry example to illustrate the point"
        ),
    }

    @classmethod
    def get_system_prompt(cls, lang: str = "zh") -> str:
        """Get system prompt for the given language."""
        return cls._system_prompts.get(lang, cls._system_prompts["zh"])


# ── 调试 ────────────────────────────────────────────────
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

if DEBUG:
    print(f"[config] ROOT_DIR = {ROOT_DIR}")
    print(f"[config] LLM configured = {LLMConfig.is_configured()}")
    print(f"[config] Embedding device = {EmbeddingConfig.get_device()}")
    print(f"[config] DATA_DIR = {DATA_DIR}")
