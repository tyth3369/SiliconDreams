"""
SiliconDreams — FastAPI Server (v0.6.0)
=======================================
Electronics / Semiconductor AI Investment Research Analyst.
FastAPI + HTMX + Jinja2 + SSE streaming + Agent-driven tool calling.
"""
from __future__ import annotations

import warnings
warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL")

import json
import uuid
import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, Form, UploadFile, File, Cookie, Depends
from fastapi.responses import HTMLResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape

from config import AppConfig, LLMConfig
from src.i18n import I18n, _ZH, _EN
from src.llm_client import llm_available, get_llm
from src.citation import CitationTracker
from src.agent_loop import run_agent_loop, build_simple_context

logger = logging.getLogger(__name__)

# ── App setup ──────────────────────────────────────────
app = FastAPI(title="SiliconDreams", version="0.6.0")

BASE_DIR = Path(__file__).parent
TEMPLATES = BASE_DIR / "templates"
STATIC = BASE_DIR / "static"

app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

jinja = Environment(
    loader=FileSystemLoader(str(TEMPLATES)),
    autoescape=select_autoescape(["html"]),
)


# ── I18n dependency ────────────────────────────────────
async def get_lang(lang: Optional[str] = Cookie(default=None)) -> str:
    """Read language preference from cookie, default to 'zh'."""
    if lang in ("zh", "en"):
        return lang
    return "zh"


def get_t(lang: str):
    """Return a translation function for the given language."""
    i18n = I18n(lang=lang)
    return i18n.t


# ── In-memory storage (single-user) ────────────────────
_messages: list[dict] = []  # [{role, content, citations}]
_uploaded_pdfs: list[dict] = []  # [{name, size}]
_kb_stats: dict = {"doc_count": 0, "text_chunks": 0, "table_chunks": 0}

PRESET_PROMPTS = {
    "compare": {
        "zh": "请对已上传的财报进行行业对比分析，重点关注：毛利率、净利率、ROE、研发投入比的横向对比。",
        "en": "Please perform a peer comparison analysis on the uploaded reports, focusing on: gross margin, net margin, ROE, and R&D intensity across companies.",
    },
    "tech_trend": {
        "zh": "请分析当前半导体行业的核心技术趋势，结合已上传财报中的相关数据说明其对公司的财务影响。",
        "en": "Please analyze key technology trends in the semiconductor industry, using data from uploaded reports to explain financial impact on companies.",
    },
    "finance": {
        "zh": "请对已上传的最新财报进行深度财务分析：营收结构、盈利能力、偿债能力、运营效率，并计算关键财务比率。",
        "en": "Please perform a deep financial analysis on the latest uploaded report: revenue structure, profitability, solvency, operational efficiency, and compute key financial ratios.",
    },
}


def _update_kb_stats():
    """Refresh KB stats from vector store."""
    try:
        from src.vector_store import VectorStore
        store = VectorStore()
        stats = store.get_stats()
        _kb_stats.update(stats)
    except Exception:
        pass


def _build_session_messages(lang: str) -> list[dict]:
    """Build messages list from session history with system prompt."""
    messages = [{"role": "system", "content": AppConfig.get_system_prompt(lang)}]
    for m in _messages:
        messages.append({"role": m["role"], "content": m["content"]})
    return messages


def _stream_tokens_with_capture(generator, _messages: list):
    """Wrap an SSE generator to capture token events and store final response."""
    full_response = ""
    for sse_str in generator:
        # Try to extract token content from SSE data
        if '"token":' in sse_str:
            try:
                # Parse "data: {...}\n\n" format
                data_str = sse_str.strip()
                if data_str.startswith("data: "):
                    data_str = data_str[6:]
                data = json.loads(data_str)
                full_response += data.get("token", "")
            except (json.JSONDecodeError, KeyError):
                pass
        yield sse_str

    if full_response.strip():
        _messages.append({"role": "assistant", "content": full_response})


# ═══════════════════════════════════════════════════════
# Routes
# ═══════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def index(lang: str = Depends(get_lang)):
    """Main page."""
    t = get_t(lang)
    _update_kb_stats()
    online = llm_available()
    return jinja.get_template("index.html").render(
        t=t, lang=lang,
        messages=_messages,
        uploaded_pdfs=_uploaded_pdfs,
        kb_stats=_kb_stats,
        llm_online=online,
        preset_prompts=PRESET_PROMPTS,
        _ZH=_ZH,
        _EN=_EN,
    )


# ── Pending agent configs for SSE streaming ──────────────
# Stores per-message agent config before SSE picks it up.
# Format: {msg_id: {"query": str, "lang": str, "tracker": CitationTracker}}
_pending_agent_configs: dict[str, dict] = {}


@app.post("/chat", response_class=HTMLResponse)
async def chat(
    message: str = Form(...),
    lang: str = Depends(get_lang),
):
    """Receive a user message, store it, return updated chat HTML + trigger SSE."""
    t = get_t(lang)
    msg_id = str(uuid.uuid4())[:8]

    _messages.append({"role": "user", "content": message, "id": msg_id})

    # Initialize citation tracker for this message
    tracker = CitationTracker()

    # Store config for SSE pickup
    _pending_agent_configs[msg_id] = {
        "query": message,
        "lang": lang,
        "tracker": tracker,
    }

    # Return the user message HTML + an empty assistant div with SSE trigger
    assistant_id = str(uuid.uuid4())[:8]
    return jinja.get_template("components.html").render(
        component="chat_response",
        t=t, lang=lang,
        user_msg=message,
        assistant_id=assistant_id,
        msg_id=msg_id,
        messages=_messages,
        uploaded_pdfs=_uploaded_pdfs,
        kb_stats=_kb_stats,
        llm_online=llm_available(),
        preset_prompts=PRESET_PROMPTS,
    )


@app.get("/chat/stream/{msg_id}")
async def chat_stream(msg_id: str, lang: str = Depends(get_lang)):
    """SSE endpoint: run Agent Loop (V3) or fallback (R1), stream results."""
    t = get_t(lang)

    # Wait for /chat to store config (up to 3 seconds)
    agent_config = None
    for _ in range(30):
        agent_config = _pending_agent_configs.pop(msg_id, None)
        if agent_config is not None:
            break
        await asyncio.sleep(0.1)

    async def generate():
        if agent_config is None:
            yield f"data: {json.dumps({'error': t('error.llm_failed') + ' — chat request not found'})}\n\n"
            return

        if not llm_available():
            yield f"data: {json.dumps({'error': t('error.llm_not_configured')})}\n\n"
            return

        try:
            client = get_llm()
            tracker: CitationTracker = agent_config["tracker"]
            query: str = agent_config["query"]
            _lang: str = agent_config["lang"]

            # Build conversation messages from session history
            session_messages = _build_session_messages(_lang)

            # Decide: Agent Loop (V3) or Fallback (R1)
            use_agent = client.model != client.reasoner_model

            if use_agent:
                # ── Agent Loop (V3) ──────────────────────
                agent_gen = run_agent_loop(
                    client=client,
                    messages=session_messages,
                    tracker=tracker,
                    lang=_lang,
                )
                for sse_str in _stream_tokens_with_capture(agent_gen, _messages):
                    yield sse_str
                    await asyncio.sleep(0)
            else:
                # ── Fallback (R1 or no tool support) ─────
                yield f"data: {json.dumps({'status': 'info', 'label': 'R1 深度推理模式（无工具调用）'})}\n\n"

                # Inject local knowledge context manually
                extra_messages = build_simple_context(query, _lang, tracker)
                api_messages = extra_messages + session_messages

                full_response = ""
                for token in client.chat_stream(messages=api_messages):
                    full_response += token
                    yield f"data: {json.dumps({'token': token})}\n\n"
                    await asyncio.sleep(0)

                _messages.append({"role": "assistant", "content": full_response})

                # Emit citations BEFORE done (so client processes them before ES close)
                if not tracker.is_empty():
                    citations = tracker.to_list()
                    panel_html = CitationTracker.format_panel(citations, lang=_lang)
                    yield f"data: {json.dumps({'citations': citations, 'panel_html': panel_html})}\n\n"

                yield f"data: {json.dumps({'done': True})}\n\n"

        except Exception as e:
            error_msg = f"{t('error.llm_failed')}: {e}"
            logger.error(f"Agent SSE 异常: {e}", exc_info=True)
            yield f"data: {json.dumps({'error': error_msg})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/upload", response_class=HTMLResponse)
async def upload_pdf(
    file: UploadFile = File(...),
    lang: str = Depends(get_lang),
):
    """Handle PDF upload: save → parse → chunk → vectorize."""
    t = get_t(lang)

    if not file.filename or not file.filename.endswith(".pdf"):
        return f"<p>{t('error.pdf_failed')}: not a PDF</p>"

    if file.size and file.size > 50 * 1024 * 1024:
        return f"<p>{t('sidebar.upload_error_size')}</p>"

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name

        from src.pdf_parser import parse_pdf
        doc = parse_pdf(tmp_path)

        from src.chunker import chunk_document
        chunks = chunk_document(doc)

        from src.vector_store import VectorStore
        store = VectorStore()
        store.add_chunks(chunks)

        Path(tmp_path).unlink(missing_ok=True)

        _uploaded_pdfs.append({
            "name": file.filename,
            "size": round(len(content) / 1024 / 1024, 1),
        })
        _update_kb_stats()

    except Exception as e:
        return f"<p>{t('error.pdf_failed')}: {e}</p>"

    return jinja.get_template("components.html").render(
        component="sidebar_content",
        t=t, lang=lang,
        uploaded_pdfs=_uploaded_pdfs,
        kb_stats=_kb_stats,
        llm_online=llm_available(),
        preset_prompts=PRESET_PROMPTS,
    )


@app.get("/stats", response_class=HTMLResponse)
async def stats(lang: str = Depends(get_lang)):
    """Return KB stats partial."""
    t = get_t(lang)
    _update_kb_stats()
    return jinja.get_template("components.html").render(
        component="kb_stats",
        t=t, lang=lang,
        kb_stats=_kb_stats,
    )


@app.post("/quick/{action}", response_class=HTMLResponse)
async def quick_action(action: str, lang: str = Depends(get_lang)):
    """Trigger a quick action preset prompt."""
    t = get_t(lang)
    prompt = PRESET_PROMPTS.get(action, {}).get(lang, "")
    if not prompt:
        return ""

    msg_id = str(uuid.uuid4())[:8]
    _messages.append({"role": "user", "content": prompt, "id": msg_id})

    tracker = CitationTracker()

    # Store config for SSE pickup
    _pending_agent_configs[msg_id] = {
        "query": prompt,
        "lang": lang,
        "tracker": tracker,
    }

    assistant_id = str(uuid.uuid4())[:8]
    return jinja.get_template("components.html").render(
        component="chat_response",
        t=t, lang=lang,
        user_msg=prompt,
        assistant_id=assistant_id,
        msg_id=msg_id,
        messages=_messages,
        uploaded_pdfs=_uploaded_pdfs,
        kb_stats=_kb_stats,
        llm_online=llm_available(),
        preset_prompts=PRESET_PROMPTS,
    )


@app.post("/theme")
async def set_theme(theme: str = Form(...)):
    """Set theme cookie."""
    response = Response(status_code=204)
    response.set_cookie(key="theme", value=theme, max_age=365 * 24 * 3600)
    return response


@app.post("/lang")
async def set_lang(lang: str = Form(...)):
    """Set language cookie and reload page."""
    response = Response(status_code=204)
    response.set_cookie(key="lang", value=lang, max_age=365 * 24 * 3600)
    return response


@app.get("/sidebar", response_class=HTMLResponse)
async def get_sidebar(request: Request):
    """Return sidebar HTML in the requested language (for HTMX language switch)."""
    # Accept lang via query param (preferred) or cookie (fallback)
    lang = request.query_params.get("lang")
    if lang not in ("zh", "en"):
        lang = request.cookies.get("lang", "zh")
    t = get_t(lang)
    _update_kb_stats()
    return jinja.get_template("components.html").render(
        t=t, lang=lang,
        component="sidebar_content",
        uploaded_pdfs=_uploaded_pdfs,
        kb_stats=_kb_stats,
    )


# ── Startup ────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    _update_kb_stats()
    uvicorn.run(app, host="127.0.0.1", port=8000)
