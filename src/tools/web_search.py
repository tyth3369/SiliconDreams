"""
SiliconDreams — Web Search Tool (v3)
=====================================
Search backend for the Agent Loop. Uses Tavily Search API (designed for
AI agents) as primary backend, with DuckDuckGo HTML as fallback.

Tavily: https://tavily.com — free tier 1,000 searches/month, no credit card.
DDG:    https://html.duckduckgo.com/html/ — free but rate-limited.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import UTC, datetime
from urllib.parse import urlparse

from config import SearchConfig
from src.evidence_policy import (
    WebEvidenceAssessment,
    assess_web_results,
    is_time_sensitive_query,
)

logger = logging.getLogger(__name__)

MAX_RESULTS = 5
SEARCH_TIMEOUT = 10

OFFICIAL_DOMAINS = {
    "tsmc.com",
    "smic.com",
    "hkexnews.hk",
    "sec.gov",
    "intel.com",
    "samsung.com",
    "amd.com",
    "nvidia.com",
    "asml.com",
    "appliedmaterials.com",
    "lamresearch.com",
    "micron.com",
    "skhynix.com",
}
REPUTABLE_NEWS_DOMAINS = {
    "reuters.com",
    "bloomberg.com",
    "ft.com",
    "wsj.com",
    "apnews.com",
    "bbc.com",
    "cnbc.com",
    "nikkei.com",
    "rfi.fr",
    "digitimes.com",
    "tomshardware.com",
    "trendforce.com",
}


def _hostname(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower().removeprefix("www.")
    except ValueError:
        return ""


def _domain_matches(hostname: str, domains: set[str]) -> bool:
    return any(hostname == domain or hostname.endswith(f".{domain}") for domain in domains)


def source_trust_tier(url: str) -> int:
    """Classify known primary/reputable domains; unknown web sources remain tier 3."""
    hostname = _hostname(url)
    if _domain_matches(hostname, OFFICIAL_DOMAINS):
        return 1
    if _domain_matches(hostname, REPUTABLE_NEWS_DOMAINS):
        return 2
    return 3


# ═══════════════════════════════════════════════════════════
# Tavily Search (Primary)
# ═══════════════════════════════════════════════════════════


def _search_tavily(query: str, max_results: int = MAX_RESULTS) -> tuple[list[dict], str]:
    """
    Search via Tavily API. Returns (structured_results, formatted_text).

    Tavily API is purpose-built for AI agents — returns clean, structured
    results with no bot detection or rate limiting (within free tier).
    """
    if not SearchConfig.is_configured():
        return [], "TAVILY_API_KEY 未配置"

    try:
        # Use urllib to avoid extra dependencies
        import urllib.error
        import urllib.request

        request_body = {
            "api_key": SearchConfig.api_key,
            "query": query,
            "search_depth": SearchConfig.search_depth,
            "max_results": max_results,
            "topic": "news" if is_time_sensitive_query(query) else "general",
        }
        if is_time_sensitive_query(query):
            request_body["end_date"] = datetime.now(UTC).date().isoformat()
        payload = json.dumps(request_body).encode("utf-8")

        req = urllib.request.Request(
            SearchConfig.api_url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=SearchConfig.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        results = data.get("results", [])
        if not results:
            return [], f"Tavily 搜索 '{query}' 未找到结果。"

        # Build structured results
        structured = []
        for r in results[:max_results]:
            content = r.get("content", "")
            if len(content) > 300:
                content = content[:300] + "..."
            structured.append(
                {
                    "title": r.get("title", "无标题"),
                    "url": r.get("url", ""),
                    "snippet": content,
                    "score": r.get("score", 0.0),
                    "publisher": _hostname(r.get("url", "")),
                    "published_at": r.get("published_date", ""),
                    "trust_tier": source_trust_tier(r.get("url", "")),
                }
            )

        return structured, "Tavily"

    except ImportError:
        logger.warning("urllib 不可用")
        return [], "搜索模块初始化失败"
    except urllib.error.HTTPError as e:
        logger.error(f"Tavily HTTP {e.code}: {e.reason}")
        if e.code == 401 or e.code == 403:
            return [], "Tavily API Key 无效或已过期，请检查 .env 中的 TAVILY_API_KEY"
        return [], f"Tavily 搜索失败（HTTP {e.code}）"
    except Exception as e:
        logger.error(f"Tavily 搜索异常: {e}")
        return [], f"Tavily 搜索出错: {e}"


# ═══════════════════════════════════════════════════════════
# DuckDuckGo HTML Search (Fallback)
# ═══════════════════════════════════════════════════════════

DDG_HTML_URL = "https://html.duckduckgo.com/html/"


def _search_ddg(query: str, max_results: int = MAX_RESULTS) -> tuple[list[dict], str]:
    """
    Fallback: DuckDuckGo HTML search via curl_cffi.

    Note: DDG rate-limits aggressively. This should only be used when
    Tavily is not configured.
    """
    try:
        from curl_cffi import requests

        for attempt in range(2):
            try:
                response = requests.post(
                    DDG_HTML_URL,
                    data={"q": query},
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/110.0.0.0 Safari/537.36"
                        ),
                    },
                    timeout=SEARCH_TIMEOUT,
                    impersonate="chrome110",
                )

                # Bot detection page — retry after delay
                if response.status_code == 202 and "anomaly.js" in response.text:
                    if attempt < 1:
                        logger.warning("DDG bot detection, retrying...")
                        time.sleep(3)
                        continue
                    return [], "DuckDuckGo 暂时限流，请稍后重试或配置 Tavily API Key"

                if response.status_code not in (200, 202):
                    return [], f"DuckDuckGo 搜索失败（HTTP {response.status_code}）"

                results = _parse_ddg_html(response.text, max_results)
                if not results:
                    return [], f"搜索 '{query}' 未找到相关结果。"

                return results, "DuckDuckGo"

            except Exception as e:
                if attempt < 1:
                    time.sleep(2)
                    continue
                raise e

    except ImportError:
        return [], "DuckDuckGo 搜索不可用：缺少 curl_cffi 依赖"
    except Exception as e:
        logger.error(f"DDG 搜索失败: {e}")
        return [], f"DuckDuckGo 搜索出错: {e}"

    return [], "搜索不可用"


def _parse_ddg_html(html: str, max_results: int) -> list[dict]:
    """Parse DuckDuckGo HTML results."""
    results = []
    blocks = re.findall(r'class="result results_links.*?".*?</div>\s*</div>', html, re.DOTALL)

    for block in blocks[:max_results]:
        title_match = re.search(
            r'class="result__title"[^>]*>.*?<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', block, re.DOTALL
        )
        if not title_match:
            continue

        url = title_match.group(1).strip()
        title = re.sub(r"<[^>]+>", "", title_match.group(2)).strip()
        title = title.replace("&#x27;", "'").replace("&amp;", "&").replace("&quot;", '"')

        snippet_match = re.search(r'class="result__snippet"[^>]*>(.*?)</a>', block, re.DOTALL)
        snippet = ""
        if snippet_match:
            snippet = re.sub(r"<[^>]+>", "", snippet_match.group(1)).strip()
            snippet = snippet.replace("&#x27;", "'").replace("&amp;", "&")

        if title and url:
            results.append(
                {
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                    "publisher": _hostname(url),
                    "published_at": "",
                    "trust_tier": source_trust_tier(url),
                }
            )

    return results


# ═══════════════════════════════════════════════════════════
# Public API (used by agent_loop.py)
# ═══════════════════════════════════════════════════════════


def _do_search(query: str, max_results: int = MAX_RESULTS) -> tuple[list[dict], str]:
    """
    Search the web — Tavily first, DDG as fallback.

    Returns:
        (structured_results, formatted_text_for_llm)
    """
    # Primary: Tavily (AI-agent-friendly, reliable)
    if SearchConfig.is_configured():
        results, backend = _search_tavily(query, max_results)
        if results:
            assessed, assessment = assess_web_results(query, results)
            if assessed:
                return assessed, _format_results(query, backend, assessed, assessment)
            logger.warning("Tavily results rejected by evidence-date policy; trying DDG")
        # Tavily failed → log and fall through to DDG
        logger.warning(f"Tavily 搜索失败，尝试 DDG fallback: {backend}")

    # Fallback: DuckDuckGo (free, rate-limited)
    results, backend = _search_ddg(query, max_results)
    if not results:
        return results, backend
    assessed, assessment = assess_web_results(query, results)
    return assessed, _format_results(query, backend, assessed, assessment)


def _format_results(
    query: str,
    backend: str,
    results: list[dict],
    assessment: WebEvidenceAssessment,
) -> str:
    """Format only policy-approved results for the model."""
    lines = [f'## Web 搜索结果 ({backend}): "{query}"', assessment.instruction("zh"), ""]
    for index, result in enumerate(results, 1):
        body = str(result.get("snippet", ""))[:300]
        published_at = result.get("published_at") or "日期未知"
        lines.extend(
            [
                f"### 结果 {index}: {result['title']}",
                f"来源: {result['url']}",
                f"发布者: {result.get('publisher') or 'unknown'}",
                f"发布日期: {published_at}",
                f"来源等级: Tier {result.get('trust_tier', 3)}",
                f"时效状态: {result.get('date_status', 'undated')}",
            ]
        )
        if body:
            lines.append(f"摘要: {body}")
        lines.append("")
    return "\n".join(lines)


def web_search(query: str, max_results: int = MAX_RESULTS) -> str:
    """Search the web, return formatted text for LLM context."""
    _, text = _do_search(query, max_results)
    return text


def web_search_structured(query: str, max_results: int = MAX_RESULTS) -> list[dict]:
    """Search the web, return structured results for citation tracking."""
    results, _ = _do_search(query, max_results)
    for r in results:
        if len(r.get("snippet", "")) > 200:
            r["snippet"] = r["snippet"][:200] + "..."
    return results
