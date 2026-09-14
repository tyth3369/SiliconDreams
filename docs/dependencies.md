# SiliconDreams — 依赖说明 v0.8

## 环境

- Python `3.12.x`（`.python-version`）
- uv 管理环境与锁文件（`uv.lock`）
- 生产部署使用 Docker Engine、Compose v2 与 Caddy 2
- 直接依赖唯一来源：`pyproject.toml`
- `requirements.txt` 是兼容传统工具的自动导出文件，不应手工编辑

## 直接依赖分组

| 分组 | 包 |
|---|---|
| Web | FastAPI, Uvicorn, Jinja2, python-multipart |
| LLM/Search | openai, curl-cffi, python-dotenv |
| RAG | ChromaDB, sentence-transformers, torch |
| PDF | PyMuPDF, PyMuPDF4LLM, pdfplumber, tabulate |
| Data | pandas, Pydantic |
| Dev | pytest, pytest-cov, Ruff, httpx, Playwright, pip-audit |

Linux 生产镜像通过 uv 的显式 PyTorch CPU 索引安装 `torch+cpu`，不携带 CUDA、NVIDIA 或 Triton 运行库；macOS 继续从 PyPI 安装原生 wheel 并保留 Apple Silicon MPS。`requirements.txt` 由 `uv.lock` 导出并包含完整哈希，CI 使用 `pip-audit --disable-pip` 直接审计锁定版本，避免二次解析到不同软件源。

Docker 与 Caddy 属于部署基础设施，不是 Python 运行时依赖，因此不写入 `pyproject.toml`。

LangChain、LlamaIndex 和 Streamlit 已从活跃依赖中删除。

## 常用命令

```bash
uv sync --dev
uv lock --check
uv pip check
uv run pip-audit --disable-pip -r requirements.txt --timeout 60  # 已复核例外以 CI 为唯一可执行策略
uv run ruff check .
uv run pytest
uv run playwright install chromium
uv run pytest -m e2e
uv export --no-dev --format requirements-txt --output-file requirements.txt
```

## 磁盘占用

- `.venv` 约 1.3GB，随平台和版本变化。
- BGE-M3 本地缓存约 2.3GB。
- cross-encoder 本地缓存约 0.5GB。
- PDF、SQLite 和 ChromaDB 随用户资料增长，均不进入 Git。

不要同时维护 `venv/` 与 `.venv/`。本项目统一使用 `.venv/`，并可由 `uv.lock` 重建。
