# SiliconDreams — 逐日执行计划

> 本文档是从 `CLAUDE.md` 引用的施工图纸。
> 每完成一步，在此文档标记 `[x]`。

---

## Sprint 0：项目初始化 + 文档体系（Day 0）

**目标**：目录就位、文档齐全、环境可用。

| # | 任务 | 状态 | 产出 |
|---|------|------|------|
| 0.1 | 创建项目目录结构 | [x] | 完整空文件夹树 |
| 0.2 | Python venv + requirements.txt | [x] | 虚拟环境 + 依赖清单 |
| 0.3 | .env.example + .gitignore + GitHub Token | [x] | 配置模板 + 排除规则 |
| 0.4 | docs/requirements.md | [x] | 需求规格说明书 |
| 0.5 | docs/tech-spec.md | [x] | 技术选型与架构文档 |
| 0.6 | docs/design-spec.md | [x] | UI 设计规范 |
| 0.7 | docs/execution-plan.md | [x] | 逐日任务清单（本文档） |
| 0.8 | docs/api-keys-guide.md | [x] | API Key 获取指南 |
| 0.9 | CLAUDE.md | [x] | AI 工作指引 |
| 0.10 | devlog/2026-07-12.md | [x] | 开发日志首日 |

---

## Sprint 1：高颜值前端框架（Day 1-2）

| # | 任务 | 状态 | 产出 |
|---|------|------|------|
| 1.1 | config.py — 全局配置类 | [x] | 环境变量加载 |
| 1.2 | styles/custom.css — 暗色极客主题 | [x] | CSS 变量、字体 |
| 1.3 | app.py — 页面骨架（侧边栏+主区域） | [x] | 空白布局可见 |
| 1.4 | app.py — 注入 CSS + 品牌元素 | [x] | 暗色主题生效 |
| 1.5 | 聊天界面 — chat_input + chat_message | [x] | 对话气泡可见 |
| 1.6 | src/llm_client.py — DeepSeek API 流式 | [x] | 流式回复正常 |
| 1.7 | 侧边栏 — PDF 上传 + 状态面板 | [x] | 上传显示文件名 |
| 1.8 | 快捷按钮区 | [x] | 按钮可点击 |
| 1.9 | 对话历史持久化 | [x] | F5 刷新不丢失 |

---

## Sprint 2：核心 RAG 管线（Day 3-5）

| # | 任务 | 状态 | 产出 |
|---|------|------|------|
| 2.1 | embedding_manager.py | [x] | BGE-M3 单例+MPS |
| 2.2 | pdf_parser.py — PyMuPDF4LLM | [x] | PDF→Markdown |
| 2.3 | pdf_parser.py — pdfplumber 辅助 | [x] | 双引擎切换 |
| 2.4 | chunker.py — 智能分块 | [x] | 文本+表格块 |
| 2.5 | vector_store.py — ChromaDB 初始化 | [x] | 本地向量库 |
| 2.6 | vector_store.py — 双 Collection | [x] | text+table 分离 |
| 2.7 | retriever.py — 基础向量检索 | [x] | 检索结果返回 |
| 2.8 | retriever.py — 混合检索 | [x] | BM25+向量 |
| 2.9 | 端到端 RAG 测试 | [x] | 问→检→答 |

---

## Sprint 3：Agent 智能体 + 知识图谱（Day 6-8）

| # | 任务 | 状态 | 产出 |
|---|------|------|------|
| 3.1 | terminology.json — 前50条 | [x] | 62条深度术语 |
| 3.2 | terminology.json — 150+条 | [x] | 六大领域全覆盖 |
| 3.3 | terminology.py — 注入逻辑 | [x] | 术语→Prompt |
| 3.4 | tools/search.py — RAG 检索工具 | [x] | Agent 可调用 |
| 3.5 | tools/calculator.py — 核心函数 | [x] | 10种比率计算 ✅ |
| 3.6 | tools/calculator.py — Tool 封装 | [x] | LangChain Tool |
| 3.7 | tools/compare.py — 公司对比 | [x] | 多公司指标对比 |
| 3.8 | tools/analyze.py — 技术趋势 | [x] | 术语联想+检索 |
| 3.9 | agent.py — ReAct 核心 | [x] | 4 tools loaded |
| 3.10 | agent.py — 强制计算规则 | [x] | 数字必须调calculator |
| 3.11 | report_generator.py — 报告模板 | [x] | 3种报告模板 |

---

## Sprint 4：引用溯源 + 集成打磨（Day 9-10）

| # | 任务 | 状态 | 产出 |
|---|------|------|------|
| 4.1 | citation_renderer.py | [x] | 引用可点击展开 |
| 4.2 | LLM Prompt 注入引用指令 | [x] | 回答带引用标签 |
| 4.3 | 错误处理完善 | [x] | 优雅报错 |
| 4.4 | 性能优化 | [x] | 单例+MPS缓存 |
| 4.5 | README.md | [x] | 完整项目文档 |
| 4.6 | 端到端全流程测试 | [x] | 全连通 ✅ |

---

## Sprint 5：GitHub 发布（可选）

| # | 任务 | 状态 | 产出 |
|---|------|------|------|
| 5.1 | .gitignore 安全审计 | [ ] | 无敏感文件泄露 |
| 5.2 | git init + commit | [ ] | 本地仓库 |
| 5.3 | push to GitHub | [ ] | 远程可见 |

---

## 里程碑

| 里程碑 | 预计日期 | 标志 |
|--------|---------|------|
| M0: 项目启动 | 2026-07-12 | Sprint 0 完成 |
| M1: Hello World | 2026-07-13 | 前端可对话 |
| M2: RAG Ready | 2026-07-15 | 财报可查询 |
| M3: Agent Smart | 2026-07-18 | 智能行研分析 |
| M4: Ship It | 2026-07-20 | 完整可交付 |
