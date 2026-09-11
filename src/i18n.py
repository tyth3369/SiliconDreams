"""
SiliconDreams — Internationalization (i18n)
===========================================
Chinese/English bilingual support.
UI language switch via session state, no external dependencies.
"""

from __future__ import annotations

# ═══════════════════════════════════════════════════
# Translation dictionaries
# ═══════════════════════════════════════════════════

_ZH = {
    # -- App / Brand --
    "app.tagline": "ELECTRONICS/SEMICONDUCTOR AI ANALYST",
    "app.footer": "SiliconDreams v0.7.0 | (c) 2026",
    # -- Sidebar --
    "sidebar.upload_title": "财报上传",
    "sidebar.upload_hint": "拖拽或点击上传 PDF 财报",
    "sidebar.upload_help": "支持半导体公司年报、季报、招股书等 PDF 文档（<=50MB）",
    "sidebar.upload_error_size": "文件超过 50MB 限制",
    "sidebar.upload_error_duplicate": "此文件已上传过",
    "sidebar.upload_success": "上传并索引完成",
    "sidebar.kb_title": "知识库状态",
    "sidebar.kb_docs": "文档",
    "sidebar.kb_text": "文本",
    "sidebar.kb_table": "表格",
    "sidebar.kb_uploaded": "已上传文件：",
    "sidebar.settings_title": "设置",
    "sidebar.settings_model": "LLM 模型",
    "sidebar.settings_model_help": "V4 Flash 适合日常分析，V4 Pro 适合复杂研究",
    "sidebar.settings_language": "界面语言",
    "sidebar.settings_theme": "主题",
    "sidebar.settings_debug": "Debug 模式",
    # -- Theme --
    "theme.auto": "自动",
    "theme.dark": "暗色",
    "theme.light": "浅色",
    # -- Spinners / Progress --
    "spinner.parse": "正在解析 PDF...",
    "spinner.chunk": "正在分块...",
    "spinner.vectorize": "正在向量化...",
    # -- Status --
    "status.online": "ONLINE",
    "status.no_key": "NO KEY",
    "status.llm_status": "LLM",
    # -- Quick Actions --
    "quick.compare": "行业对比",
    "quick.tech": "技术趋势",
    "quick.finance": "财务分析",
    # -- Chat --
    "chat.placeholder": "请输入您的问题",
    # -- Errors --
    "error.pdf_failed": "PDF 处理失败",
    "error.llm_failed": "LLM 调用失败",
    "error.llm_not_configured": (
        "**LLM 尚未配置**\n\n"
        "请完成以下步骤以启用 AI 对话：\n"
        "1. 编辑 `.env` 文件，填入你的 DeepSeek API Key\n"
        "2. 刷新页面\n\n"
        "详见 [docs/api-keys-guide.md](docs/api-keys-guide.md)"
    ),
    # -- Citation --
    "citation.source_tag": "来源",
    "citation.page_prefix": "p",
    "citation.trace_title": "引用溯源",
    "citation.trace_hint": "点击展开查看原始文本片段",
    "citation.unavailable": "（原始文本段落在当前会话中不可用）",
    "citation.financial_label": "财务数据",
    "citation.web_label": "网络搜索",
    "citation.source_count": "个来源",
    # -- RAG Context --
    "rag.context_header": "以下是从已上传财报中检索到的相关信息，请基于这些信息回答用户问题。引用数据时必须标注 [来源 p页码]：",
    "rag.error": "RAG 检索异常",
}

_EN = {
    # -- App / Brand --
    "app.tagline": "ELECTRONICS/SEMICONDUCTOR AI ANALYST",
    "app.footer": "SiliconDreams v0.7.0 | (c) 2026",
    # -- Sidebar --
    "sidebar.upload_title": "Upload Reports",
    "sidebar.upload_hint": "Drag & drop PDF financial reports",
    "sidebar.upload_help": "Supports annual/quarterly reports, prospectuses (<=50MB)",
    "sidebar.upload_error_size": "File exceeds 50MB limit",
    "sidebar.upload_error_duplicate": "This file has already been uploaded",
    "sidebar.upload_success": "uploaded and indexed successfully",
    "sidebar.kb_title": "Knowledge Base",
    "sidebar.kb_docs": "Docs",
    "sidebar.kb_text": "Text",
    "sidebar.kb_table": "Tables",
    "sidebar.kb_uploaded": "Uploaded files:",
    "sidebar.settings_title": "Settings",
    "sidebar.settings_model": "LLM Model",
    "sidebar.settings_model_help": "V4 Flash for daily analysis, V4 Pro for complex research",
    "sidebar.settings_language": "Language",
    "sidebar.settings_theme": "Theme",
    "sidebar.settings_debug": "Debug Mode",
    # -- Theme --
    "theme.auto": "Auto",
    "theme.dark": "Dark",
    "theme.light": "Light",
    # -- Spinners / Progress --
    "spinner.parse": "Parsing PDF...",
    "spinner.chunk": "Chunking...",
    "spinner.vectorize": "Vectorizing...",
    # -- Status --
    "status.online": "ONLINE",
    "status.no_key": "NO KEY",
    "status.llm_status": "LLM",
    # -- Quick Actions --
    "quick.compare": "Peer Comparison",
    "quick.tech": "Tech Trends",
    "quick.finance": "Financial Analysis",
    # -- Chat --
    "chat.placeholder": "Please enter your question",
    # -- Errors --
    "error.pdf_failed": "PDF processing failed",
    "error.llm_failed": "LLM call failed",
    "error.llm_not_configured": (
        "**LLM Not Configured**\n\n"
        "Please complete the following steps to enable AI chat:\n"
        "1. Edit `.env` file with your DeepSeek API Key\n"
        "2. Refresh the page\n\n"
        "See [docs/api-keys-guide.md](docs/api-keys-guide.md) for details"
    ),
    # -- Citation --
    "citation.source_tag": "source",
    "citation.page_prefix": "p",
    "citation.trace_title": "Source Trace",
    "citation.trace_hint": "Click to expand and view original text excerpts",
    "citation.unavailable": "(Original text unavailable in current session)",
    "citation.financial_label": "Financials",
    "citation.web_label": "Web Search",
    "citation.source_count": "sources",
    # -- RAG Context --
    "rag.context_header": "The following is relevant information retrieved from uploaded reports. Base your answer on this data. Cite data points with [source pN] format:",
    "rag.error": "RAG retrieval error",
}


# ═══════════════════════════════════════════════════
# I18n Manager
# ═══════════════════════════════════════════════════


class I18n:
    """Internationalization manager (singleton per session)."""

    SUPPORTED = {"zh": "中文", "en": "English"}

    def __init__(self, lang: str = "zh"):
        self._lang = lang

    @property
    def lang(self) -> str:
        return self._lang

    def t(self, key: str, **kwargs) -> str:
        """Translate a key. Falls back to Chinese if key missing."""
        if self._lang == "en":
            value = _EN.get(key)
            if value is not None:
                return value.format(**kwargs) if kwargs else value
        # Default: Chinese
        value = _ZH.get(key, key)
        return value.format(**kwargs) if kwargs else value

    def switch(self, lang: str):
        """Switch language ('zh' or 'en')."""
        if lang in self.SUPPORTED:
            self._lang = lang


# ═══════════════════════════════════════════════════
# Convenience functions (framework-agnostic)
# ═══════════════════════════════════════════════════

# Module-level default instance (used when no request context)
_default_i18n = I18n(lang="zh")


def get_i18n(lang: str = "zh") -> I18n:
    """Get an I18n instance for the given language."""
    return I18n(lang=lang)


def t(key: str, **kwargs) -> str:
    """Shorthand using default language. For request-scoped usage,
    use get_i18n(lang).t(key) instead."""
    return _default_i18n.t(key, **kwargs)
