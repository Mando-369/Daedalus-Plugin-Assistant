# Daedalus Plugin Assistant

A local macOS application that manages, classifies, and provides intelligent search across your AU and VST3 audio plugin collection using autonomous AI agents and a local LLM via Ollama.

## Features

- **Automatic Plugin Discovery** -- Scans standard macOS plugin directories for AU and VST3 formats
- **Metadata Extraction** -- Reads developer names and plugin types directly from bundle Info.plist files, with cross-format propagation (AU metadata shared to VST3)
- **Static Classification** -- 1000+ known plugins pre-classified with developer, category, character, and use case data
- **Autonomous AI Enrichment** -- Goal-oriented agents with LLM tool-calling that research plugins autonomously:
  - **Product Info Agent** -- Finds developer, category, description, hardware emulation details from product pages and KVR
  - **Sonic Profile Agent** -- Finds sonic character, use cases, pro tips, and limitations from real user discussions on forums
  - **Quality self-check** -- Agents evaluate their own results and retry with different search strategies if data is thin
- **SearXNG Search** -- Self-hosted metasearch engine (Docker) aggregating Google, Bing, Brave, and DuckDuckGo without rate limits. Falls back to DuckDuckGo if not running.
- **RAG-Powered Chat** -- Ask natural language questions about your plugins with hybrid SQL + semantic search, markdown-rendered responses, and persistent multi-conversation history
- **Per-Plugin Enrichment** -- Enrich individual plugins with optional user-provided URLs or PDF manuals
- **Bulk Enrichment** -- Batch-process all unclassified plugins with streaming progress
- **Chat History** -- SQLite-backed multi-conversation history with sidebar, search, and individual delete
- **Browse, Review, Edit** -- Grid-based plugin browser with filters, review queue, and full metadata editor including hidden tips and limitations fields

## Prerequisites

- **macOS** (scans `/Library/Audio/Plug-Ins/` directories)
- **Python 3.10 - 3.13**
- **Ollama** -- local LLM inference -- [ollama.com](https://ollama.com)
- **Docker** -- for SearXNG (optional but recommended) -- [docker.com](https://www.docker.com/products/docker-desktop/)
- **16GB+ RAM** recommended (32GB+ for larger models)

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/Mando-369/Daedalus-Plugin-Assistant.git
cd Daedalus-Plugin-Assistant

# 2. Run the app -- handles everything automatically
./run.sh
```

That's it. `run.sh` automatically:
- Finds a compatible Python and sets up a virtual environment
- Installs all dependencies
- Starts Ollama (opens the app if installed)
- Starts SearXNG via Docker (creates the container on first run, restarts it on subsequent runs)
- Frees the server port if something is already using it
- Initializes the database
- Launches the server at [http://127.0.0.1:8777](http://127.0.0.1:8777)

### Manual Setup (if you prefer)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Start Ollama and pull models
ollama serve
ollama pull gemma4:26b
ollama pull nomic-embed-text

# Start SearXNG (optional, runs in a Docker container for clean isolation)
docker run -d --name searxng -p 8888:8080 \
  -e SEARXNG_SECRET=$(openssl rand -hex 32) \
  searxng/searxng

# Start the app
python -m uvicorn src.app:app --host 127.0.0.1 --port 8777
```

### Why SearXNG runs in Docker

SearXNG is a web service that proxies searches to Google, Bing, and others. Docker keeps it cleanly isolated -- no system pollution, no Python conflicts with the app, easy to remove (`docker rm searxng`), and simple to restart. It runs locally; no data leaves your machine beyond the search queries themselves.

## Usage

### Scanning Plugins

Click **Rescan Plugins** to discover all installed AU and VST3 plugins. The scanner:
1. Reads plugin directories on disk
2. Extracts developer and plugin type from bundle metadata (Info.plist)
3. Cross-references AU metadata to VST3 versions of the same plugin
4. Runs static classification against 1000+ known plugins
5. Builds vector embeddings for semantic search
6. Detects newly installed plugins and reports them for enrichment

### Chat

Ask questions in natural language:
- "What compressor plugins do I have?"
- "I need a warm, vintage-sounding EQ for mastering"
- "Compare my optical compressors"
- "Which plugins emulate the LA-2A?"

The assistant searches your plugin database using hybrid SQL FTS + semantic vector search, then generates a contextual answer with your local LLM. Responses render with full markdown formatting (headers, lists, code, bold).

Conversations are saved automatically and accessible from the sidebar. Search past conversations or start a new one anytime.

### Enrichment

#### Per-Plugin (Edit Modal)
1. Click any plugin to open the edit modal
2. Click **Enrich** to run autonomous research agents
3. Optionally expand "Provide additional context" and paste a URL or PDF path
4. Agents autonomously search the web, fetch product pages, and fill empty metadata
5. If results are thin, agents self-evaluate and retry with different search strategies
6. Review the auto-filled fields and save

#### Bulk (Review Tab)
1. Go to the **Review** tab
2. Click **Enrich with Web Search**
3. Watch streaming progress as agents process each unclassified plugin

### Editing & Review

- Click any plugin card to open the full metadata editor
- Edit all fields: developer, category, character, description, hidden tips, limitations, etc.
- Confidence dot turns green automatically when key fields are filled (via enrichment or manual edit)
- Check "My own plugin" for plugins you developed

## Configuration

Key settings in `config.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `OLLAMA_MODEL` | `gemma4:26b` | LLM model for chat and enrichment agents |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama API endpoint |
| `SEARXNG_URL` | `http://127.0.0.1:8888` | SearXNG instance URL |
| `WEB_PORT` | `8777` | Web server port |
| `PLUGIN_SCAN_DIRS` | Standard macOS paths | Directories to scan for AU, VST3 plugins |
| `EMBEDDING_MODEL` | `nomic-embed-text` | Model for semantic search embeddings |
| `RAG_MAX_CONTEXT_PLUGINS` | `20` | Max plugins included in LLM context |
| `OWN_PLUGIN_BRANDS` | `{}` | Your own plugin brand names for detection |

## Architecture

```
                        Plugin directories on disk
                         (AU, VST3 bundles)
                                  |
                                  v
                         scan_plugins() + plist
                         (developer, plugin_type)
                                  |
                                  v
                    classify_all() (1000+ known plugins)
                                  |
                                  v
                           SQLite Database
                       (1599 plugins + metadata)
                          /              \
                         v                v
              Enrichment Agents      RAG Chat Pipeline
                    |                     |
         +─────────+─────────+    hybrid search (SQL + vector)
         |                   |            |
         v                   v            v
  Product Info Agent   Sonic Profile    LLM Generation
  (category, desc,    Agent (character,  (gemma4:26b)
   emulation)          tips, limits)        |
         |                   |              v
         v                   v       Markdown Response
     SearXNG ─────────> fetch_page    + Chat History
  (Google, Bing,        (meta tags,
   Brave, DDG)          JSON-LD)
```

### File Structure

```
src/
  app.py              FastAPI web app + API + WebSocket endpoints
  models.py           SQLite schema + migrations (plugins, conversations, messages)
  scanner.py          Plugin directory scanner + plist metadata extraction
  classifier.py       Static classification database (1000+ plugins)
  embeddings.py       ChromaDB vector store wrapper
  rag.py              RAG pipeline (hybrid search + streaming LLM generation)
  enrichment.py       Legacy enrichment service
  agents/
    base.py           Agent runner (LLM tool-calling loop + quality self-check)
    tools.py          Agent tools (web_search via SearXNG/DDG, fetch_page, read_pdf)
    product_agent.py  Product Info Agent (factual research)
    sonic_agent.py    Sonic Profile Agent (character + forum research)
    orchestrator.py   Enrichment orchestrator (runs agents, merges, applies to DB)

static/
  css/style.css       Dark theme stylesheet
  js/app.js           Frontend (chat, browse, edit, enrichment, conversations)
  favicon.svg         App icon

templates/
  index.html          Single-page app

data/
  plugins.db          SQLite database
  chroma/             ChromaDB vector store

config.py             Central configuration
run.sh                One-command startup (Python, Ollama, SearXNG, server)
```

## Tech Stack

- **Backend**: Python, FastAPI, SQLite, ChromaDB
- **LLM**: Ollama (local inference), gemma4:26b (recommended for tool-calling)
- **Embeddings**: nomic-embed-text via Ollama
- **Search**: SearXNG (self-hosted, Docker) with DuckDuckGo fallback
- **Frontend**: Vanilla JavaScript, CSS (dark theme)
- **Retrieval**: Hybrid SQL FTS5 + cosine-similarity vector search

## License

MIT
