# SiliconDreams — 依赖安装记录
# ================================
# 安装日期: 2026-07-12
# Python 版本: 3.9.6 (系统默认)
# 平台: macOS Apple Silicon (MPS: ✅)
# 
# ⚠️ 已知限制: Python 3.9 不支持 llama-index >= 0.11
# (新版依赖 banks 库使用了 3.10+ 的 `|` 类型语法)
# 当前使用 llama-index 0.10.x，功能完整。
# 建议后续升级 Python 到 3.11+（从 python.org 下载安装器）

# ══════════════════════════════════════════════
# 第一层：前端 + LLM (Sprint 1, 已安装 ✅)
# ══════════════════════════════════════════════

fastapi>=0.110.0           # Web 框架
uvicorn[standard]>=0.27.0  # ASGI 服务器
jinja2>=3.1.0              # HTML 模板引擎
python-multipart>=0.0.9    # 文件上传支持
python-dotenv>=1.0.0        # 环境变量加载
openai>=1.12.0              # DeepSeek API (兼容 OpenAI SDK)

# ══════════════════════════════════════════════
# 第二层：RAG 核心 (Sprint 2, 本次安装)
# ══════════════════════════════════════════════

# -- LlamaIndex 生态 --
llama-index>=0.11.0                  # RAG 核心框架
llama-index-embeddings-huggingface>=0.3.0  # HuggingFace Embedding 集成
llama-index-llms-openai-like>=0.2.0  # DeepSeek (OpenAI 兼容) 集成

# -- LangChain 生态 --
langchain>=0.2.0            # Agent 框架
langchain-community>=0.2.0  # 社区集成

# -- 向量数据库 --
chromadb>=0.5.0             # 本地向量库 (SQLite 持久化)

# -- PDF 解析 --
pymupdf>=1.24.0             # PDF 底层库
pymupdf4llm>=0.0.7          # PDF → Markdown (保留表格)
pdfplumber>=0.11.0          # 复杂表格提取

# -- Embedding 模型 --
torch>=2.1.0                # PyTorch (Apple Silicon MPS)
sentence-transformers>=2.7.0  # BGE-M3 模型加载
huggingface-hub>=0.20.0     # HuggingFace 模型下载

# -- 数据处理 --
pandas>=2.0.0               # 数据框操作
numpy>=1.24.0               # 数值计算

# ══════════════════════════════════════════════
# 第三层：Agent 工具 (Sprint 3, 后续安装)
# ══════════════════════════════════════════════
# (Sprint 3 实测时确认，当前不需要额外依赖)
# - decimal (Python stdlib, 无需安装)
# - json (Python stdlib)

# ══════════════════════════════════════════════
# 开发工具
# ══════════════════════════════════════════════
pytest>=7.0.0               # 测试框架

# ══════════════════════════════════════════════
# ══════════════════════════════════════════════
# 实际安装版本 (2026-07-12)
# ══════════════════════════════════════════════
# torch:               2.8.0
# fastapi:             0.110.x
# uvicorn:             0.27.x
# openai:              2.45.0
# llama-index:         0.10.68.post1 (⚠️ 3.9兼容上限)
# llama-index-embeddings-huggingface: 0.2.3
# langchain:           0.3.27
# langchain-community: 0.3.27
# chromadb:            1.5.9
# pymupdf:             1.26.5
# pymupdf4llm:         0.0.8
# pdfplumber:          0.11.5
# sentence-transformers: 5.1.2
# pandas:              2.3.3
# numpy:               2.0.2
# pytest:              8.4.2

# ══════════════════════════════════════════════
# 预估磁盘占用
# ══════════════════════════════════════════════
# pip 包:           ~2-3 GB
# BGE-M3 模型文件:   ~2.2 GB (下载到 ~/.cache/huggingface/)
# torch:            ~800 MB
# 总计 (首次):       ~5-6 GB
# 后续增量:          ~200-300 MB (ChromaDB + 缓存)
