# SiliconDreams — 技术选型与架构设计

## 技术栈总览

```
┌─────────────────────────────────────────┐
│              展示层 (Presentation)        │
│  FastAPI + HTMX + Jinja2 (Bloomberg 终端风) │
├─────────────────────────────────────────┤
│              Agent 层 (Orchestration)     │
│  LangChain ReAct Agent + Tool Calling    │
├─────────────────────────────────────────┤
│              RAG 层 (Retrieval)           │
│  LlamaIndex + ChromaDB + BGE-M3         │
├─────────────────────────────────────────┤
│              存储层 (Storage)             │
│  ChromaDB (向量) + JSON (术语) + FS (缓存)│
└─────────────────────────────────────────┘
```

## 组件详细设计

### 1. 前端层 — FastAPI + HTMX

**文件**：`server.py`, `templates/index.html`, `templates/components.html`, `static/style.css`, `static/app.js`

**设计决策**：
- 放弃 Streamlit（主题系统不兼容深度定制）→ 改用 FastAPI + HTMX + Jinja2
- Bloomberg 终端风格：暗色 = 纯黑(#000000) + 琥珀(#ffb000)，浅色 = 纯白(#ffffff) + 深蓝(#003d80)
- CSS 变量驱动主题切换：`:root` (暗色默认) + `[data-theme="light"]` (浅色覆盖)
- HTMX 处理动态交互：聊天提交、PDF 上传、侧边栏局部更新
- SSE (Server-Sent Events) 流式输出 LLM token
- Cookie 持久化主题/语言偏好

**状态管理**：
```python
_messages: list[dict]       # 对话历史（内存）
_uploaded_pdfs: list[dict]  # 已上传文件列表
_kb_stats: dict             # 知识库统计 {doc_count, text_chunks, table_chunks}
```

### 2. LLM Client — DeepSeek API

**文件**：`src/llm_client.py`

**模型路由**：
| 任务 | 模型 | 理由 |
|------|------|------|
| 日常对话、报告生成 | `deepseek-chat` (V3) | 快、便宜 |
| 复杂推理、多步分析 | `deepseek-reasoner` (R1) | 推理能力更强 |

**API 封装**：
- 同步调用：基础对话
- 流式调用：聊天界面实时输出
- 重试逻辑：3 次退避重试，处理 API 暂时不可用

### 3. PDF 解析 — 双引擎

**文件**：`src/pdf_parser.py`

```
输入: PDF 文件路径
  ├── 引擎1: PyMuPDF4LLM (主力)
  │   └── PDF → Markdown (表格结构完整保留)
  ├── 引擎2: pdfplumber (辅助)
  │   └── 复杂表格 → DataFrame → Markdown/JSON
  └── 输出: ParsedDocument { text_chunks, table_chunks, metadata }
```

**引擎选择逻辑**：
- 默认使用 PyMuPDF4LLM
- 当 PyMuPDF4LLM 输出的表格格式异常时，自动回退到 pdfplumber 重解析该页
- 判断依据：Markdown 表格的列数/行数是否合理

### 4. Embedding Manager — BGE-M3 单例

**文件**：`src/embedding_manager.py`

```
EmbeddingManager (Singleton)
├── __new__() → 保证全局唯一实例
├── get_model() → 惰性加载
│   ├── device = "mps" (Apple Silicon)
│   └── fallback = "cpu" (Intel Mac / 其他)
└── 单例模式 → 全局唯一实例，应用生命周期内复用
```

**性能预期**：
- 首次加载：5-10 秒（下载/加载 2GB 模型）
- 后续调用：毫秒级（模型已在内存）
- MPS 加速：比 CPU 模式快 3-5x

### 5. 向量存储 — ChromaDB

**文件**：`src/vector_store.py`

**Collection 设计**：
| Collection | 内容 | Chunk 策略 |
|-----------|------|-----------|
| `text_chunks` | 财报正文段落 | chunk_size=512, overlap=64 |
| `table_chunks` | 完整表格 | 一整张表 = 一个 chunk（不切割） |

**元数据 Schema**：
```python
{
    "source": "台积电2024Q4财报.pdf",
    "page": 12,
    "type": "text" | "table",
    "section": "管理层讨论与分析",
    "chunk_id": "t_045",
    "companies": ["台积电", "TSMC"],
    "date": "2024-Q4"
}
```

### 6. 检索器 — LlamaIndex

**文件**：`src/retriever.py`

**检索策略**：
1. **查询扩展**：HyDE (Hypothetical Document Embeddings) — 先用 LLM 生成假设性答案，再用该答案的 embedding 检索
2. **混合检索**：向量相似度 (cosine) + BM25 关键词 → 加权融合
3. **表格优先路由**：检测到财务关键词（营收、毛利率、净利润…）时，提升 `table_chunks` 集合的权重
4. **重排序**：Cross-encoder 对 Top-K 结果二次排序

### 7. Agent 层 — LangChain ReAct

**文件**：`src/agent.py`

**ReAct 循环**：
```
Thought → Action → Observation → ... → Final Answer
```

**工具集**：
| 工具 | 函数 | 强制规则 |
|------|------|---------|
| search_reports | RAG 检索 | — |
| lookup_terminology | 查术语字典 | — |
| financial_calculator | 财务比率计算 | **涉及数字比较必须调用** |
| compare_companies | 多公司对比 | 内部调用 calculator |
| analyze_technology | 技术趋势分析 | 内部调用 terminology |

**查询路由器**：
| 意图 | 路由目标 | 所需工具 |
|------|---------|---------|
| 财务查询 | 财务分析管线 | search + calculator |
| 技术分析 | 技术分析管线 | search + terminology + analyze_technology |
| 行业对比 | 对比管线 | compare_companies + calculator |
| 综合研报 | 完整管线 | 全部工具 |

### 8. Financial Calculator

**文件**：`src/tools/calculator.py`

**设计原则**：LLM 不碰数字。所有计算 100% Python 执行。

**实现**：
```python
from decimal import Decimal  # 金融级精度
import pandas as pd           # 批量计算

class FinancialCalculator:
    @staticmethod
    def yoy_growth(current: float, prior: float) -> dict:
        """同比增长率"""
        result = (current - prior) / prior * 100
        return {
            "result": round(result, 2),
            "formula": f"({current}-{prior})/{prior}*100",
            "interpretation": f"{'上升' if result > 0 else '下降'}{abs(result):.2f}%"
        }
    # ... 其余 9 种比率
```

### 9. 术语知识图谱

**文件**：`data/terminology.json`, `src/terminology.py`

**数据结构**：
```json
{
  "3nm制程": {
    "name_en": "3nm Process Technology",
    "definition": "晶体管栅极宽度约为3纳米的芯片制造工艺...",
    "generation": "先进制程 (≤7nm)",
    "business_impact": "提升芯片性能/能效比，降低单位成本，但初期资本开支巨大",
    "related_companies": ["台积电", "三星", "英特尔"],
    "related_terms": ["EUV光刻", "FinFET", "GAA", "High-NA EUV", "先进封装"]
  }
}
```

**查询增强流程**：
```
用户问题 → 分词 → 匹配术语字典 → 注入定义和商业影响 → 增强后 Prompt → LLM
```

---

## 数据流

```
PDF 上传
  → pdf_parser.py (PyMuPDF4LLM + pdfplumber)
  → chunker.py (文本语义分块 + 表格完整保留)
  → embedding_manager.py (BGE-M3 → 向量)
  → vector_store.py (ChromaDB 双 Collection 存储)
  → [等待用户查询]

用户查询
  → terminology.py (术语增强)
  → retriever.py (HyDE + 混合检索)
  → agent.py (ReAct → 调用工具)
  → calculator.py (如有财务计算)
  → llm_client.py (DeepSeek 生成回答)
  → citation_renderer.py (引用渲染)
  → FastAPI/HTMX 聊天界面 (展示)
```

---

## 安全设计

- `.env` 不入库（`.gitignore` 排除）
- `.github_token` 不入库
- `data/pdfs/`, `data/chroma_db/` 不入库（含敏感财报数据）
- API Key 仅存在于本地 `.env` 文件
