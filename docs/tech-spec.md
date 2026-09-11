# SiliconDreams — 技术规范 v0.7

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
- Chroma 的 vector ID 与 SQLite chunk ID 一致，upsert 保持幂等。

## 检索

1. BGE-M3 cosine 稠密召回。
2. SQLite 文本上的 BM25；英文/数字 token + 中文 2/3-gram。
3. Weighted reciprocal-rank fusion，财务查询轻度提升表格，概念查询轻度提升文本。
4. 本地 `mmarco-mMiniLMv2-L12-H384-v1` cross-encoder 对候选重排。
5. `src/evaluation.py` 计算 Recall@K 和 MRR；真实基准必须由人工核验 PDF 页码。

## 引用

`CitationTracker` 按来源类型、名称和页码去重。网页 URL 只允许绝对 HTTP(S)，所有文本 HTML escape。前端用 marked 渲染 Markdown、DOMPurify 消毒，再将 `[N]` 绑定到同一消息的引用条目。

## 持久化与并发

- SQLite WAL 保存来源、事实、文档、会话和消息。
- conversation cookie 为 HttpOnly、SameSite=Lax。
- SSE hand-off 有 60 秒 TTL 和 128 条上限。
- 同步 LLM/RAG generator 通过 worker thread 逐步推进，避免冻结 FastAPI event loop。
- 模型上下文只取最近 24 条消息，UI/数据库仍保留更长历史。

## 安全

- `.env`、token、PDF、DB、vector store 由 `.gitignore` 排除。
- PDF 校验扩展名、大小和 `%PDF-` magic；文件名净化。
- 用户输入限制 4000 字符。
- CSP、nosniff、frame deny、referrer policy、permissions policy 默认启用。
- Prompt 明确把网页/PDF/工具输出视为不可信证据，禁止执行嵌入指令。

## 已知边界

- CSP 暂时允许 inline script，以兼容现有 HTMX fragment 和本地化数据；公网部署前应改 nonce 或移除 inline script。
- 上传仍为单请求工作流，虽不阻塞 Agent SSE，但尚无持久后台队列与百分比进度。
- 当前身份模型适用于 localhost 单用户，不适合直接公开部署。
