# SiliconDreams

面向电子与半导体行业的证据优先 AI 投研助理。系统将实时网页搜索、用户上传财报、结构化公司数据和半导体术语库统一成可追溯证据，再由有界 Agent 规划检索、调用 Python 财务计算器并生成带行内引用的回答。

> 技术专家 + 财务分析师 + 可验证证据 = 投研大脑

## 已实现能力

- DeepSeek V4 Flash / Pro Provider 抽象与 SSE 流式输出
- 确定性 Agent：一次检索规划、并发取证、至多一次计算规划，无开放式循环
- Tavily 实时网页搜索，DuckDuckGo 仅作降级备用
- 网页来源可信度/发布日期策略：未来日期过滤、最新问题陈旧性标记、官方来源优先
- Web 搜索结果分时效缓存；明确的财报查询约束到公司官方域名，检索摘要以内容哈希留存审计快照
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
- 证据型财务仪表盘：季度营收/毛利率、制程收入结构和 Capex 强度；季度数据点直达官方来源
- 持久化公司 Watchlist 与官方披露事件时间线，可直接打开每期公告原文
- 规范化术语图谱：稳定实体 ID、中英文别名、公司归一化、类型边与闭合审计

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

首版生产方案为阿里云香港 ECS + Docker Compose + Caddy：Caddy 自动管理 HTTPS，应用层单账号认证、CSRF、分层限流与追加审计保护 API 额度和上传资料，`data/` 与本地模型使用持久卷。完整操作见[部署指南](docs/deployment.md)和[安全指南](docs/security.md)。

```bash
cp .env.production.example .env.production
cp .env.caddy.example .env.caddy
docker compose build
docker compose run --rm app python scripts/generate_auth_config.py
# 将生成结果和真实 API Keys 写入 .env.production
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
uv run pip-audit --disable-pip -r requirements.txt --timeout 60  # 例外参数以 CI 和 security-advisories.md 为准
uv run playwright install chromium
uv run pytest -m e2e
uv run python scripts/benchmark_workbench.py
uv run python scripts/audit_knowledge_graph.py
uv run python scripts/run_official_retrieval_benchmark.py
uv run python scripts/run_citation_benchmark.py
uv run python scripts/manage_database.py status
uv run python scripts/manage_database.py audit --limit 50
uv run python scripts/manage_database.py metrics --hours 24
uv run python scripts/verify_deployment.py --alias-url https://www.sillycon.xyz --expected-version 1.0.0-rc.5 --expected-ip ECS_PUBLIC_IPV4
```

正式检索基准由 TSMC 与 SMIC 2025 官方年报、6 个中文问题和 6 个英文问题组成；每个答案页码和关键文本均人工核验，PDF 以 SHA-256 锁定。v0.8 实测 Recall@5 为 **100%**、MRR 为 **84.03%**，高于 90% / 70% 发布门槛。脚本会下载并隔离索引官方年报，低于门槛时返回失败状态。

引用基准冻结了 6 个由真实 Agent 生成、再人工核验 claim→source 映射的中英双语回答。发布门槛为 citation precision ≥ **95%**、claim coverage ≥ **90%**、编号有效率 **100%**；当前三项均为 100%。

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
src/analytics.py             官方数据图表载荷与来源绑定
src/knowledge_graph.py       规范化术语/公司实体与类型关系图
data/entity_aliases.json     人工核验的公司实体别名
src/migrations.py            有序事务化 SQLite schema 迁移
scripts/manage_database.py   数据库状态、校验、审计、备份与恢复 CLI
scripts/verify_deployment.py 无凭据公网 DNS/TLS/安全边界验收 CLI
scripts/run_citation_benchmark.py  人工核验的真实 Agent 引用质量门禁
src/observability.py         无研究正文的请求级成本、延迟、错误与来源覆盖遥测
templates/ + static/          Bloomberg Terminal 风格 UI
assets/fonts/                 PDF 使用的 OFL 中文字体及许可证
tests/                        回归测试
```

## 数据与安全边界

- `.env`、`.github_token`、上传 PDF、SQLite 和 ChromaDB 均被 Git 忽略。
- PDF、Embedding、向量和会话存储在本机；用户问题和检索证据会发送给配置的 DeepSeek API，实时搜索查询会发送给 Tavily。
- `ai_runs` / `ai_tool_events` 只保存请求 ID、耗时、token、工具名、错误码和来源类型计数，不保存问题、回答、来源名称、URL 或证据片段。`/ops/metrics` 与 `manage_database.py metrics` 提供聚合运维视图。
- 网页和 PDF 内容被视为不可信证据，不作为系统指令执行。
- HTMX、Marked、DOMPurify 与 IBM Plex 字体均锁定版本并由 `/static/` 本地提供；第三方许可证见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
- 本项目用于研究辅助，不构成投资建议。重要判断应回到原始公告核验。

## 文档

- [需求规格](docs/requirements.md)
- [技术规范](docs/tech-spec.md)
- [设计规范](docs/design-spec.md)
- [执行计划](docs/execution-plan.md)
- [API 与模型配置](docs/api-keys-guide.md)
- [依赖说明](docs/dependencies.md)
- [v1.0 发布候选验收清单](docs/release-checklist-v1.0.md)
- [v1.0.0-rc.5 发布说明](docs/release-notes-v1.0.0-rc.5.md)
- [v1.0.0-rc.4 发布说明](docs/release-notes-v1.0.0-rc.4.md)
- [依赖安全公告与限时例外](docs/security-advisories.md)
