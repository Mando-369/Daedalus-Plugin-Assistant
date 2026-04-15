#!/usr/bin/env bash
# ──────────────────────────────────────────────────
# Daedalus Plugin Assistant - Startup Script
# Checks prerequisites, starts services, and launches the server.
# ──────────────────────────────────────────────────

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}═══════════════════════════════════════════${NC}"
echo -e "${CYAN}  Daedalus Plugin Assistant${NC}"
echo -e "${CYAN}═══════════════════════════════════════════${NC}"
echo

# ── Find compatible Python (3.10–3.13) ───────
echo -e "${YELLOW}[1/6]${NC} Checking Python..."
PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" &>/dev/null; then
        PY_VER=$("$candidate" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)
        PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
        PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
        if [ "$PY_MAJOR" = "3" ] && [ "$PY_MINOR" -ge 10 ] && [ "$PY_MINOR" -le 13 ]; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo -e "${RED}  ✗ No compatible Python found. Please install Python 3.10–3.13.${NC}"
    exit 1
fi
PY_VERSION=$("$PYTHON" --version 2>&1)
echo -e "${GREEN}  ✓ $PY_VERSION ($(command -v "$PYTHON"))${NC}"

# ── Virtual environment & dependencies ───────
echo -e "${YELLOW}[2/6]${NC} Setting up environment..."
VENV_DIR="$SCRIPT_DIR/.venv"

if [ ! -d "$VENV_DIR" ]; then
    echo -e "  Creating virtual environment..."
    "$PYTHON" -m venv "$VENV_DIR"
    echo -e "${GREEN}  ✓ Virtual environment created${NC}"
fi

source "$VENV_DIR/bin/activate"

if ! python3 -c "import fastapi, uvicorn, chromadb, httpx, jinja2" 2>/dev/null; then
    echo -e "  Installing dependencies..."
    pip install -r requirements.txt --quiet
    echo -e "${GREEN}  ✓ Dependencies installed${NC}"
else
    echo -e "${GREEN}  ✓ All dependencies present${NC}"
fi

# ── Check & start Ollama ────────────────────
echo -e "${YELLOW}[3/6]${NC} Checking Ollama..."
OLLAMA_URL=$(python3 -c "from config import OLLAMA_BASE_URL; print(OLLAMA_BASE_URL)")
OLLAMA_MODEL=$(python3 -c "from config import OLLAMA_MODEL; print(OLLAMA_MODEL)")
EMBED_MODEL=$(python3 -c "from config import EMBEDDING_MODEL; print(EMBEDDING_MODEL)")

if ! curl -s "${OLLAMA_URL}/api/tags" >/dev/null 2>&1; then
    # Try to start Ollama
    if [ -d "/Applications/Ollama.app" ]; then
        echo -e "  Starting Ollama..."
        open -a Ollama
        sleep 3
    fi
fi

if curl -s "${OLLAMA_URL}/api/tags" >/dev/null 2>&1; then
    echo -e "${GREEN}  ✓ Ollama is running${NC}"

    # Check LLM model
    if curl -s "${OLLAMA_URL}/api/tags" | python3 -c "
import sys, json
data = json.load(sys.stdin)
models = [m['name'] for m in data.get('models', [])]
target = '${OLLAMA_MODEL}'
found = any(target.split(':')[0] in m for m in models)
sys.exit(0 if found else 1)
" 2>/dev/null; then
        echo -e "${GREEN}  ✓ LLM model '${OLLAMA_MODEL}'${NC}"
    else
        echo -e "${YELLOW}  ⚠ Model '${OLLAMA_MODEL}' not found. Pulling...${NC}"
        ollama pull "${OLLAMA_MODEL}" || echo -e "${RED}  ✗ Failed to pull model${NC}"
    fi

    # Check embedding model
    if curl -s "${OLLAMA_URL}/api/tags" | python3 -c "
import sys, json
data = json.load(sys.stdin)
models = [m['name'] for m in data.get('models', [])]
found = any('${EMBED_MODEL}'.split(':')[0] in m for m in models)
sys.exit(0 if found else 1)
" 2>/dev/null; then
        echo -e "${GREEN}  ✓ Embedding model '${EMBED_MODEL}'${NC}"
    else
        echo -e "${YELLOW}  ⚠ Embedding model '${EMBED_MODEL}' not found. Pulling...${NC}"
        ollama pull "${EMBED_MODEL}" || echo -e "${RED}  ✗ Failed to pull embedding model${NC}"
    fi
else
    echo -e "${RED}  ✗ Ollama is not running${NC}"
    echo -e "${YELLOW}    Install from https://ollama.com or start manually: ollama serve${NC}"
    echo -e "${YELLOW}    Continuing anyway (browsing/editing will work, chat won't)...${NC}"
fi

# ── Check & start SearXNG ───────────────────
echo -e "${YELLOW}[4/6]${NC} Checking SearXNG..."
SEARXNG_URL=$(python3 -c "from config import SEARXNG_URL; print(SEARXNG_URL)")

if curl -s "${SEARXNG_URL}" >/dev/null 2>&1; then
    echo -e "${GREEN}  ✓ SearXNG is running at ${SEARXNG_URL}${NC}"
elif command -v docker &>/dev/null && docker info &>/dev/null; then
    # Check if container exists but is stopped
    if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q '^searxng$'; then
        echo -e "  Starting existing SearXNG container..."
        docker start searxng >/dev/null 2>&1
        sleep 2
        if curl -s "${SEARXNG_URL}" >/dev/null 2>&1; then
            echo -e "${GREEN}  ✓ SearXNG started${NC}"
        else
            echo -e "${YELLOW}  ⚠ SearXNG container started but not responding yet (may need a moment)${NC}"
        fi
    else
        echo -e "  Creating SearXNG container..."
        SEARXNG_CONF="$SCRIPT_DIR/docker/searxng/settings.yml"
        docker run -d --name searxng -p 8888:8080 \
            -v "${SEARXNG_CONF}:/etc/searxng/settings.yml:ro" \
            searxng/searxng >/dev/null 2>&1
        sleep 5
        if curl -s "${SEARXNG_URL}" >/dev/null 2>&1; then
            echo -e "${GREEN}  ✓ SearXNG installed and started${NC}"
        else
            echo -e "${YELLOW}  ⚠ SearXNG container created but not responding yet (may need a moment)${NC}"
        fi
    fi
elif command -v docker &>/dev/null; then
    echo -e "${YELLOW}  ⚠ Docker is installed but not running${NC}"
    echo -e "${YELLOW}    Open Docker Desktop first, then restart this script${NC}"
    echo -e "${YELLOW}    Falling back to DuckDuckGo (may rate-limit)${NC}"
else
    echo -e "${YELLOW}  ⚠ Docker not installed${NC}"
    echo -e "${YELLOW}    Install Docker Desktop from https://docker.com${NC}"
    echo -e "${YELLOW}    Falling back to DuckDuckGo (may rate-limit)${NC}"
fi

# ── Initialize Database ──────────────────────
echo -e "${YELLOW}[5/6]${NC} Initializing database..."
python3 -c "from src.models import init_db; init_db()" 2>/dev/null || \
python3 -c "
import sys; sys.path.insert(0, '.')
from src.models import init_db; init_db()
"
echo -e "${GREEN}  ✓ Database ready${NC}"

# ── Create directories ────────────────────────
mkdir -p data logs static/css static/js templates

# ── Kill any existing server on the port ─────
WEB_HOST=$(python3 -c "from config import WEB_HOST; print(WEB_HOST)")
WEB_PORT=$(python3 -c "from config import WEB_PORT; print(WEB_PORT)")

if lsof -ti:"${WEB_PORT}" >/dev/null 2>&1; then
    echo -e "${YELLOW}  Freeing port ${WEB_PORT}...${NC}"
    lsof -ti:"${WEB_PORT}" | xargs kill 2>/dev/null
    sleep 1
fi

# ── Start Server ─────────────────────────────
echo -e "${YELLOW}[6/6]${NC} Starting server..."
echo
echo -e "${GREEN}═══════════════════════════════════════════${NC}"
echo -e "${GREEN}  http://${WEB_HOST}:${WEB_PORT}${NC}"
echo -e "${GREEN}  Press Ctrl+C to stop${NC}"
echo -e "${GREEN}═══════════════════════════════════════════${NC}"
echo

python3 -m uvicorn src.app:app --host "${WEB_HOST}" --port "${WEB_PORT}" --reload
