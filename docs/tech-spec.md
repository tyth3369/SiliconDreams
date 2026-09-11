# SiliconDreams — 技术规范 v0.8

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

## 检索

1. BGE-M3 cosine 稠密召回。
2. SQLite 文本上的 BM25；英文/数字 token + 中文 2/3-gram。
3. 原始查询与中英术语扩展分别执行词法召回，再用 best-rank 合并，避免扩展词稀释原始查询。
4. Weighted reciprocal-rank fusion；财务问题提高精确 BM25 权重，显式公司名约束到匹配报告。
5. 本地 `mmarco-mMiniLMv2-L12-H384-v1` cross-encoder 重排后，以查询所需指标的证据覆盖度做确定性终排。
6. `src/evaluation.py` 计算 Recall@K 和 MRR。v0.8 的 12 题中英双语基准来自人工核验的 TSMC/SMIC 2025 官方年报，发布门槛为 Recall@5 ≥ 90%、MRR ≥ 70%。

## 引用

`CitationTracker` 按来源类型、名称和页码去重。网页 URL 只允许绝对 HTTP(S)，所有文本 HTML escape。前端用 marked 渲染 Markdown、DOMPurify 消毒，再将 `[N]` 绑定到同一消息的引用条目。

时效性查询使用 Tavily `news` topic 并把当前日期作为 `end_date`；普通知识查询使用 `general`。网页结果进入上下文前按相关度、Tier 和时效状态重排。Tier 1 是公司/监管官方域名；Tier 2 仅由显式白名单中的国际主流媒体和半导体专业媒体构成；其余均为 Tier 3。引用面板显示发布者、日期、Tier，以及“日期未知/较旧背景来源”标签。最终回答提示包含本次实际来源构成，并要求低等级来源不得无说明覆盖官方披露。

## 持久化与并发

- SQLite WAL 保存来源、事实、文档、会话和消息。
- PDF 摄入任务保存在 SQLite `jobs` 表；单后台 worker 原子领取任务，记录阶段与进度，并在进程重启时把中断任务重新排队。
- 上传接口只负责校验、内容寻址落盘和入队；侧栏每秒拉取一次任务状态，任务结束后自动停止轮询。
- conversation cookie 为 HttpOnly、SameSite=Lax。
- 对话列表按最近活动排序；首条用户消息自动生成可修改标题。归档使用 `archived_at` 软删除并支持恢复，schema v1 数据库启动时自动迁移到 v2。
- SSE hand-off 有 60 秒 TTL 和 128 条上限。
- 同步 LLM/RAG generator 通过 worker thread 逐步推进，避免冻结 FastAPI event loop。
- 模型上下文只取最近 24 条消息，UI/数据库仍保留更长历史。
- 导出器直接读取 SQLite 中的完整会话；Markdown 保留原始内容与来源链接，PDF 使用内嵌 Noto Sans SC、分页表格和可点击网页来源，避免依赖查看设备字体。

## 安全

- `.env`、token、PDF、DB、vector store 由 `.gitignore` 排除。
- PDF 校验扩展名、大小和 `%PDF-` magic；文件名净化。
- 用户输入限制 4000 字符。
- CSP、nosniff、frame deny、referrer policy、permissions policy 默认启用。
- Prompt 明确把网页/PDF/工具输出视为不可信证据，禁止执行嵌入指令。

## 已知边界

- CSP 暂时允许 inline script，以兼容现有 HTMX fragment 和本地化数据；公网部署前应改 nonce 或移除 inline script。
- PDF 后台摄入采用单机 SQLite 队列；多实例部署前需要改为共享任务队列和跨进程锁。
- 当前身份模型适用于 localhost 单用户，不适合直接公开部署。

## v0.8 部署

- 生产拓扑：Caddy（TLS + Basic Auth）→ 单 worker Uvicorn → SQLite/Chroma 持久目录。
- Caddy 对 SSE 禁用响应缓冲，自动完成 HTTP 到 HTTPS 跳转与证书续期。
- BGE-M3 与 Cross-Encoder 位于独立 Docker 命名卷，应用数据绑定到宿主机 `data/`。
- Basic Auth 仅用于首发访问保护；移除前必须完成正式身份认证、CSRF、限流和审计。
- 由于 SSE hand-off 仍为进程内状态，当前版本禁止多 worker 或多实例部署。
