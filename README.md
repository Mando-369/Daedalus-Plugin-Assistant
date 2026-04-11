# Daedalus Plugin Assistant

A local macOS application that manages, classifies, and provides intelligent search across your AU, VST3, and AAX audio plugin collection using autonomous AI agents and a local LLM via Ollama.

## Features

- **Automatic Plugin Discovery** -- Scans standard macOS audio plugin directories for AU, VST3, and AAX formats
- **Metadata Extraction** -- Reads developer names and plugin types directly from bundle Info.plist files, with cross-format propagation (AU metadata shared to VST3/AAX)
- **Static Classification** -- 1000+ known plugins pre-classified with developer, category, character, and use case data
- **Autonomous AI Enrichment** -- Goal-oriented agents that research plugins via web search (DuckDuckGo, KVR, Gearspace) and LLM-powered analysis:
  - **Product Info Agent** -- Finds developer, category, description, hardware emulation details
  - **Sonic Profile Agent** -- Finds sonic character, use cases, pro tips, and limitations from real user discussions
- **RAG-Powered Chat** -- Ask natural language questions about your plugins ("I need a warm compressor for vocals") with hybrid SQL + semantic search
- **Per-Plugin Enrichment** -- Enrich individual plugins with optional user-provided URLs or PDF manuals
- **Bulk Enrichment** -- Batch-process all unclassified plugins with streaming progress
- **Browse, Review, Edit** -- Grid-based plugin browser with filters, review queue for auto-classified plugins, and full metadata editor

## Prerequisites

- **macOS** (scans `/Library/Audio/Plug-Ins/` directories)
- **Python 3.10 - 3.13**
- **Ollama** (local LLM inference) -- [ollama.com](https://ollama.com)
- **16GB+ RAM** recommended (32GB+ for larger models)

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/your-username/plugin-manager-assistant.git
cd plugin-manager-assistant

# 2. Start Ollama
ollama serve

# 3. Start SearXNG (local search engine -- recommended)
docker run -d --name searxng -p 8888:8080 \
  -e SEARXNG_SECRET=$(openssl rand -hex 32) \
  searxng/searxng

# 4. Run the app (auto-creates venv, pulls model if needed)
./run.sh

# 5. Open in browser
open http://127.0.0.1:8777
```

> **SearXNG is optional but recommended.** It aggregates results from Google, Bing, Brave, and DuckDuckGo without rate limits. Without it, the app falls back to DuckDuckGo which rate-limits after heavy use.

Or manually:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
ollama pull gemma4:26b
ollama pull nomic-embed-text
python -m uvicorn src.app:app --host 127.0.0.1 --port 8777
```

## Usage

### Scanning Plugins

Click **Rescan Plugins** to discover all installed AU, VST3, and AAX plugins. The scanner:
1. Reads plugin directories on disk
2. Extracts developer and type from bundle metadata (Info.plist)
3. Runs static classification against known plugin database
4. Builds search embeddings for the RAG chat

### Chat

Ask questions in natural language:
- "What compressor plugins do I have?"
- "I need a warm, vintage-sounding EQ for mastering"
- "Compare my SSL compressors"

The assistant searches your plugin database using hybrid SQL + semantic search, then generates a contextual answer using your local LLM.

### Enrichment

#### Per-Plugin (Edit Modal)
1. Click any plugin to open the edit modal
2. Click **Enrich** to run autonomous research agents
3. Optionally provide a URL (product page) or PDF manual path for better results
4. Agents search the web, fetch pages, and fill empty metadata fields
5. Review the auto-filled fields and save

#### Bulk (Review Tab)
1. Go to the **Review** tab
2. Click **Enrich with Web Search**
3. Watch streaming progress as agents process each unclassified plugin
4. All enriched plugins are flagged for review

### Editing & Review

- Click any plugin card to open the full metadata editor
- Edit all fields: developer, category, character, description, tips, limitations, etc.
- Check "My own plugin" for plugins you developed
- Save marks the plugin as reviewed

## Configuration

Key settings in `config.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `OLLAMA_MODEL` | `gemma4:26b` | LLM model for chat and enrichment |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama API endpoint |
| `WEB_PORT` | `8777` | Web server port |
| `PLUGIN_SCAN_DIRS` | Standard macOS paths | Directories to scan for plugins |
| `EMBEDDING_MODEL` | `nomic-embed-text` | Model for semantic search embeddings |
| `RAG_MAX_CONTEXT_PLUGINS` | `12` | Max plugins included in LLM context |
| `OWN_PLUGIN_BRANDS` | `{}` | Your own plugin brand names for detection |

## Architecture

```
scan_plugins()          Plugin directories on disk
      |                      |
      v                      v
  Info.plist -----> developer, plugin_type (AU type codes)
      |
      v
  classify_all()        Static classifier (1000+ known plugins)
      |
      v
  SQLite DB             1599 plugins with metadata
      |
      v
  Enrichment Agents     Autonomous web research
      |                      |
      |          +-----------+-----------+
      |          |                       |
      v          v                       v
  Product Info Agent              Sonic Profile Agent
  (developer, category,          (character, tips,
   description, emulation)        use cases, limitations)
      |          |                       |
      +----------+-----------+-----------+
                             |
                             v
                    ChromaDB Embeddings
                             |
                             v
                    RAG Chat Pipeline
                    (hybrid search + LLM)
```

### File Structure

```
src/
  app.py              FastAPI web app + API endpoints
  models.py           SQLite schema + migrations
  scanner.py          Plugin directory scanner + plist parser
  classifier.py       Static classification database (1000+ plugins)
  embeddings.py       ChromaDB vector store wrapper
  rag.py              RAG pipeline (hybrid search + LLM generation)
  enrichment.py       Legacy enrichment service
  agents/
    base.py           Agent runner (LLM tool-calling loop)
    tools.py          Agent tools (web_search, fetch_page, read_pdf)
    product_agent.py  Product Info Agent
    sonic_agent.py    Sonic Profile Agent
    orchestrator.py   Enrichment orchestrator

static/               CSS + JavaScript frontend
templates/            HTML templates
data/                 SQLite DB + ChromaDB store
config.py             Central configuration
run.sh                Startup script
```

## Tech Stack

- **Backend**: Python, FastAPI, SQLite, ChromaDB
- **LLM**: Ollama (local inference), gemma4:26b (recommended) / qwen3.5
- **Embeddings**: nomic-embed-text via Ollama
- **Frontend**: Vanilla JavaScript, CSS (dark theme)
- **Search**: Hybrid SQL FTS5 + cosine-similarity vector search

## License

MIT
