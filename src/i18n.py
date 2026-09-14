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
    "app.footer": "SiliconDreams v1.0.0-rc.5 | (c) 2026",
    # -- Sidebar --
    "sidebar.upload_title": "财报上传",
    "sidebar.upload_hint": "拖拽或点击上传 PDF 财报",
    "sidebar.upload_help": "支持半导体公司年报、季报、招股书等 PDF 文档（<=50MB）",
    "sidebar.upload_error_size": "文件超过 50MB 限制",
    "sidebar.upload_error_duplicate": "此文件已上传过",
    "sidebar.upload_success": "上传并索引完成",
    "job.stage.queued": "等待处理",
    "job.stage.pending": "等待处理",
    "job.stage.starting": "正在启动",
    "job.stage.parsing": "正在解析",
    "job.stage.chunking": "正在分块",
    "job.stage.persisting": "正在保存证据",
    "job.stage.indexing": "正在建立索引",
    "job.stage.completed": "索引完成",
    "job.stage.ready": "索引完成",
    "job.stage.failed": "处理失败",
    "sidebar.kb_title": "知识库状态",
    "sidebar.kb_docs": "文档",
    "sidebar.kb_text": "文本",
    "sidebar.kb_table": "表格",
    "sidebar.kb_uploaded": "已上传文件：",
    "conversation.title": "研究会话",
    "conversation.new": "新建",
    "conversation.rename": "重命名",
    "conversation.rename_prompt": "输入新的会话名称",
    "conversation.archive": "归档",
    "conversation.archive_confirm": "归档此会话？内容仍保存在数据库中。",
    "conversation.archived": "已归档",
    "conversation.restore": "恢复",
    "conversation.export_markdown": "下载 Markdown",
    "conversation.export_pdf": "下载 PDF",
    "sidebar.settings_title": "设置",
    "sidebar.settings_model": "LLM 模型",
    "sidebar.settings_model_help": "V4 Flash 适合日常分析，V4 Pro 适合复杂研究",
    "sidebar.settings_language": "界面语言",
    "sidebar.settings_theme": "主题",
    "sidebar.settings_debug": "Debug 模式",
    "auth.login_title": "研究终端登录",
    "auth.username": "用户名",
    "auth.password": "密码",
    "auth.sign_in": "登录",
    "auth.sign_out": "退出登录",
    "auth.invalid": "凭据无效或表单已过期，请重试。",
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
    "quick.analytics": "数据图表",
    "quick.watchlist": "关注列表",
    "analytics.title": "代工财务仪表盘",
    "analytics.subtitle": "官方披露数据 · 数据点可点击溯源",
    "analytics.close": "关闭",
    "analytics.revenue": "季度营收",
    "analytics.revenue_unit": "十亿美元",
    "analytics.margin": "季度毛利率",
    "analytics.margin_unit": "%",
    "analytics.process": "FY2025 制程收入结构",
    "analytics.capex": "FY2025 资本开支强度",
    "analytics.approximate": "中芯国际制程结构为近似披露口径",
    "analytics.sources": "年度数据来源",
    "analytics.open_source": "打开官方来源",
    "watchlist.title": "公司关注列表",
    "watchlist.subtitle": "持久关注 · 官方披露事件时间线",
    "watchlist.follow": "关注",
    "watchlist.following": "已关注",
    "watchlist.empty": "选择公司后，最近官方披露将在这里形成时间线。",
    "watchlist.source": "打开披露原文",
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
    "app.footer": "SiliconDreams v1.0.0-rc.5 | (c) 2026",
    # -- Sidebar --
    "sidebar.upload_title": "Upload Reports",
    "sidebar.upload_hint": "Drag & drop PDF financial reports",
    "sidebar.upload_help": "Supports annual/quarterly reports, prospectuses (<=50MB)",
    "sidebar.upload_error_size": "File exceeds 50MB limit",
    "sidebar.upload_error_duplicate": "This file has already been uploaded",
    "sidebar.upload_success": "uploaded and indexed successfully",
    "job.stage.queued": "Queued",
    "job.stage.pending": "Queued",
    "job.stage.starting": "Starting",
    "job.stage.parsing": "Parsing",
    "job.stage.chunking": "Chunking",
    "job.stage.persisting": "Saving evidence",
    "job.stage.indexing": "Building index",
    "job.stage.completed": "Indexed",
    "job.stage.ready": "Indexed",
    "job.stage.failed": "Failed",
    "sidebar.kb_title": "Knowledge Base",
    "sidebar.kb_docs": "Docs",
    "sidebar.kb_text": "Text",
    "sidebar.kb_table": "Tables",
    "sidebar.kb_uploaded": "Uploaded files:",
    "conversation.title": "Research Sessions",
    "conversation.new": "New",
    "conversation.rename": "Rename",
    "conversation.rename_prompt": "Enter a new session name",
    "conversation.archive": "Archive",
    "conversation.archive_confirm": "Archive this session? Its content remains in the database.",
    "conversation.archived": "Archived",
    "conversation.restore": "Restore",
    "conversation.export_markdown": "Download Markdown",
    "conversation.export_pdf": "Download PDF",
    "sidebar.settings_title": "Settings",
    "sidebar.settings_model": "LLM Model",
    "sidebar.settings_model_help": "V4 Flash for daily analysis, V4 Pro for complex research",
    "sidebar.settings_language": "Language",
    "sidebar.settings_theme": "Theme",
    "sidebar.settings_debug": "Debug Mode",
    "auth.login_title": "Research Terminal Access",
    "auth.username": "Username",
    "auth.password": "Password",
    "auth.sign_in": "Sign In",
    "auth.sign_out": "Sign Out",
    "auth.invalid": "Invalid credentials or expired form. Please try again.",
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
    "quick.analytics": "Data Charts",
    "quick.watchlist": "Watchlist",
    "analytics.title": "Foundry Financial Analytics",
    "analytics.subtitle": "Official disclosures · select a data point to trace its source",
    "analytics.close": "Close",
    "analytics.revenue": "Quarterly Revenue",
    "analytics.revenue_unit": "USD billion",
    "analytics.margin": "Quarterly Gross Margin",
    "analytics.margin_unit": "%",
    "analytics.process": "FY2025 Process Revenue Mix",
    "analytics.capex": "FY2025 Capex Intensity",
    "analytics.approximate": "SMIC process mix uses approximate disclosed groupings",
    "analytics.sources": "Annual data sources",
    "analytics.open_source": "Open official source",
    "watchlist.title": "Company Watchlist",
    "watchlist.subtitle": "Persistent tracking · official disclosure timeline",
    "watchlist.follow": "Follow",
    "watchlist.following": "Following",
    "watchlist.empty": "Select a company to build a timeline of its latest official disclosures.",
    "watchlist.source": "Open filing",
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
