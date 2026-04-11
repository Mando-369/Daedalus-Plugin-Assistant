"""
Daedalus Plugin Assistant - Central Configuration
All adjustable parameters live here. Nothing hardcoded elsewhere.
"""

import os
from pathlib import Path

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
OLLAMA_CONTEXT_LENGTH = 8192   # max context window tokens
OLLAMA_TEMPERATURE = 0.3       # lower = more factual, higher = more creative
OLLAMA_TOP_P = 0.9
OLLAMA_NUM_PREDICT = 2048      # max tokens in response
OLLAMA_KEEP_ALIVE = "10m"      # keep model loaded in memory

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
OWN_PLUGIN_BRANDS = {
    "Mandolini Audio": [
        "THE LIMITER", "THE TRANSFORMER", "THE-GRAPHIC-EQ",
        "TM_THE_GRAPHIC_EQ", "TM_THE_TRANSFORMER", "TM IR Convolver",
        "TM_FSM_TAPE_5_proto2", "TM700V2",
    ],
    "OmegaDSP": [
        "Angelizer", "Gravitas", "Kalos", "Symmetria", "Polymera",
        "Magnetic Master Suite", "Xenia", "XeniaFX",
        "OsTIrus", "OsTIrusFX", "Osirus", "OsirusFX",
        "Vavra", "VavraFX", "thauma",
    ],
    "Development/Prototype": [
        "FirstDSP", "SimpleAnalogSaturation", "TransparentClipper",
        "BJT Clipper", "ZenerCapSat", "XMCompressor", "XMEQ", "XMLimiter",
        "XMTape&Clip", "XMTubePre", "TUDI_Limiter", "EQP-WDF-1A",
        "MASTERING_EQ_FAUST", "FSM_Tape", "FSM_Tape_LUT",
        "FSMInspiredTapeModel", "JA_Hysteresis", "Polarity-MD",
        "ja_tabulateNd", "ja_streaming_bias", "jahysteresis",
        "TS_Derivative", "TS_FIR", "TS_IIR_Gauss", "TS_Slew",
        "FAUST_TX81Z", "Ultramaster KR-106", "InOut_Transformer",
        "NodalRed2x",
    ],
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
