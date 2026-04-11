"""
Agent Tools - Functions that LLM agents can call via tool-calling.

Each tool has a Python implementation and an Ollama schema definition.
Search uses SearXNG (self-hosted) as primary, DuckDuckGo as fallback.
"""

import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import httpx

from config import SEARXNG_URL


# ── Rate limiting ────────────────────────────────

_last_search_time = 0.0
_SEARCH_DELAY = 1.0  # SearXNG is local, minimal delay needed
_DDG_DELAY = 4.0     # DuckDuckGo needs more breathing room


# ── Search Backends ─────────────────────────────

def _searxng_search(query: str, num_results: int = 5) -> list[dict]:
    """Search using local SearXNG instance (JSON API)."""
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(
                f"{SEARXNG_URL}/search",
                params={
                    "q": query,
                    "format": "json",
                    "categories": "general",
                    "engines": "google,bing,duckduckgo,brave",
                    "language": "en",
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                results = []
                for r in data.get("results", [])[:num_results]:
                    results.append({
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "snippet": r.get("content", ""),
                    })
                return results
    except Exception:
        pass
    return []


def _ddg_search(query: str, num_results: int = 5) -> list[dict]:
    """Fallback: Search using DuckDuckGo HTML scraping."""
    global _last_search_time
    elapsed = time.time() - _last_search_time
    if elapsed < _DDG_DELAY:
        time.sleep(_DDG_DELAY - elapsed)
    _last_search_time = time.time()

    results = []
    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            resp = client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                },
            )
            if resp.status_code == 200:
                html = resp.text
                result_blocks = re.findall(
                    r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?'
                    r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
                    html, re.DOTALL,
                )
                for url, title, snippet in result_blocks[:num_results]:
                    title = re.sub(r"<[^>]+>", "", title).strip()
                    snippet = re.sub(r"<[^>]+>", "", snippet).strip()
                    if "uddg=" in url:
                        m = re.search(r"uddg=([^&]+)", url)
                        if m:
                            url = unquote(m.group(1))
                    results.append({"title": title, "url": url, "snippet": snippet})
    except Exception:
        pass
    return results


# ── Tool Implementations ────────────────────────

def web_search(query: str, num_results: int = 5) -> list[dict]:
    """Search the web. Uses SearXNG (local) with DuckDuckGo fallback."""
    global _last_search_time

    # Minimal delay for SearXNG (local instance)
    elapsed = time.time() - _last_search_time
    if elapsed < _SEARCH_DELAY:
        time.sleep(_SEARCH_DELAY - elapsed)
    _last_search_time = time.time()

    # Try SearXNG first (local, no rate limits)
    results = _searxng_search(query, num_results)
    if results:
        return results

    # Fallback to DuckDuckGo
    results = _ddg_search(query, num_results)
    return results if results else [{"info": "No results found"}]


def fetch_page(url: str) -> str:
    """Fetch a web page and return its main text content.

    Extracts content in priority order:
    1. JSON-LD structured data (works on JS-rendered sites like Gumroad)
    2. Meta descriptions (og:description, description)
    3. Body text (stripped HTML)
    """
    skip_patterns = (".pdf", ".zip", ".dmg", ".exe", ".wav", ".mp3")
    if any(url.lower().endswith(ext) for ext in skip_patterns):
        return f"Skipped binary file: {url}"

    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            resp = client.get(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                },
            )
            if resp.status_code != 200:
                return f"HTTP {resp.status_code}"

            html = resp.text
            parts = []

            # 1. Extract JSON-LD structured data (survives JS rendering)
            ld_blocks = re.findall(
                r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
                html, re.DOTALL | re.IGNORECASE,
            )
            for block in ld_blocks:
                block = block.strip()
                if block:
                    parts.append(f"[Structured Data] {block[:2000]}")

            # 2. Extract meta descriptions
            for attr in ("og:description", "description", "twitter:description"):
                meta = re.findall(
                    rf'<meta[^>]*(?:name|property)="{attr}"[^>]*content="([^"]+)"',
                    html, re.IGNORECASE,
                )
                if not meta:
                    meta = re.findall(
                        rf"<meta[^>]*content=\"([^\"]+)\"[^>]*(?:name|property)=\"{attr}\"",
                        html, re.IGNORECASE,
                    )
                for m in meta[:1]:
                    parts.append(f"[Meta Description] {m}")

            # 3. Extract body text (strip HTML)
            body = html
            # Remove script, style, nav, footer
            body = re.sub(r"<(script|style|nav|footer)[^>]*>.*?</\1>", "", body, flags=re.DOTALL | re.IGNORECASE)
            # Remove HTML tags
            body_text = re.sub(r"<[^>]+>", " ", body)
            body_text = re.sub(r"\s+", " ", body_text).strip()
            # Decode entities
            for old, new in [("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                             ("&quot;", '"'), ("&#39;", "'"), ("&nbsp;", " ")]:
                body_text = body_text.replace(old, new)

            if len(body_text) > 100:
                # Smart truncation
                limit = 4000 - sum(len(p) for p in parts)
                if limit > 500:
                    cut = body_text[:limit].rfind(". ")
                    body_text = body_text[:cut + 1] if cut > limit // 2 else body_text[:limit]
                    parts.append(f"[Page Content] {body_text}")

            result = "\n\n".join(parts)
            return result if result else "Page had no readable content"

    except Exception as e:
        return f"Error fetching page: {e}"


def read_pdf(path: str) -> str:
    """Extract text from a local PDF file."""
    try:
        import pdfplumber
    except ImportError:
        return "Error: pdfplumber not installed. Run: pip install pdfplumber"

    try:
        text_parts = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
                if sum(len(t) for t in text_parts) > 5000:
                    break
        text = "\n\n".join(text_parts)
        return text[:5000] if text else "PDF had no extractable text"
    except Exception as e:
        return f"Error reading PDF: {e}"


# ── Ollama Tool Schemas ─────────────────────────

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web for information. Returns a list of results with "
                "title, URL, and snippet. Use specific queries for better results. "
                "Examples: 'SSL Bus Compressor 2 review', "
                "'site:kvraudio.com FabFilter Pro-Q 3', "
                "'site:gearspace.com \"LA-2A\" compressor comparison'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query. Use quotes for exact phrases, site: for specific sites.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_page",
            "description": (
                "Fetch and read the text content of a web page. "
                "Use this after web_search to get full details from a promising result. "
                "Returns the main text content of the page."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Full URL to fetch",
                    },
                },
                "required": ["url"],
            },
        },
    },
]

TOOL_SCHEMAS_WITH_PDF = TOOL_SCHEMAS + [
    {
        "type": "function",
        "function": {
            "name": "read_pdf",
            "description": (
                "Read text from a local PDF file (e.g., a plugin manual). "
                "Returns extracted text content."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute path to the PDF file",
                    },
                },
                "required": ["path"],
            },
        },
    },
]

TOOL_HANDLERS = {
    "web_search": web_search,
    "fetch_page": fetch_page,
    "read_pdf": read_pdf,
}
