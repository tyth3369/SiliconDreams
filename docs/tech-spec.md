# SiliconDreams — 技术规范 v1.0-dev.2

## 真实架构

```text
Browser
  -> FastAPI / HTMX / SSE
  -> SQLite conversation + request hand-off
  -> retrieval planner (DeepSeek function calling, once)
       -> Tavily web search (<=2)
       -> PDF hybrid RAG (<=1)
       -> terminology (<=1)
       -> official company facts (<=2)
     retrieval tools run concurrently
  -> calculator planner (only for numeric intent, once)
       -> Decimal calculator (<=4)
  -> DeepSeek streaming generation
  -> sanitized Markdown + message-local citations
```

## Agent 收敛模型

`src/agent_loop.py` 不使用 ReAct while-loop。检索规划和计算规划各调用模型至多一次；Pydantic 校验参数，按工具预算去重截断。检索工具并发执行、按规划顺序合并引用。这样从结构上消除了“达到最大迭代次数”的旧问题。

## Provider

`src/providers/base.py` 定义最小接口，`src/providers/deepseek.py` 实现 DeepSeek V4。普通规划和生成显式关闭 thinking，复杂研究接口可开启。兼容入口 `src/llm_client.py` 不包含业务逻辑。

## PDF 与证据模型

- PyMuPDF4LLM 使用 page chunks 和 `lines_strict`；pdfplumber 处理复杂表格回退。
- 文件以 SHA-256 内容寻址保存。
- SQLite：`sources -> documents -> chunks/facts`；每条证据保留来源、页码、时间、可信等级和原文。
- `src/evidence_policy.py`：对网页证据执行可信等级、发布日期和时效评估；未来日期结果在进入模型前被剔除。对结构化 facts 只在公司、指标、期间、单位和币种均相同时检测数值冲突，避免把口径差异误报为冲突。
- Chroma 的 vector ID 与 SQLite chunk ID 一致，upsert 保持幂等。
- 结构化公司事实区分 `FY2025` 与 `YYYY QN`；台积电季度实际值逐季绑定官方 IR 页面，中芯国际季度实际值逐季绑定港交所公告，未收录季度不得退回年度数据冒充。
- 两家公司 2024 Q1–2026 Q2 的共同直接披露口径是 USD revenue 与 gross margin。台积电直接披露 operating margin；中芯国际披露 operating profit 金额，若需利润率只能调用 Decimal 计算器派生。
- `data/metric_definitions.json` 是公司对比、后续图表和报告模板共用的指标口径注册表；`src/analysis_templates.py` 只生成有界研究请求，不执行或伪造计算。
- `src/analytics.py` 只把已存储的官方报告值组织为图表载荷，不在展示层派生财务比率；季度点保留原始标题、发布日期和官方 URL，中芯国际制程结构保留近似值标记。

## 检索

1. BGE-M3 cosine 稠密召回。
2. SQLite 文本上的 BM25；英文/数字 token + 中文 2/3-gram。
3. 原始查询与中英术语扩展分别执行词法召回，再用 best-rank 合并，避免扩展词稀释原始查询。
4. Weighted reciprocal-rank fusion；财务问题提高精确 BM25 权重，显式公司名约束到匹配报告。
5. 本地 `mmarco-mMiniLMv2-L12-H384-v1` cross-encoder 重排后，以查询所需指标的证据覆盖度做确定性终排。
6. `src/evaluation.py` 计算 Recall@K 和 MRR。v0.8 的 12 题中英双语基准来自人工核验的 TSMC/SMIC 2025 官方年报，发布门槛为 Recall@5 ≥ 90%、MRR ≥ 70%。

## 术语知识图谱

`src/knowledge_graph.py` 将 100 条术语规范化为稳定 term 实体；无法解析为既有术语的关联词保留为 concept 实体，不再形成悬空字符串。`data/entity_aliases.json` 对 TSMC/SMIC/NVIDIA/NXP/TI 等常见公司别名进行人工归一化。`related_to` 与 `associated_with` 均生成显式反向边，`scripts/audit_knowledge_graph.py` 在发布前检查端点闭合、反向边和别名冲突。术语 Prompt 使用规范图谱邻居，但原始定义和商业影响仍来自 `terminology.json`。

## 引用

`CitationTracker` 按来源类型、名称和页码去重。网页 URL 只允许绝对 HTTP(S)，所有文本 HTML escape。前端用 marked 渲染 Markdown、DOMPurify 消毒，再将 `[N]` 绑定到同一消息的引用条目。

`src/evaluation.py` 同时检查行内编号范围、人工标注 claim 的来源支持关系和可核验陈述覆盖率。`tests/fixtures/citation_golden.json` 冻结 6 个由真实 DeepSeek Agent 生成并人工复核的中英双语回答；CI 强制 citation precision ≥ 95%、claim coverage ≥ 90%、marker validity = 100%。结构化财务与术语引用均携带本次实际提供给模型的有界证据摘要，而不是只有笼统数据库名称。

`src/observability.py` 为每次 Agent 请求收集总耗时、首 token、模型调用与 token usage、工具耗时/错误以及引用来源类型。schema v6 的 `ai_runs` / `ai_tool_events` 仅保存聚合元数据，不保存问题、回答、来源名称、URL 或证据片段。DeepSeek 流按[官方 Chat Completions 规范](https://api-docs.deepseek.com/api/create-chat-completion/)使用 `stream_options.include_usage` 获取实际 token；成本仅在部署者显式配置每百万 token 价格时由 Decimal 计算，否则返回 `null`。认证后的 `/ops/metrics` 和 `manage_database.py metrics` 提供 24 小时或自定义窗口汇总，并分别报告 success、degraded、error 与 cancelled 比例，不把降级回答或客户端取消误称为错误。

时效性查询使用 Tavily `news` topic 并把当前日期作为 `end_date`；普通知识查询使用 `general`。网页结果进入上下文前按相关度、Tier 和时效状态重排。Tier 1 是公司/监管官方域名；Tier 2 仅由显式白名单中的国际主流媒体和半导体专业媒体构成；其余均为 Tier 3。引用面板显示发布者、日期、Tier，以及“日期未知/较旧背景来源”标签。最终回答提示包含本次实际来源构成，并要求低等级来源不得无说明覆盖官方披露。

明确包含“官方/财报/年报/季报/filing/results”等意图的公司查询通过 Tavily `include_domains` 约束到对应公司或监管域名。一般搜索缓存 24 小时，时效性搜索缓存 15 分钟；缓存命中仍重新执行当前日期的时效策略。每个返回摘要以 URL + 内容哈希保存到 SQLite `web_snapshots`，支持事后审计检索时实际提供给模型的网页证据。

## 持久化与并发

- SQLite WAL 保存来源、事实、文档、会话和消息。
- `src/migrations.py` 按 v1→v6 在单一 `BEGIN IMMEDIATE` 事务中升级数据库；每步在 `schema_migrations` 保存名称、SHA-256 校验和、时间和 baseline 状态。启动时拒绝未来版本、历史漂移、缺表/列/索引/触发器以及不完整 FTS 结构，不再以最终建表脚本覆盖真实升级历史。
- `scripts/manage_database.py` 提供只读状态、完整性校验、SQLite 在线备份和显式原子恢复；备份在返回前再次验证当前 schema、foreign keys 和 `PRAGMA integrity_check`。
- PDF 摄入任务保存在 SQLite `jobs` 表；单后台 worker 原子领取任务，记录阶段与进度，并在进程重启时把中断任务重新排队。
- 上传接口只负责校验、内容寻址落盘和入队；侧栏每秒拉取一次任务状态，任务结束后自动停止轮询。
- conversation cookie 为 HttpOnly、SameSite=Lax。
- 对话列表按最近活动排序；首条用户消息自动生成可修改标题。归档使用 `archived_at` 软删除并支持恢复，schema v1 数据库启动时自动迁移到 v2。
- SSE hand-off 有 60 秒 TTL 和 128 条上限。
- 同步 LLM/RAG generator 通过 worker thread 逐步推进，避免冻结 FastAPI event loop。
- 模型上下文只取最近 24 条消息，UI/数据库仍保留更长历史。
- 导出器直接读取 SQLite 中的完整会话；Markdown 保留原始内容与来源链接，PDF 使用内嵌 Noto Sans SC、分页表格和可点击网页来源，避免依赖查看设备字体。
- `watchlist` 表持久保存关注公司；事件时间线由结构化季度事实确定性生成，按官方发布日期排序并链接披露原文，不把网页传闻冒充公司事件。

## 安全

- `.env`、token、PDF、DB、vector store 由 `.gitignore` 排除。
- PDF 校验扩展名、大小和 `%PDF-` magic；文件名净化。
- 用户输入限制 4000 字符。
- `APP_ENV=production` 强制启用应用层单账号认证和 Secure Cookie；PBKDF2 密码哈希与 HMAC 会话密钥只存在于部署环境变量。
- 会话绑定的双提交 CSRF token 保护所有认证后的写请求；HTMX 统一附加请求头。
- 登录、AI 与普通请求分桶限流；当前单 worker 下使用线程安全内存滑动窗口。
- schema v5 的 `audit_events` 保存写请求结果和匿名化客户端标识，触发器拒绝修改或删除。
- 每个页面请求生成独立 CSP nonce；CSP 不允许 `unsafe-inline`。nosniff、frame deny、referrer policy、permissions policy、COOP 和生产 HSTS 默认启用。
- Prompt 明确把网页/PDF/工具输出视为不可信证据，禁止执行嵌入指令。
- CI 使用 `pip-audit` 检查导出的生产依赖；未复核漏洞直接阻断。ChromaDB 上游尚无修复版本的 HTTP Server 公告只在嵌入式 `PersistentClient`、无 Server/HTTP Client/端口暴露的约束下限时例外，并由架构测试持续验证。

## 已知边界

- 认证是单共享账号，尚无角色、用户隔离和单会话服务端撤销。
- 限流状态位于单进程内存，服务重启后重置；多实例前需要共享限流后端。
- PDF 后台摄入采用单机 SQLite 队列；多实例部署前需要改为共享任务队列和跨进程锁。
- 当前身份模型适用于个人或小团队共享账号的单实例部署，不适合多租户服务。

## 浏览器与性能回归

- `tests/test_browser_e2e.py` 启动隔离 SQLite 的真实 Uvicorn + Chromium，验证主题、语言、图表、Watchlist 以及对话 DOM 不丢失。
- CI 安装固定于 lockfile 的 Playwright Chromium 并执行该测试。
- `scripts/benchmark_workbench.py` 对无外部 API 的核心工作台路由建立可重复的本机中位数/P95基线。

## v1.0 部署

- 生产拓扑：Caddy（TLS）→ 应用认证与限流 → 单 worker Uvicorn → SQLite/Chroma 持久目录。
- Caddy 对 SSE 禁用响应缓冲，自动完成 HTTP 到 HTTPS 跳转与证书续期。
- BGE-M3 与 Cross-Encoder 位于独立 Docker 命名卷，应用数据绑定到宿主机 `data/`。
- `APP_ENV=production` 在认证配置缺失或 Cookie 非 Secure 时拒绝启动。
- 由于 SSE hand-off 仍为进程内状态，当前版本禁止多 worker 或多实例部署。
