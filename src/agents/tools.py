"""
Agent Tools - Functions that LLM agents can call via tool-calling.

Each tool has a Python implementation and an Ollama schema definition.
"""

import re
import time
from urllib.parse import unquote

import httpx


# ── Rate limiting ────────────────────────────────

_last_search_time = 0.0
_SEARCH_DELAY = 2.0  # seconds between DuckDuckGo requests


# ── Tool Implementations ────────────────────────

def web_search(query: str, num_results: int = 5) -> list[dict]:
    """Search the web using DuckDuckGo. Returns [{title, url, snippet}]."""
    global _last_search_time

    # Rate limiting
    elapsed = time.time() - _last_search_time
    if elapsed < _SEARCH_DELAY:
        time.sleep(_SEARCH_DELAY - elapsed)
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
    except Exception as e:
        return [{"error": str(e)}]

    return results if results else [{"info": "No results found"}]


def fetch_page(url: str) -> str:
    """Fetch a web page and return its main text content."""
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
                        "AppleWebKit/537.36"
                    ),
                },
            )
            if resp.status_code != 200:
                return f"HTTP {resp.status_code}"

            html = resp.text

            # Remove script, style, nav, header, footer elements
            html = re.sub(r"<(script|style|nav|header|footer)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
            # Remove HTML tags
            text = re.sub(r"<[^>]+>", " ", html)
            # Collapse whitespace
            text = re.sub(r"\s+", " ", text).strip()
            # Decode HTML entities
            text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            text = text.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")

            # Smart truncation: keep paragraphs intact, don't cut mid-sentence
            if len(text) > 5000:
                # Find the last sentence boundary before 5000 chars
                cut = text[:5000].rfind(". ")
                if cut > 3000:
                    text = text[:cut + 1]
                else:
                    text = text[:5000]

            return text if text else "Page had no readable content"

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
