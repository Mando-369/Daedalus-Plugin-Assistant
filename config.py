"""
Daedalus Plugin Assistant - Central Configuration
All adjustable parameters live here. Nothing hardcoded elsewhere.
"""

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
        "path": os.path.expanduser("~/Library/Audio/Plug-Ins/Components"),
        "format": "AU",
        "scope": "user",
        "extension": ".component",
    },
    {
        "path": os.path.expanduser("~/Library/Audio/Plug-Ins/VST3"),
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
# Ollama / LLM
# ──────────────────────────────────────────────
OLLAMA_BASE_URL = "http://127.0.0.1:11434"
OLLAMA_MODEL = "qwen3.5:9b-nvfp4"  # adjust to your pulled model name
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

# Log what was detected (visible in run.sh output)
print(f"  System: {_system_ram}GB RAM | Model max context: {_model_max_ctx or 'unknown'}")
print(f"  Token limits: context={OLLAMA_CONTEXT_LENGTH}, predict={OLLAMA_NUM_PREDICT}"
      f" ({'auto' if OLLAMA_CONTEXT_LENGTH_SETTING == 'auto' else 'manual'})")

# System prompt for the assistant
LLM_SYSTEM_PROMPT = """You are Daedalus, a knowledgeable audio plugin assistant. You help the user manage,
understand, and find the right plugins from their personal collection.

You have access to a database of the user's installed audio plugins with detailed metadata
including categories, specialties, best use cases, and sonic character.

When answering:
- Be specific about plugin names and their strengths
- Compare plugins when relevant ("X is more transparent, Y adds more color")
- Mention hidden features or lesser-known use cases when you know them
- If multiple plugins could work, rank them by suitability
- Reference the signal chain position when relevant
- If you're unsure about a specific plugin, say so

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
RAG_MAX_CONTEXT_PLUGINS = 12   # max plugins to include in LLM context
RAG_CONTEXT_TEMPLATE = """Here are relevant plugins from the user's collection:

{plugin_context}

Based on this information, answer the user's question."""

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
