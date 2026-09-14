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

两个脚本均使用系统 curl、支持镜像与断点续传，避免旧版 macOS Python/LibreSSL 的 Hugging Face TLS 问题。下载 URL 固定到已审计的 Hugging Face commit；文件先写入 `.part`，大小与 SHA-256 全部通过后才原子替换并生成完成标记。运行期只接受这套已验证的离线缓存，不会把中断下载留下的残片当成可用模型。模型版本或清单变化后重新运行脚本即可校验或补齐文件。

- BGE-M3：`BAAI/bge-m3@5617a9f61b028005a4858fdac845db406aefb181`
- reranker：`cross-encoder/mmarco-mMiniLMv2-L12-H384-v1@1427fd652930e4ba29e8149678df786c240d8825`

## 3. 验证

```bash
uv run python -c "from src.providers import get_provider; print(type(get_provider()).__name__)"
uv run python -c "from src.embedding_manager import EmbeddingManager; print(len(EmbeddingManager.get_instance().embed_query('台积电')))"
curl -fsS http://127.0.0.1:8000/readyz
uv run pytest
```

网络搜索不可用时，Agent 应降级到本地证据并明确说明；不得把 DDG fallback 当成稳定生产依赖。
