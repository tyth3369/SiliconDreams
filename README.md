# SiliconDreams

面向电子与半导体行业的证据优先 AI 投研助理。系统将实时网页搜索、用户上传财报、结构化公司数据和半导体术语库统一成可追溯证据，再由有界 Agent 规划检索、调用 Python 财务计算器并生成带行内引用的回答。

> 技术专家 + 财务分析师 + 可验证证据 = 投研大脑

## 已实现能力

- DeepSeek V4 Flash / Pro Provider 抽象与 SSE 流式输出
- 确定性 Agent：一次检索规划、并发取证、至多一次计算规划，无开放式循环
- Tavily 实时网页搜索，DuckDuckGo 仅作降级备用
- 网页来源可信度/发布日期策略：未来日期过滤、最新问题陈旧性标记、官方来源优先
- PDF 双引擎解析，保留原始文件名与精确页码
- BGE-M3 稠密检索 + 中文 BM25 + RRF 融合 + 多语言 Cross-encoder 重排
- SQLite 证据、事实、文档和会话持久化；ChromaDB 存储向量
- Decimal 财务计算器；LLM 不负责算术
- 100 条半导体术语、台积电/中芯国际 FY2025 官方数据，以及两家公司 2024 Q1–2026 Q2 官方季度实际值
- 显式保留披露口径差异：中芯国际营业利润率只能由官方营业利润金额经计算器派生
- `[1]` 行内引用、原文片段、网页/官方报告链接与点击定位
- 中英文界面、自动/深色/浅色主题；研究会话可新建、命名、切换、归档和恢复
- 当前研究会话可下载为完整 Markdown 或带嵌入中文字体、表格和来源链接的 PDF
- 可复用的公司对比模板与指标口径字典；快捷对比明确直接披露、派生值和可比性边界

## 架构

```text
FastAPI + HTMX + Jinja2 + SSE
              |
      Deterministic Planner
       /       |        \
Web / PDF RAG / Terms / Official Facts
       \       |        /
   Python Decimal Calculator
              |
      DeepSeek V4 Generation
              |
   Inline citations + source panel
```

PDF RAG 的排序链路为：BGE-M3 cosine 与 BM25 并行召回 → weighted RRF → `mmarco-mMiniLMv2-L12-H384-v1` 重排。

## 快速启动

要求：macOS、[uv](https://docs.astral.sh/uv/)、Python 3.12。Apple Silicon 可使用 MPS。

```bash
cd SiliconDreams
uv sync --dev
cp .env.example .env
# 在 .env 填入 DEEPSEEK_API_KEY 和 TAVILY_API_KEY
uv run python src/tools/download_bge_m3.py
uv run python src/tools/download_reranker.py
uv run uvicorn server:app --host 127.0.0.1 --port 8000 --reload
```

浏览器打开 [http://127.0.0.1:8000](http://127.0.0.1:8000)。

## 部署到 sillycon.xyz

首版生产方案为阿里云香港 ECS + Docker Compose + Caddy：Caddy 自动管理 HTTPS，Basic Auth 保护 API 额度与上传资料，`data/` 和本地模型使用持久卷。完整操作见[部署指南](docs/deployment.md)。

```bash
cp .env.production.example .env.production
cp .env.caddy.example .env.caddy
docker compose build
docker compose run --rm app python src/tools/download_bge_m3.py
docker compose run --rm app python src/tools/download_reranker.py
docker compose up -d
```

当前 SSE hand-off 是进程内状态，生产命令必须保持一个 Uvicorn worker。

## 质量检查

```bash
uv run ruff check .
uv run pytest
uv run pytest --cov=src --cov-report=term-missing
uv run python scripts/run_official_retrieval_benchmark.py
```

正式检索基准由 TSMC 与 SMIC 2025 官方年报、6 个中文问题和 6 个英文问题组成；每个答案页码和关键文本均人工核验，PDF 以 SHA-256 锁定。v0.8 实测 Recall@5 为 **100%**、MRR 为 **84.03%**，高于 90% / 70% 发布门槛。脚本会下载并隔离索引官方年报，低于门槛时返回失败状态。

## 关键目录

```text
server.py                     FastAPI 入口、会话与 PDF 摄入
config.py                     环境、模型、RAG 配置
src/agent_loop.py             有界编排管线
src/agent_tools.py            工具 Schema、校验与执行
src/providers/                LLM Provider 抽象与 DeepSeek 实现
src/storage.py                SQLite 证据/事实/会话模型
src/exporter.py               Markdown/PDF 研究记录导出
src/retriever.py              混合检索与重排
src/tools/calculator.py       唯一财务计算实现
data/terminology.json         半导体术语库
data/foundry_financials.json  官方来源结构化数据
data/metric_definitions.json 指标定义、单位、可比性与派生规则
src/analysis_templates.py    可复用公司对比模板
templates/ + static/          Bloomberg Terminal 风格 UI
assets/fonts/                 PDF 使用的 OFL 中文字体及许可证
tests/                        回归测试
```

## 数据与安全边界

- `.env`、`.github_token`、上传 PDF、SQLite 和 ChromaDB 均被 Git 忽略。
- PDF、Embedding、向量和会话存储在本机；用户问题和检索证据会发送给配置的 DeepSeek API，实时搜索查询会发送给 Tavily。
- 网页和 PDF 内容被视为不可信证据，不作为系统指令执行。
- 本项目用于研究辅助，不构成投资建议。重要判断应回到原始公告核验。

## 文档

- [需求规格](docs/requirements.md)
- [技术规范](docs/tech-spec.md)
- [设计规范](docs/design-spec.md)
- [执行计划](docs/execution-plan.md)
- [API 与模型配置](docs/api-keys-guide.md)
- [依赖说明](docs/dependencies.md)
