"""
SiliconDreams — FastAPI Server (v1.0.0-rc.6)
=======================================
Electronics / Semiconductor AI Investment Research Analyst.
FastAPI + HTMX + Jinja2 + SSE streaming + Agent-driven tool calling.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import Cookie, Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape

from config import PDF_DIR, AppConfig, LLMConfig, SearchConfig, SecurityConfig
from src.agent_loop import run_agent_loop
from src.analysis_templates import default_foundry_comparison_prompt
from src.analytics import build_watchlist_timeline, load_analytics_payload
from src.citation import CitationTracker
from src.exporter import build_markdown_export, build_pdf_export, export_filename
from src.financial_data import FinancialDataManager
from src.i18n import _EN, _ZH, I18n
from src.ingestion_jobs import IngestionWorker
from src.llm_client import get_llm, llm_available
from src.observability import RunTelemetry
from src.security import SecurityManager, SlidingWindowLimiter, verify_password
from src.storage import Database

logger = logging.getLogger(__name__)


# ── App setup ──────────────────────────────────────────
@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Recover durable ingestion work and stop the local worker cleanly."""
    SecurityConfig.validate()
    _ingestion_worker.start(recover=True)
    yield
    _ingestion_worker.stop()


app = FastAPI(title="SiliconDreams", version=AppConfig.version, lifespan=lifespan)

BASE_DIR = Path(__file__).parent
TEMPLATES = BASE_DIR / "templates"
STATIC = BASE_DIR / "static"

app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

jinja = Environment(
    loader=FileSystemLoader(str(TEMPLATES)),
    autoescape=select_autoescape(["html"]),
)
jinja.globals["auth_enabled"] = SecurityConfig.auth_enabled

_security = SecurityManager(
    SecurityConfig.session_secret or "silicondreams-local-development-secret",
    SecurityConfig.session_ttl_seconds,
)
_rate_limiter = SlidingWindowLimiter()
SESSION_COOKIE = "sd_session"
CSRF_COOKIE = "sd_csrf"
PUBLIC_PATHS = {"/healthz", "/readyz", "/login"}


def _client_address(request: Request) -> str:
    if SecurityConfig.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
        if forwarded:
            return forwarded
    return request.client.host if request.client else "unknown"


def _set_cookie(response: Response, key: str, value: str, **kwargs) -> None:
    response.set_cookie(key, value, secure=SecurityConfig.cookie_secure, **kwargs)


def _audit_request(request: Request, status_code: int, outcome: str | None = None) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    session = getattr(request.state, "auth_session", None)
    route = request.scope.get("route")
    route_path = getattr(route, "path", request.url.path)
    resolved_outcome = outcome or (
        "success" if status_code < 400 else "denied" if status_code in {401, 403, 429} else "error"
    )
    try:
        _db.add_audit_event(
            request_id=request.state.request_id,
            actor=session.username if session else "anonymous",
            action=f"{request.method} {route_path}",
            outcome=resolved_outcome,
            target_type="http_route",
            target_id=request.url.path[:500],
            client_hash=_security.hash_identifier(_client_address(request)),
            metadata={"status_code": status_code},
        )
    except Exception:
        logger.exception("Failed to append security audit event")


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Authenticate, enforce CSRF/rate limits, audit mutations, and apply CSP."""
    request.state.request_id = uuid.uuid4().hex
    request.state.csp_nonce = secrets.token_urlsafe(18)
    request.state.auth_session = _security.verify_session(request.cookies.get(SESSION_COOKIE))
    path = request.url.path
    is_public = path.startswith("/static/") or path in PUBLIC_PATHS

    response: Response | None = None
    if (
        SecurityConfig.rate_limit_enabled
        and not path.startswith("/static/")
        and path not in {"/healthz", "/readyz"}
    ):
        session = request.state.auth_session
        identity = session.session_id if session else _client_address(request)
        if path == "/login" and request.method == "POST":
            bucket, limit, window = "login", SecurityConfig.login_attempts_per_5_minutes, 300
        elif path == "/chat" or path.startswith("/quick/"):
            bucket, limit, window = "ai", SecurityConfig.ai_limit_per_minute, 60
        else:
            bucket, limit, window = "request", SecurityConfig.request_limit_per_minute, 60
        allowed, retry_after = _rate_limiter.allow(
            f"{bucket}:{identity}", limit=limit, window_seconds=window
        )
        if not allowed:
            response = Response(
                "Too Many Requests", status_code=429, headers={"Retry-After": str(retry_after)}
            )

    if response is None and SecurityConfig.auth_enabled and not is_public:
        session = request.state.auth_session
        if session is None:
            if request.headers.get("HX-Request") == "true":
                response = Response(status_code=401, headers={"HX-Redirect": "/login"})
            else:
                response = RedirectResponse("/login", status_code=303)
        elif request.method not in {"GET", "HEAD", "OPTIONS"}:
            header_token = request.headers.get("X-CSRF-Token")
            cookie_token = request.cookies.get(CSRF_COOKIE)
            if (
                not header_token
                or not hmac.compare_digest(header_token, cookie_token or "")
                or not _security.verify_csrf(header_token, session.session_id)
            ):
                response = Response("CSRF validation failed", status_code=403)

    if response is None:
        try:
            response = await call_next(request)
        except Exception:
            _audit_request(request, 500, outcome="error")
            raise

    _audit_request(request, response.status_code)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    response.headers.setdefault("X-Request-ID", request.state.request_id)
    if SecurityConfig.cookie_secure:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        f"script-src 'self' 'nonce-{request.state.csp_nonce}'; "
        "style-src 'self'; font-src 'self'; "
        "connect-src 'self'; img-src 'self' data:; object-src 'none'; "
        "base-uri 'self'; frame-ancestors 'none'; form-action 'self'",
    )
    return response


# ── I18n dependency ────────────────────────────────────
async def get_lang(lang: str | None = Cookie(default=None)) -> str:
    """Read language preference from cookie, default to 'zh'."""
    if lang in ("zh", "en"):
        return lang
    return "zh"


def get_t(lang: str):
    """Return a translation function for the given language."""
    i18n = I18n(lang=lang)
    return i18n.t


# ── Persistent storage + transient UI state ────────────
_db = Database()
FinancialDataManager().sync_to_database(_db)
_uploaded_pdfs: list[dict] = []  # [{name, size}]
_kb_stats: dict = {"doc_count": 0, "text_chunks": 0, "table_chunks": 0}

PRESET_PROMPTS = {
    "compare": {
        "zh": default_foundry_comparison_prompt("zh"),
        "en": default_foundry_comparison_prompt("en"),
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


def _refresh_uploaded_pdfs() -> None:
    active_jobs = {}
    for job in _db.list_jobs(job_type=IngestionWorker.JOB_TYPE, limit=100):
        document_id = job["payload"].get("document_id")
        if document_id and document_id not in active_jobs:
            active_jobs[document_id] = job
    _uploaded_pdfs.clear()
    for document in _db.list_documents(limit=100):
        path = Path(document["stored_path"])
        size_mb = round(path.stat().st_size / 1024 / 1024, 1) if path.exists() else 0.0
        job = active_jobs.get(document["id"])
        result = job["result"] if job else {}
        _uploaded_pdfs.append(
            {
                "name": document["original_filename"],
                "size": size_mb,
                "status": document["parse_status"],
                "job_id": job["id"] if job else "",
                "job_status": job["status"] if job else "",
                "stage": result.get("stage", document["parse_status"]),
                "progress": result.get(
                    "progress", 100 if document["parse_status"] == "ready" else 0
                ),
                "error": (job.get("error") if job else document.get("parse_error")) or "",
            }
        )


def _ensure_conversation(conversation_id: str | None, lang: str) -> str:
    if conversation_id and _db.conversation_exists(conversation_id):
        return conversation_id
    return _db.create_conversation(language=lang)


def _conversation_messages(conversation_id: str, lang: str) -> list[dict]:
    messages = _db.list_messages(conversation_id)
    for message in messages:
        if message["role"] == "assistant" and message.get("citations"):
            message["panel_html"] = CitationTracker.format_panel(message["citations"], lang=lang)
    return messages


def _conversation_summaries(lang: str) -> list[dict]:
    """Return active conversations with a localized fallback title."""
    fallback = "新研究" if lang == "zh" else "New research"
    conversations = _db.list_conversations(limit=20)
    for conversation in conversations:
        conversation["display_title"] = conversation["title"] or fallback
    return conversations


def _archived_conversation_summaries(lang: str) -> list[dict]:
    fallback = "未命名研究" if lang == "zh" else "Untitled research"
    conversations = [
        item
        for item in _db.list_conversations(include_archived=True, limit=30)
        if item["archived_at"]
    ]
    for conversation in conversations:
        conversation["display_title"] = conversation["title"] or fallback
    return conversations


def _build_session_messages(lang: str, conversation_id: str) -> list[dict]:
    """Build messages list from session history with system prompt."""
    today = date.today().isoformat()
    date_rule = (
        f"当前日期为 {today}。涉及‘最新’或时间线时，以此日期为上限并优先采用有发布日期的证据。"
        if lang == "zh"
        else f"Current date: {today}. For latest-status queries, do not go beyond this date and prefer dated evidence."
    )
    messages = [
        {"role": "system", "content": f"{AppConfig.get_system_prompt(lang)}\n\n{date_rule}"}
    ]
    # Bound model context while retaining full history in SQLite/UI.
    for m in _db.list_messages(conversation_id, limit=24):
        messages.append({"role": m["role"], "content": m["content"]})
    return messages


def _available_retrieval_tools() -> set[str]:
    """Do not advertise unavailable evidence paths to the planner."""
    names = {"lookup_terms", "get_company_data"}
    if SearchConfig.is_configured():
        names.add("web_search")
    if _db.count("documents") > 0:
        names.add("search_reports")
    return names


def _stream_tokens_with_capture(generator, conversation_id: str, tracker: CitationTracker):
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
        _db.add_message(
            conversation_id,
            "assistant",
            full_response,
            citations=tracker.to_list(),
        )


# ═══════════════════════════════════════════════════════
# Routes
# ═══════════════════════════════════════════════════════


@app.get("/healthz")
async def healthz():
    """Lightweight container/orchestrator health probe."""
    return {"status": "ok", "version": AppConfig.version}


@app.get("/readyz")
async def readyz():
    """Fail closed until database, providers, and pinned local models are ready."""
    from src.model_artifacts import BGE_M3_MANIFEST, RERANKER_MANIFEST, model_cache_status

    checks = {
        "database": False,
        "llm": LLMConfig.is_configured(),
        "web_search": SearchConfig.is_configured(),
        "embedding_model": model_cache_status(BGE_M3_MANIFEST)[0],
        "reranker_model": model_cache_status(RERANKER_MANIFEST)[0],
    }
    try:
        with _db.connect() as connection:
            checks["database"] = connection.execute("SELECT 1").fetchone()[0] == 1
    except Exception:
        logger.exception("Readiness database check failed")

    ready = all(checks.values())
    payload = {
        "status": "ready" if ready else "not_ready",
        "version": AppConfig.version,
        "checks": checks,
    }
    return JSONResponse(payload, status_code=200 if ready else 503)


@app.get("/ops/metrics")
async def operations_metrics(hours: int = 24):
    """Return authenticated aggregate AI operations metrics without research content."""
    return _db.observability_summary(hours=hours)


def _render_login(request: Request, lang: str, csrf_token: str, error: str = "") -> HTMLResponse:
    t = get_t(lang)
    content = jinja.get_template("login.html").render(
        lang=lang,
        t=t,
        csp_nonce=request.state.csp_nonce,
        csrf_token=csrf_token,
        error=error,
    )
    response = HTMLResponse(content, status_code=401 if error else 200)
    _set_cookie(
        response,
        CSRF_COOKIE,
        csrf_token,
        max_age=600,
        httponly=False,
        samesite="strict",
    )
    return response


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, lang: str = Depends(get_lang)):
    if not SecurityConfig.auth_enabled:
        return RedirectResponse("/", status_code=303)
    if request.state.auth_session is not None:
        return RedirectResponse("/", status_code=303)
    return _render_login(request, lang, _security.issue_csrf("login"))


@app.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    username: Annotated[str, Form(max_length=120)],
    password: Annotated[str, Form(max_length=500)],
    csrf_token: Annotated[str, Form(max_length=500)],
    lang: str = Depends(get_lang),
):
    cookie_token = request.cookies.get(CSRF_COOKIE, "")
    csrf_valid = hmac.compare_digest(csrf_token, cookie_token) and _security.verify_csrf(
        csrf_token, "login"
    )
    username_valid = hmac.compare_digest(username, SecurityConfig.username)
    password_valid = verify_password(password, SecurityConfig.password_hash)
    if not csrf_valid or not username_valid or not password_valid:
        return _render_login(
            request,
            lang,
            _security.issue_csrf("login"),
            get_t(lang)("auth.invalid"),
        )

    session_token = _security.issue_session(SecurityConfig.username)
    session = _security.verify_session(session_token)
    request.state.auth_session = session
    response = RedirectResponse("/", status_code=303)
    _set_cookie(
        response,
        SESSION_COOKIE,
        session_token,
        max_age=SecurityConfig.session_ttl_seconds,
        httponly=True,
        samesite="lax",
    )
    _set_cookie(
        response,
        CSRF_COOKIE,
        _security.issue_csrf(session.session_id),
        max_age=SecurityConfig.session_ttl_seconds,
        httponly=False,
        samesite="strict",
    )
    return response


@app.post("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return response


@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    lang: str = Depends(get_lang),
    conversation_id: Annotated[str | None, Cookie()] = None,
):
    """Main page."""
    t = get_t(lang)
    _update_kb_stats()
    _refresh_uploaded_pdfs()
    online = llm_available()
    active_conversation = _ensure_conversation(conversation_id, lang)
    csrf_token = request.cookies.get(CSRF_COOKIE, "")
    session = request.state.auth_session
    refresh_csrf = bool(
        SecurityConfig.auth_enabled
        and session
        and not _security.verify_csrf(csrf_token, session.session_id)
    )
    if refresh_csrf:
        csrf_token = _security.issue_csrf(session.session_id)
    content = jinja.get_template("index.html").render(
        request=request,
        t=t,
        lang=lang,
        messages=_conversation_messages(active_conversation, lang),
        uploaded_pdfs=_uploaded_pdfs,
        kb_stats=_kb_stats,
        llm_online=online,
        preset_prompts=PRESET_PROMPTS,
        conversations=_conversation_summaries(lang),
        archived_conversations=_archived_conversation_summaries(lang),
        active_conversation=active_conversation,
        csp_nonce=request.state.csp_nonce,
        csrf_token=csrf_token,
        auth_enabled=SecurityConfig.auth_enabled,
        _ZH=_ZH,
        _EN=_EN,
    )
    response = HTMLResponse(content)
    if refresh_csrf:
        _set_cookie(
            response,
            CSRF_COOKIE,
            csrf_token,
            max_age=SecurityConfig.session_ttl_seconds,
            httponly=False,
            samesite="strict",
        )
    if active_conversation != conversation_id:
        _set_cookie(
            response,
            "conversation_id",
            active_conversation,
            max_age=365 * 24 * 3600,
            httponly=True,
            samesite="lax",
        )
    return response


# ── Pending agent configs for SSE streaming ──────────────
# Stores per-message agent config before SSE picks it up.
# Format: {msg_id: {"query": str, "lang": str, "tracker": CitationTracker}}
_pending_agent_configs: dict[str, dict] = {}
_PENDING_TTL_SECONDS = 60.0
_MAX_PENDING_REQUESTS = 128
_STREAM_END = object()


def _prune_pending_requests() -> None:
    """Bound transient SSE hand-off state if a browser never opens its stream."""
    cutoff = time.monotonic() - _PENDING_TTL_SECONDS
    expired = [
        key
        for key, value in _pending_agent_configs.items()
        if float(value.get("created_at", 0.0)) < cutoff
    ]
    for key in expired:
        config = _pending_agent_configs.pop(key, None)
        if config:
            _persist_agent_run(config, status="cancelled")
    if len(_pending_agent_configs) >= _MAX_PENDING_REQUESTS:
        oldest = min(
            _pending_agent_configs,
            key=lambda key: float(_pending_agent_configs[key].get("created_at", 0.0)),
        )
        config = _pending_agent_configs.pop(oldest, None)
        if config:
            _persist_agent_run(config, status="cancelled")


def _persist_agent_run(config: dict, *, status: str | None = None) -> None:
    """Finalize one aggregate run without persisting prompts, answers, or source names."""
    telemetry: RunTelemetry | None = config.get("telemetry")
    tracker: CitationTracker | None = config.get("tracker")
    if telemetry is None or config.get("telemetry_persisted"):
        return
    config["telemetry_persisted"] = True
    try:
        _db.add_ai_run(telemetry.finish(tracker.to_list() if tracker else [], status=status))
    except Exception:
        logger.exception("Failed to persist AI request telemetry")


def _next_stream_item(iterator):
    """Advance a blocking generator without leaking StopIteration through a Future."""
    try:
        return next(iterator)
    except StopIteration:
        return _STREAM_END


def _ingest_pdf_sync(
    *,
    original_filename: str,
    stored_path: Path,
    source_id: str,
    document_id: str,
    progress_callback=None,
) -> dict:
    """Run CPU/model-heavy PDF ingestion outside the ASGI event loop."""
    if progress_callback:
        progress_callback("parsing", 10)

    from src.pdf_parser import parse_pdf

    doc = parse_pdf(stored_path, original_filename=original_filename)
    if progress_callback:
        progress_callback("chunking", 35, {"page_count": doc.total_pages})

    from src.chunker import chunk_document

    chunks = chunk_document(doc)
    if progress_callback:
        progress_callback("persisting", 50, {"chunk_count": len(chunks)})
    for chunk in chunks:
        database_chunk_id = _db.add_chunk(
            document_id=document_id,
            source_id=source_id,
            page=max(1, chunk.page),
            chunk_type=chunk.chunk_type,
            text=chunk.text,
            section=chunk.section,
            metadata=chunk.metadata,
        )
        chunk.chunk_id = database_chunk_id
        chunk.metadata.update(
            {"document_id": document_id, "source_id": source_id, "vector_id": database_chunk_id}
        )

    from src.vector_store import VectorStore

    if progress_callback:
        progress_callback("indexing", 70, {"chunk_count": len(chunks)})
    VectorStore().add_chunks(chunks)
    _db.set_document_status(
        document_id,
        "ready",
        page_count=doc.total_pages,
        error="; ".join(doc.parse_errors) or None,
    )
    return {
        "stage": "completed",
        "progress": 100,
        "page_count": doc.total_pages,
        "chunk_count": len(chunks),
    }


def _process_ingestion_job(job: dict) -> dict:
    """Resolve a persisted job payload and update durable progress checkpoints."""
    payload = job["payload"]
    job_id = job["id"]
    document_id = payload["document_id"]

    def report(stage: str, progress: int, detail: dict | None = None) -> None:
        _db.update_job_progress(job_id, stage=stage, progress=progress, detail=detail)

    try:
        return _ingest_pdf_sync(
            original_filename=payload["original_filename"],
            stored_path=Path(payload["stored_path"]),
            source_id=payload["source_id"],
            document_id=document_id,
            progress_callback=report,
        )
    except Exception as exc:
        _db.set_document_status(document_id, "failed", error=str(exc))
        raise


_ingestion_worker = IngestionWorker(lambda: _db, _process_ingestion_job)


@app.post("/chat", response_class=HTMLResponse)
async def chat(
    request: Request,
    message: Annotated[str, Form(min_length=1, max_length=4000)],
    lang: str = Depends(get_lang),
    conversation_id: Annotated[str | None, Cookie()] = None,
):
    """Receive a user message, store it, return updated chat HTML + trigger SSE."""
    t = get_t(lang)
    msg_id = str(uuid.uuid4())[:8]
    message = message.strip()
    if not message:
        return HTMLResponse("", status_code=400)

    active_conversation = _ensure_conversation(conversation_id, lang)
    _db.add_message(active_conversation, "user", message)

    # Initialize citation tracker for this message
    tracker = CitationTracker()

    # Store config for SSE pickup
    _prune_pending_requests()
    _pending_agent_configs[msg_id] = {
        "query": message,
        "lang": lang,
        "tracker": tracker,
        "conversation_id": active_conversation,
        "created_at": time.monotonic(),
        "telemetry": RunTelemetry(
            request_id=request.state.request_id,
            conversation_id=active_conversation,
            provider=LLMConfig.provider,
            model=LLMConfig.model,
        ),
    }

    # Return the user message HTML + an empty assistant div with SSE trigger
    assistant_id = str(uuid.uuid4())[:8]
    content = jinja.get_template("components.html").render(
        component="chat_response",
        t=t,
        lang=lang,
        user_msg=message,
        assistant_id=assistant_id,
        msg_id=msg_id,
        messages=_db.list_messages(active_conversation),
        uploaded_pdfs=_uploaded_pdfs,
        kb_stats=_kb_stats,
        llm_online=llm_available(),
        preset_prompts=PRESET_PROMPTS,
        conversations=_conversation_summaries(lang),
        archived_conversations=_archived_conversation_summaries(lang),
        active_conversation=active_conversation,
    )
    response = HTMLResponse(content)
    if active_conversation != conversation_id:
        _set_cookie(
            response,
            "conversation_id",
            active_conversation,
            max_age=365 * 24 * 3600,
            httponly=True,
            samesite="lax",
        )
    return response


@app.get("/chat/stream/{msg_id}")
async def chat_stream(msg_id: str, lang: str = Depends(get_lang)):
    """Run the bounded Agent pipeline and stream its events over SSE."""
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
            telemetry: RunTelemetry = agent_config["telemetry"]
            telemetry.fail("llm_not_configured")
            _persist_agent_run(agent_config, status="error")
            yield f"data: {json.dumps({'error': t('error.llm_not_configured')})}\n\n"
            return

        final_status: str | None = "cancelled"
        try:
            client = get_llm()
            tracker: CitationTracker = agent_config["tracker"]
            _lang: str = agent_config["lang"]
            conversation_id: str = agent_config["conversation_id"]

            # Build conversation messages from session history
            session_messages = _build_session_messages(_lang, conversation_id)

            agent_gen = run_agent_loop(
                client=client,
                messages=session_messages,
                tracker=tracker,
                lang=_lang,
                available_retrieval_tools=_available_retrieval_tools(),
                telemetry=agent_config["telemetry"],
            )
            stream = iter(_stream_tokens_with_capture(agent_gen, conversation_id, tracker))
            while True:
                # LLM calls, embedding inference, reranking, and web requests are
                # synchronous. Advance each generator step in a worker thread so
                # one research request cannot freeze FastAPI's event loop.
                sse_str = await asyncio.to_thread(_next_stream_item, stream)
                if sse_str is _STREAM_END:
                    break
                yield sse_str
            final_status = None

        except Exception as e:
            final_status = "error"
            agent_config["telemetry"].fail("agent_stream_failed")
            error_msg = f"{t('error.llm_failed')}: {e}"
            logger.error(f"Agent SSE 异常: {e}", exc_info=True)
            yield f"data: {json.dumps({'error': error_msg})}\n\n"
        finally:
            _persist_agent_run(agent_config, status=final_status)

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
    file: Annotated[UploadFile, File()],
    lang: str = Depends(get_lang),
    conversation_id: Annotated[str | None, Cookie()] = None,
):
    """Validate and persist a PDF, then enqueue durable background ingestion."""
    t = get_t(lang)

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        return f"<p>{t('error.pdf_failed')}: not a PDF</p>"

    max_bytes = AppConfig.max_upload_size_mb * 1024 * 1024
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        return f"<p>{t('sidebar.upload_error_size')}</p>"
    if not content.startswith(b"%PDF-"):
        return f"<p>{t('error.pdf_failed')}: invalid PDF signature</p>"

    original_filename = Path(file.filename).name
    safe_filename = re.sub(r"[^\w. -]", "_", original_filename).strip() or "document.pdf"
    digest = hashlib.sha256(content).hexdigest()
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    stored_path = PDF_DIR / f"{digest[:16]}-{safe_filename}"
    existing = _db.get_document_by_sha256(digest)
    if existing and existing["parse_status"] == "ready":
        _refresh_uploaded_pdfs()
        _update_kb_stats()
        return jinja.get_template("components.html").render(
            component="sidebar_content",
            t=t,
            lang=lang,
            uploaded_pdfs=_uploaded_pdfs,
            kb_stats=_kb_stats,
            conversations=_conversation_summaries(lang),
            archived_conversations=_archived_conversation_summaries(lang),
            active_conversation=conversation_id,
        )

    await asyncio.to_thread(stored_path.write_bytes, content)
    source_id = _db.upsert_source(
        source_type="document",
        title=original_filename,
        content_hash=digest,
        trust_tier=1,
        metadata={"upload_type": "user_pdf"},
    )
    document_id = _db.upsert_document(
        source_id=source_id,
        original_filename=original_filename,
        stored_path=str(stored_path),
        sha256=digest,
        parse_status="pending",
    )
    _db.enqueue_job(
        IngestionWorker.JOB_TYPE,
        {
            "document_id": document_id,
            "source_id": source_id,
            "original_filename": original_filename,
            "stored_path": str(stored_path),
            "digest": digest,
        },
        dedupe_key=document_id,
    )
    _ingestion_worker.wake()
    _refresh_uploaded_pdfs()

    return jinja.get_template("components.html").render(
        component="sidebar_content",
        t=t,
        lang=lang,
        uploaded_pdfs=_uploaded_pdfs,
        kb_stats=_kb_stats,
        llm_online=llm_available(),
        preset_prompts=PRESET_PROMPTS,
        conversations=_conversation_summaries(lang),
        archived_conversations=_archived_conversation_summaries(lang),
        active_conversation=conversation_id,
    )


@app.get("/jobs/{job_id}")
async def get_job(job_id: str):
    """Return durable ingestion status for diagnostics and UI polling."""
    job = _db.get_job(job_id)
    if job is None:
        return Response(status_code=404)
    return {
        "id": job["id"],
        "type": job["job_type"],
        "status": job["status"],
        "stage": job["result"].get("stage", "queued"),
        "progress": job["result"].get("progress", 0),
        "error": job["error"],
    }


@app.get("/stats", response_class=HTMLResponse)
async def stats(lang: str = Depends(get_lang)):
    """Return KB stats partial."""
    t = get_t(lang)
    _update_kb_stats()
    _refresh_uploaded_pdfs()
    return jinja.get_template("components.html").render(
        component="kb_stats",
        t=t,
        lang=lang,
        kb_stats=_kb_stats,
    )


@app.get("/analytics", response_class=HTMLResponse)
async def analytics(request: Request):
    """Return the evidence-backed financial chart workbench."""
    lang = request.query_params.get("lang")
    if lang not in ("zh", "en"):
        lang = request.cookies.get("lang", "zh")
    return jinja.get_template("components.html").render(
        component="analytics",
        t=get_t(lang),
        lang=lang,
        analytics=load_analytics_payload(),
    )


def _render_watchlist(lang: str) -> str:
    watched = _db.list_watchlist()
    return jinja.get_template("components.html").render(
        component="watchlist",
        t=get_t(lang),
        lang=lang,
        timeline=build_watchlist_timeline(watched, lang=lang),
    )


@app.get("/watchlist", response_class=HTMLResponse)
async def watchlist(request: Request):
    """Return the persistent company watchlist and official event timeline."""
    lang = request.query_params.get("lang")
    if lang not in ("zh", "en"):
        lang = request.cookies.get("lang", "zh")
    return _render_watchlist(lang)


@app.post("/watchlist/{company}/toggle", response_class=HTMLResponse)
async def toggle_watchlist(company: str, watched: bool = Form(...), lang: str = Form("zh")):
    """Toggle a supported company and return the refreshed timeline."""
    if FinancialDataManager().get_company(company) is None:
        return Response(status_code=404)
    _db.set_watchlist(company, watched=watched)
    return _render_watchlist(lang if lang in ("zh", "en") else "zh")


@app.post("/quick/{action}", response_class=HTMLResponse)
async def quick_action(
    request: Request,
    action: str,
    lang: str = Depends(get_lang),
    conversation_id: Annotated[str | None, Cookie()] = None,
):
    """Trigger a quick action preset prompt."""
    t = get_t(lang)
    prompt = PRESET_PROMPTS.get(action, {}).get(lang, "")
    if not prompt:
        return ""

    msg_id = str(uuid.uuid4())[:8]
    active_conversation = _ensure_conversation(conversation_id, lang)
    _db.add_message(active_conversation, "user", prompt)

    tracker = CitationTracker()

    # Store config for SSE pickup
    _prune_pending_requests()
    _pending_agent_configs[msg_id] = {
        "query": prompt,
        "lang": lang,
        "tracker": tracker,
        "conversation_id": active_conversation,
        "created_at": time.monotonic(),
        "telemetry": RunTelemetry(
            request_id=request.state.request_id,
            conversation_id=active_conversation,
            provider=LLMConfig.provider,
            model=LLMConfig.model,
        ),
    }

    assistant_id = str(uuid.uuid4())[:8]
    content = jinja.get_template("components.html").render(
        component="chat_response",
        t=t,
        lang=lang,
        user_msg=prompt,
        assistant_id=assistant_id,
        msg_id=msg_id,
        messages=_db.list_messages(active_conversation),
        uploaded_pdfs=_uploaded_pdfs,
        kb_stats=_kb_stats,
        llm_online=llm_available(),
        preset_prompts=PRESET_PROMPTS,
        conversations=_conversation_summaries(lang),
        archived_conversations=_archived_conversation_summaries(lang),
        active_conversation=active_conversation,
    )
    response = HTMLResponse(content)
    if active_conversation != conversation_id:
        _set_cookie(
            response,
            "conversation_id",
            active_conversation,
            max_age=365 * 24 * 3600,
            httponly=True,
            samesite="lax",
        )
    return response


@app.post("/theme")
async def set_theme(theme: str = Form(...)):
    """Set theme cookie."""
    response = Response(status_code=204)
    _set_cookie(response, key="theme", value=theme, max_age=365 * 24 * 3600)
    return response


@app.post("/lang")
async def set_lang(lang: str = Form(...)):
    """Set language cookie and reload page."""
    response = Response(status_code=204)
    _set_cookie(response, key="lang", value=lang, max_age=365 * 24 * 3600)
    return response


def _conversation_switch_response(conversation_id: str, lang: str) -> HTMLResponse:
    content = jinja.get_template("components.html").render(
        component="conversation_switch",
        t=get_t(lang),
        lang=lang,
        messages=_conversation_messages(conversation_id, lang),
        conversations=_conversation_summaries(lang),
        archived_conversations=_archived_conversation_summaries(lang),
        active_conversation=conversation_id,
    )
    response = HTMLResponse(content)
    _set_cookie(
        response,
        "conversation_id",
        conversation_id,
        max_age=365 * 24 * 3600,
        httponly=True,
        samesite="lax",
    )
    return response


@app.post("/conversations/new", response_class=HTMLResponse)
async def new_conversation(lang: str = Depends(get_lang)):
    """Create and select a blank research conversation."""
    return _conversation_switch_response(_db.create_conversation(language=lang), lang)


@app.post("/conversations/{conversation_id}/select", response_class=HTMLResponse)
async def select_conversation(conversation_id: str, lang: str = Depends(get_lang)):
    """Select an active conversation and return its persisted messages."""
    if not _db.conversation_exists(conversation_id):
        return HTMLResponse("", status_code=404)
    return _conversation_switch_response(conversation_id, lang)


@app.post("/conversations/{conversation_id}/rename", response_class=HTMLResponse)
async def rename_conversation(
    conversation_id: str,
    title: Annotated[str, Form(min_length=1, max_length=80)],
    lang: str = Depends(get_lang),
    active_id: Annotated[str | None, Cookie(alias="conversation_id")] = None,
):
    """Rename a conversation without replacing the chat panel."""
    if not _db.rename_conversation(conversation_id, title):
        return HTMLResponse("", status_code=404)
    return jinja.get_template("components.html").render(
        component="conversation_list",
        t=get_t(lang),
        lang=lang,
        conversations=_conversation_summaries(lang),
        archived_conversations=_archived_conversation_summaries(lang),
        active_conversation=active_id,
    )


@app.post("/conversations/{conversation_id}/archive", response_class=HTMLResponse)
async def archive_conversation(
    conversation_id: str,
    lang: str = Depends(get_lang),
    active_id: Annotated[str | None, Cookie(alias="conversation_id")] = None,
):
    """Archive a conversation and select the most recent remaining one."""
    if not _db.archive_conversation(conversation_id):
        return HTMLResponse("", status_code=404)
    if active_id != conversation_id and active_id and _db.conversation_exists(active_id):
        next_id = active_id
    else:
        remaining = _db.list_conversations(limit=1)
        next_id = remaining[0]["id"] if remaining else _db.create_conversation(language=lang)
    return _conversation_switch_response(next_id, lang)


@app.post("/conversations/{conversation_id}/restore", response_class=HTMLResponse)
async def restore_conversation(conversation_id: str, lang: str = Depends(get_lang)):
    """Restore and select a previously archived conversation."""
    if not _db.restore_conversation(conversation_id):
        return HTMLResponse("", status_code=404)
    return _conversation_switch_response(conversation_id, lang)


def _export_response(content: bytes, filename: str, media_type: str) -> Response:
    """Build a download response with portable ASCII and UTF-8 filenames."""
    extension = filename.rsplit(".", 1)[-1]
    ascii_name = f"silicondreams-research.{extension}"
    disposition = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": disposition},
    )


@app.get("/conversations/{conversation_id}/export.md")
async def export_conversation_markdown(conversation_id: str, lang: str = Depends(get_lang)):
    """Download one active conversation as portable Markdown."""
    conversation = _db.get_conversation(conversation_id)
    if conversation is None:
        return Response(status_code=404)
    content = build_markdown_export(conversation, _db.list_messages(conversation_id), lang)
    return _export_response(
        content.encode("utf-8"),
        export_filename(conversation, "md"),
        "text/markdown; charset=utf-8",
    )


@app.get("/conversations/{conversation_id}/export.pdf")
async def export_conversation_pdf(conversation_id: str, lang: str = Depends(get_lang)):
    """Download one active conversation as a paginated research PDF."""
    conversation = _db.get_conversation(conversation_id)
    if conversation is None:
        return Response(status_code=404)
    return _export_response(
        build_pdf_export(conversation, _db.list_messages(conversation_id), lang),
        export_filename(conversation, "pdf"),
        "application/pdf",
    )


@app.get("/exports/current.md")
async def export_current_conversation_markdown(
    conversation_id: Annotated[str | None, Cookie()] = None,
    lang: str = Depends(get_lang),
):
    """Download the browser's selected conversation as Markdown."""
    if not conversation_id:
        return Response(status_code=404)
    return await export_conversation_markdown(conversation_id, lang)


@app.get("/exports/current.pdf")
async def export_current_conversation_pdf(
    conversation_id: Annotated[str | None, Cookie()] = None,
    lang: str = Depends(get_lang),
):
    """Download the browser's selected conversation as PDF."""
    if not conversation_id:
        return Response(status_code=404)
    return await export_conversation_pdf(conversation_id, lang)


@app.get("/sidebar", response_class=HTMLResponse)
async def get_sidebar(request: Request):
    """Return sidebar HTML in the requested language (for HTMX language switch)."""
    # Accept lang via query param (preferred) or cookie (fallback)
    lang = request.query_params.get("lang")
    if lang not in ("zh", "en"):
        lang = request.cookies.get("lang", "zh")
    t = get_t(lang)
    active_conversation = request.cookies.get("conversation_id")
    _refresh_uploaded_pdfs()
    # Avoid opening Chroma for count polling while the worker is actively writing it.
    if not any(pdf["job_status"] in {"pending", "running"} for pdf in _uploaded_pdfs):
        _update_kb_stats()
    return jinja.get_template("components.html").render(
        t=t,
        lang=lang,
        component="sidebar_content",
        uploaded_pdfs=_uploaded_pdfs,
        kb_stats=_kb_stats,
        conversations=_conversation_summaries(lang),
        archived_conversations=_archived_conversation_summaries(lang),
        active_conversation=active_conversation,
    )


# ── Startup ────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    _update_kb_stats()
    uvicorn.run(app, host="127.0.0.1", port=8000)
