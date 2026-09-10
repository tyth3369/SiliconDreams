# AGENTS.md — SiliconDreams 项目工作指引

## 项目简介

**SiliconDreams（硅梦）** — 电子/半导体行业 AI 助理分析师。

基于 RAG + Agent 架构的智能投研 Agent：技术专家 + 财务分析师 + Web 搜索 = 智能投研大脑。

当前版本：**v0.6.0** — Agent-Driven Tool Calling + DuckDuckGo Web Search

## 标准文件路径（项目宪法）

| 文档 | 路径 | 作用 |
|------|------|------|
| 需求规格 | [docs/requirements.md](docs/requirements.md) | 用户故事、功能清单、验收标准 |
| 技术规范 | [docs/tech-spec.md](docs/tech-spec.md) | 架构图、组件设计、数据流、安全设计 |
| 设计规范 | [docs/design-spec.md](docs/design-spec.md) | CSS变量、配色、字体、布局、组件规范 |
| 执行计划 | [docs/execution-plan.md](docs/execution-plan.md) | Sprint 0-5 逐日任务清单（施工图纸） |
| API 指南 | [docs/api-keys-guide.md](docs/api-keys-guide.md) | API Key 获取与配置步骤 |

## 开发日志

- 目录：[devlog/](devlog/)
- 格式：`YYYY-MM-DD.md`（每天一个文件）
- **每次会话结束前，自动更新当天的 devlog**

## 工作原则

1. **小步快跑**：每次只做执行计划中当前 Sprint 的一小步，完成后停下来等待用户确认
2. **禁止 LLM 算数**：任何涉及数字计算的功能，必须使用 `src/tools/calculator.py`（Python 精确计算），严禁 LLM 自行心算
3. **先读后写**：修改任何文件前先用 Read 工具确认当前内容，避免覆盖已有工作
4. **依赖同步**：修改任何 Python 依赖前，更新 `requirements.txt`
5. **日志纪律**：每日开始→读取当天 devlog 了解进度；每日结束→更新 devlog 记录完成事项和次日计划
6. **安全第一**：`.env` 和 `.github_token` 绝对不入库，每次提交前自查

## 技术栈速查

| 层 | 技术 | 说明 |
|----|------|------|
| 前端 | FastAPI + HTMX + Jinja2 | Bloomberg 终端风，纯黑+琥珀(暗)/纯白+深蓝(浅)，IBM Plex 字体 |
| Agent | Custom Agent Loop + DeepSeek Function Calling | 5 工具（web_search/reports/terms/financial/calculator），SSE 流式 |
| RAG | LlamaIndex | PDF摄入、智能分块、混合检索、重排序 |
| Web Search | DuckDuckGo (ddgs) | 免费实时搜索，Agent 自主决定何时调用 |
| 向量库 | ChromaDB | 本地持久化，双Collection (text+table) |
| Embedding | BGE-M3 (本地) | Apple Silicon MPS 加速，Singleton 单例 |
| LLM | DeepSeek API | deepseek-chat(V3)日常 / deepseek-reasoner(R1)复杂推理 |
| PDF | PyMuPDF4LLM + pdfplumber | 双引擎解析，表格→Markdown |
| 计算 | Python decimal + pandas | Financial Calculator，100%精确 |

## 项目结构

```
SiliconDreams/
├── AGENTS.md              ← 你在这里
├── server.py              # FastAPI 主入口
├── config.py              # 全局配置（环境变量、路径常量）
├── docs/                  # 项目规范文件（宪法）
├── devlog/                # 开发日志（每日自动更新）
├── src/                   # 核心代码
│   ├── llm_client.py      # DeepSeek API
│   ├── pdf_parser.py      # PDF 双引擎
│   ├── chunker.py         # 智能分块
│   ├── embedding_manager.py  # BGE-M3 单例
│   ├── vector_store.py    # ChromaDB
│   ├── retriever.py       # LlamaIndex 检索
│   ├── agent.py           # [DEPRECATED] 旧 LangChain Agent
│   ├── agent_loop.py      # 自定义 Agent Loop（Function Calling）
│   ├── report_generator.py   # 报告生成
│   ├── terminology.py     # 术语管理
│   ├── financial_data.py  # 公司财务数据管理
│   └── tools/             # Agent 工具集
│       ├── web_search.py  # DuckDuckGo 搜索（NEW）
├── templates/             # Jinja2 模板
├── static/                # CSS + JS + 静态资源
├── data/                  # 数据文件（大部分 gitignore）
└── tests/                 # 单元测试
```

## 当前进度

参见 [docs/execution-plan.md](docs/execution-plan.md) 中的状态标记。

开始工作前，读取执行计划确认当前应从哪里继续。
