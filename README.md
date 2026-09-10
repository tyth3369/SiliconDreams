# SiliconDreams — AI Semiconductor Investment Research Analyst

> **Technical Expert + Financial Analyst = Intelligent Investment Research Brain**

A RAG-based AI investment research assistant purpose-built for the semiconductor industry. Solves two key pain points of traditional RAG in financial report scenarios: messy table parsing & insufficient technical terminology understanding.

---

## Core Capabilities

| Capability | Description |
|------------|-------------|
| **Financial Report Parsing** | Dual-engine PDF parsing (PyMuPDF4LLM + pdfplumber), tables 100% preserved as Markdown |
| **Hybrid Retrieval** | Vector similarity + keyword + table-first routing + reranking |
| **Precise Financial Calculation** | 10 financial ratios computed by Python with full precision, zero LLM math — 100% accurate |
| **Terminology Enhancement** | 100+ semiconductor core terms, auto-linked from technology to business impact |
| **ReAct Agent** | 4 tools (search/calculate/compare/technology analysis), autonomous decision-making |
| **Source Traceability** | Every AI-cited data point is clickable back to the original report paragraph |

---

## Architecture

```
FastAPI + HTMX Frontend (theme-adaptive: dark + light)
    |
LangChain ReAct Agent (query routing + tool calling)
    |
LlamaIndex RAG Layer (HyDE + hybrid retrieval + reranking)
    |
ChromaDB Vector Store (text + table dual Collection)
    |
BGE-M3 Embedding (Apple Silicon MPS accelerated)
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | FastAPI + HTMX + Jinja2 (theme-adaptive, SSE streaming) |
| RAG | LlamaIndex (retrieval) + LangChain (Agent) |
| Vector DB | ChromaDB (local persistence) |
| Embedding | BGE-M3 (local, Apple Silicon MPS) |
| LLM | DeepSeek API (V3 + R1) |
| PDF | PyMuPDF4LLM + pdfplumber (dual-engine) |

---

## Quick Start

### Prerequisites

- Python 3.9+ (3.11+ recommended)
- macOS (Apple Silicon for best performance)
- DeepSeek API Key ([free registration](https://platform.deepseek.com))

### Installation

```bash
# 1. Clone
git clone https://github.com/YOUR_USERNAME/SiliconDreams.git
cd SiliconDreams

# 2. Virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure API Key
cp .env.example .env
# Edit .env, fill in DEEPSEEK_API_KEY

# 5. Launch
uvicorn server:app --host 127.0.0.1 --port 8000 --reload
```

### Usage

1. **Upload Reports** -> Sidebar: drag & drop PDF (TSMC / NVIDIA / SMIC annual reports, etc.)
2. **Wait for Indexing** -> Auto parse -> chunk -> vectorize (~30-60 sec per report)
3. **Ask Questions** -> Type in natural language in the chat area
4. **View Sources** -> Click `[source pN]` tags in responses to see original paragraphs

---

## Project Structure

```
SiliconDreams/
├── server.py                  # FastAPI main entry
├── config.py                  # Global configuration
├── CLAUDE.md                  # AI work guide
├── src/
│   ├── i18n.py                # Chinese/English localization
│   ├── llm_client.py          # DeepSeek API client
│   ├── pdf_parser.py          # PDF dual-engine
│   ├── chunker.py             # Smart chunking
│   ├── embedding_manager.py   # BGE-M3 singleton
│   ├── vector_store.py        # ChromaDB management
│   ├── retriever.py           # LlamaIndex retrieval
│   ├── agent.py               # ReAct Agent
│   ├── report_generator.py    # Report templates
│   ├── terminology.py         # Terminology management
│   └── tools/                 # Agent tools
├── templates/                 # Jinja2 HTML templates
├── static/                    # CSS + JS + static assets
├── data/                      # Terminology DB + PDF cache + vector store
├── docs/                      # Project specification docs
├── devlog/                    # Development logs
```

---

## Documentation

| Document | Description |
|----------|-------------|
| [Requirements](docs/requirements.md) | User stories + acceptance criteria |
| [Tech Spec](docs/tech-spec.md) | Architecture design + data flow |
| [Design Spec](docs/design-spec.md) | UI/UX color/font/component specs |
| [Execution Plan](docs/execution-plan.md) | Sprint 0-5 task checklist |
| [API Guide](docs/api-keys-guide.md) | API Key setup guide |
| [Dependencies](docs/dependencies.md) | Complete dependency record |

---

## Important Notes

- **Financial Calculations**: All ratios are computed by Python with full precision; LLM only does narrative polish
- **Investment Advice**: This tool is for research reference only and does NOT constitute investment advice
- **Data Security**: All data is stored locally (ChromaDB + file cache), never uploaded to third parties

---

## Acknowledgments

Built with the support of:

- **Claude** (Anthropic) — AI-assisted design & implementation
- **DeepSeek** — Primary LLM API
- **BGE-M3** (BAAI) — Chinese Embedding model
- **FastAPI** + **HTMX** — Modern Python web framework
- **LlamaIndex** + **LangChain** — RAG & Agent frameworks

---

## License

MIT License — For research and educational use only.
