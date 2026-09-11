# SiliconDreams — API 与本地模型配置

## 1. 环境文件

```bash
cp .env.example .env
chmod 600 .env
```

填写：

```dotenv
DEEPSEEK_API_KEY=sk-your-key
DEEPSEEK_API_BASE=https://api.deepseek.com
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-v4-flash
LLM_REASONER_MODEL=deepseek-v4-pro
TAVILY_API_KEY=tvly-your-key
DEBUG=false
```

DeepSeek key 在 [DeepSeek Platform](https://platform.deepseek.com/) 创建；Tavily key 在 [Tavily](https://app.tavily.com/) 创建。不要把真实 key 写入 `.env.example`、文档、Issue 或 Git commit。

VS Code 的 `python.terminal.useEnvFile` 提示不影响应用：`config.py` 会在进程启动时通过 python-dotenv 读取项目根目录 `.env`。

## 2. 本地模型

BGE-M3 约 2.3GB，用于 embedding：

```bash
uv run python src/tools/download_bge_m3.py
```

多语言 cross-encoder 约 0.5GB，用于重排：

```bash
uv run python src/tools/download_reranker.py
```

两个脚本均使用系统 curl、支持镜像与断点续传，避免旧版 macOS Python/LibreSSL 的 Hugging Face TLS 问题。运行期优先本地离线缓存，不应重复下载。

## 3. 验证

```bash
uv run python -c "from src.providers import get_provider; print(type(get_provider()).__name__)"
uv run python -c "from src.embedding_manager import EmbeddingManager; print(len(EmbeddingManager.get_instance().embed_query('台积电')))"
uv run pytest
```

网络搜索不可用时，Agent 应降级到本地证据并明确说明；不得把 DDG fallback 当成稳定生产依赖。
