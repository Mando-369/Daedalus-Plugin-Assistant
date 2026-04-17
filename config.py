"""
Daedalus Plugin Assistant - Central Configuration
All adjustable parameters live here. Nothing hardcoded elsewhere.
"""

# Kill ChromaDB telemetry -- env vars don't work due to PostHog v7 API change
# (https://github.com/chroma-core/chroma/issues/4966)
# Monkey-patch PostHog so it never sends anything.
import os as _os
_os.environ["ANONYMIZED_TELEMETRY"] = "False"
try:
    import posthog as _posthog
    _posthog.capture = lambda *args, **kwargs: None
    _posthog.Posthog = type("Posthog", (), {
        "__init__": lambda self, *a, **kw: None,
        "capture": lambda self, *a, **kw: None,
        "shutdown": lambda self: None,
    })
except ImportError:
    pass

import os
import platform
import subprocess
import logging
from pathlib import Path


# ──────────────────────────────────────────────
# System Auto-Detection
# ──────────────────────────────────────────────

def _detect_system_ram_gb() -> int:
    """Detect total system RAM in GB."""
    try:
        if platform.system() == "Darwin":
            raw = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip()
            return int(raw) // (1024 ** 3)
        elif platform.system() == "Linux":
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal"):
                        kb = int(line.split()[1])
                        return kb // (1024 ** 2)
    except Exception:
        pass
    return 16  # safe fallback


def _detect_ollama_model_context(base_url: str, model: str) -> int | None:
    """Query Ollama for the model's max supported context length."""
    try:
        import httpx
        resp = httpx.post(f"{base_url}/api/show", json={"name": model}, timeout=10)
        if resp.status_code == 200:
            info = resp.json().get("model_info", {})
            for key, val in info.items():
                if "context_length" in key:
                    return int(val)
    except Exception:
        pass
    return None


def _auto_token_limits(ram_gb: int, model_max_ctx: int | None) -> tuple[int, int]:
    """
    Determine optimal context_length and num_predict based on system RAM
    and model capabilities. Returns (context_length, num_predict).

    Conservative tiers — leaves plenty of room for OS and other processes.
    """
    if ram_gb >= 96:
        ctx, predict = 32768, 16384
    elif ram_gb >= 64:
        ctx, predict = 24576, 12288
    elif ram_gb >= 32:
        ctx, predict = 16384, 8192
    elif ram_gb >= 16:
        ctx, predict = 8192, 4096
    else:
        ctx, predict = 4096, 2048

    # Cap to model's actual max if known
    if model_max_ctx:
        ctx = min(ctx, model_max_ctx)

    return ctx, predict

# ──────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "data"
SQLITE_DB_PATH = DATA_DIR / "plugins.db"
CHROMA_DB_PATH = DATA_DIR / "chroma"
LOG_DIR = BASE_DIR / "logs"
BACKUP_DIR = DATA_DIR / "backups"

# Plugin scan directories (macOS standard locations)
PLUGIN_SCAN_DIRS = [
    {
        "path": "/Library/Audio/Plug-Ins/Components",
        "format": "AU",
        "scope": "system",
        "extension": ".component",
    },
    {
        "path": "/Library/Audio/Plug-Ins/VST3",
        "format": "VST3",
        "scope": "system",
        "extension": ".vst3",
    },
    {
        "path": "~/Library/Audio/Plug-Ins/Components",
        "format": "AU",
        "scope": "user",
        "extension": ".component",
    },
    {
        "path": "~/Library/Audio/Plug-Ins/VST3",
        "format": "VST3",
        "scope": "user",
        "extension": ".vst3",
    },
]

# ──────────────────────────────────────────────
# Web Server
# ──────────────────────────────────────────────
WEB_HOST = "127.0.0.1"
WEB_PORT = 8777
WEB_RELOAD = True  # auto-reload on code changes (dev mode)
WEB_WORKERS = 1    # single worker is fine for local use
WEB_LOG_LEVEL = "info"

# ──────────────────────────────────────────────
# Search (SearXNG)
# ──────────────────────────────────────────────
SEARXNG_URL = "http://127.0.0.1:8888"  # local SearXNG instance
# To set up SearXNG:
#   docker run -d --name searxng -p 8888:8080 \
#     -e SEARXNG_SECRET=$(openssl rand -hex 32) \
#     searxng/searxng
# Falls back to DuckDuckGo if SearXNG is not running.

# ──────────────────────────────────────────────
# Ollama / LLM
# ──────────────────────────────────────────────
OLLAMA_BASE_URL = "http://127.0.0.1:11434"
OLLAMA_MODEL = "gemma4:26b"  # adjust to your pulled model name
OLLAMA_TIMEOUT = 120           # seconds to wait for LLM response
OLLAMA_TEMPERATURE = 0.3       # lower = more factual, higher = more creative
OLLAMA_TOP_P = 0.9
OLLAMA_KEEP_ALIVE = "10m"      # keep model loaded in memory

# Token limits — set to "auto" to detect from system specs, or override with int
# Auto-detection checks RAM + model's max context and picks optimal values
OLLAMA_CONTEXT_LENGTH_SETTING = "auto"   # "auto" or int (e.g. 32768)
OLLAMA_NUM_PREDICT_SETTING = "auto"      # "auto" or int (e.g. 16384)

# Resolve auto settings
_system_ram = _detect_system_ram_gb()
_model_max_ctx = _detect_ollama_model_context(OLLAMA_BASE_URL, OLLAMA_MODEL)
_auto_ctx, _auto_predict = _auto_token_limits(_system_ram, _model_max_ctx)

OLLAMA_CONTEXT_LENGTH = (
    _auto_ctx if OLLAMA_CONTEXT_LENGTH_SETTING == "auto"
    else int(OLLAMA_CONTEXT_LENGTH_SETTING)
)
OLLAMA_NUM_PREDICT = (
    _auto_predict if OLLAMA_NUM_PREDICT_SETTING == "auto"
    else int(OLLAMA_NUM_PREDICT_SETTING)
)

# Log what was detected (only when running the app, not one-liner imports)
import sys as _sys
if not getattr(_sys, '_called_from_test', False) and len(_sys.argv) > 1:
    _mode = 'auto' if OLLAMA_CONTEXT_LENGTH_SETTING == 'auto' else 'manual'
    print(f"  System: {_system_ram}GB RAM | Model max context: {_model_max_ctx or 'unknown'}", file=_sys.stderr)
    print(f"  Token limits: context={OLLAMA_CONTEXT_LENGTH}, predict={OLLAMA_NUM_PREDICT} ({_mode})", file=_sys.stderr)

# System prompt for the assistant
LLM_SYSTEM_PROMPT = """You are Daedalus, a knowledgeable audio plugin assistant. You help the user find the right plugins for their task.

You receive three kinds of context for each question:
- **Web research** — current real-world plugin information pulled from the web. This is the PRIMARY SOURCE for technical facts (developers, technology, emulations, features).
- **User's scanned collection** — plugins the user actually has installed (marked with ✓). Shown with the user's own metadata/notes.
- **DAW stock plugins** — plugins bundled with the user's DAW(s) (marked with 🎛️). The user has access to these because they own the DAW.

CRITICAL RULES — read carefully:

1. **Web research is the source of truth for facts.** When the web research mentions technical details about a plugin (developer, technology, emulation claims), trust those over your training data. If web research is absent or insufficient, say so rather than inventing.

2. **The collection and stock sections tell you what the user has access to — not what is technically true about a plugin.** Use them to decide WHAT to recommend, not to guess technical specs.

3. **NEVER invent technical facts.** If the provided context doesn't mention a feature, developer, or technology, do NOT claim the plugin has it. Don't add information from your training data that isn't grounded in the provided context.

4. **Label every plugin you recommend** with one of these markers:
   - `✓` — plugin is in the user's scanned collection (preferred recommendation)
   - `🎛️` — plugin is bundled with one of the user's DAWs
   - `[NOT INSTALLED]` — mentioned in web research but user has neither scanned nor DAW-stock access. Suggest this only if nothing installed fits, and mention the user can use "Search Online" for more info.

5. **Prefer ✓ first, then 🎛️, then [NOT INSTALLED].** When multiple options fit, rank by availability — the user shouldn't have to buy a plugin to solve a problem if they already own a good alternative.

When answering:
- Be specific about plugin names and why each is suited to the task
- Compare plugins when relevant ("X is more transparent, Y adds more color")
- Reference the signal chain position when relevant
- If you're unsure about a specific plugin, say so — don't guess

Previous user queries may be included for preference context. Use them to understand the user's workflow and taste, but ALWAYS verify against the current context.

The user is an experienced audio engineer and plugin developer. Be technical and precise."""

# ──────────────────────────────────────────────
# ChromaDB / Embeddings
# ──────────────────────────────────────────────
CHROMA_COLLECTION_NAME = "plugin_embeddings"
EMBEDDING_MODEL = "nomic-embed-text"  # via Ollama - fast, good quality
EMBEDDING_BATCH_SIZE = 50
SEMANTIC_SEARCH_TOP_K = 15     # how many results to return from vector search
SQL_SEARCH_LIMIT = 20          # how many results from structured SQL search

# ──────────────────────────────────────────────
# RAG Pipeline
# ──────────────────────────────────────────────
RAG_MAX_CONTEXT_PLUGINS = 20            # max plugins to include in LLM context
STOCK_PLUGINS_MAX_IN_CONTEXT = 60        # cap on DAW stock plugins injected
RAG_WEB_MAX_CHARS = 3500                 # max chars budget for web context
RAG_WEB_PAGE_MAX_CHARS = 1500            # per-page fetch truncation in web section

# Section templates — assembled by rag.build_context()
RAG_WEB_SECTION_TEMPLATE = """Web research (PRIMARY SOURCE for technical facts — use these facts over your training data):

{web_context}

"""

RAG_COLLECTION_SECTION_TEMPLATE = """User's scanned plugin collection (✓ — these ARE installed locally):

{plugin_context}

"""

RAG_STOCK_SECTION_TEMPLATE = """DAW stock plugins bundled with the user's DAW(s) — {daw_list} (🎛️ — the user has these because they own the DAW):

{stock_context}

"""

RAG_CONTEXT_TEMPLATE = """{web_section}{collection_section}{stock_section}LEGEND:
  ✓              = plugin is in the user's scanned collection (prefer these)
  🎛️             = stock plugin bundled with the user's DAW(s)
  [NOT INSTALLED] = mentioned in web research but not owned — suggest only if nothing installed fits

Based on the above, answer the user's question. Ground every technical claim in the web research or the provided metadata — never invent. When recommending, prefer ✓ first, then 🎛️, and only suggest [NOT INSTALLED] plugins when nothing installed fits."""

# ──────────────────────────────────────────────
# UI Preferences
# ──────────────────────────────────────────────
UI_THEME = "dark"              # 'dark' or 'light'
UI_TITLE = "Daedalus Plugin Assistant"
UI_PLUGINS_PER_PAGE = 50
UI_SHOW_REVIEW_BADGE = True    # show count of plugins needing review

# ──────────────────────────────────────────────
# Scanner
# ──────────────────────────────────────────────
SCANNER_SKIP_EXTENSIONS = {".xml", ".eng", ".n2s", ".aqu", ".aut"}  # non-plugin files in AU folders
SCANNER_SKIP_PATTERNS = ["old test plugins"]  # directories/files to skip

# ──────────────────────────────────────────────
# Own Plugin Detection
# ──────────────────────────────────────────────
# Add your own plugin names here, grouped by brand.
# The scanner uses these to flag plugins as "own" in the database.
# Example:
#   "MyDSP": ["MyCompressor", "MySynth"],
#   "Prototypes": ["TestPlugin1", "TestPlugin2"],
OWN_PLUGIN_BRANDS = {
    # "MyDSP": [
    #     "MyPlugin1", "MyPlugin2",
    # ],
    # "Prototypes": [
    #     "TestCompressor", "TestEQ",
    # ],
}

# ──────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_TO_FILE = True
LOG_FILE = LOG_DIR / "plugin_assistant.log"
LOG_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
LOG_BACKUP_COUNT = 3

# ──────────────────────────────────────────────
# Backup
# ──────────────────────────────────────────────
BACKUP_ON_STARTUP = True
BACKUP_MAX_KEEP = 10           # max number of backup files to retain
