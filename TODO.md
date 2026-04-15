# Daedalus Plugin Assistant - TODO

## Completed
- [x] Git repo init + push to GitHub
- [x] Auto-detect compatible Python (3.10-3.13) in run.sh with venv setup
- [x] Fix duplicate ChromaDB embedding IDs (use DB primary key)
- [x] Fix empty chat responses (streaming for thinking models)
- [x] Set context/predict limits to match system specs (auto-detection)
- [x] Developer extraction from AU/VST3 bundle Info.plist metadata
- [x] Plugin type extraction from AU type codes (aufx/aumu)
- [x] Cross-format metadata propagation (AU → VST3)
- [x] Display names from plist (developer's own naming, not filename heuristics)
- [x] Autonomous enrichment agents (Product Info + Sonic Profile) with tool-calling
- [x] SearXNG self-hosted search backend (replaces rate-limited DuckDuckGo)
- [x] Per-plugin enrichment with optional URL/PDF input
- [x] Agent quality self-check (retry if results are thin)
- [x] Persistent multi-conversation chat history with sidebar + search
- [x] Markdown rendering in chat responses
- [x] Search Online in chat (per-response + global search button)
- [x] Confidence auto-evaluation on save and enrichment
- [x] Stop word filtering in RAG search
- [x] ChromaDB telemetry disabled
- [x] run.sh auto-starts Ollama, SearXNG, frees port
- [x] README + GPL v3 license

## Planned Features

### LLM Settings & Online Fallback
- [ ] Settings tab in UI for LLM backend configuration:
  - Local Ollama (auto-detected models, system spec check)
  - Remote Ollama (custom URL for cloud-hosted instances)
  - Cloud providers via OpenAI-compatible API:
    - Google Gemini 2.5 Flash / 3.0 Flash-Lite (recommended online default: free tier 1000 req/day, 1M+ token context)
    - OpenAI, Anthropic, DeepSeek, Qwen API
  - Model selection with capability info (size, context window, speed)
  - API key management (stored locally in SQLite, never leaves the machine)
- [ ] Auto-fallback: detect small systems (<16GB RAM) and suggest/enable online LLM (Gemini free tier)
- [ ] Separate model config per purpose:
  - Chat: larger/cloud model for better responses (Gemini Flash or local 26B+)
  - Agents: fast local model for tool-calling decisions (Gemma 4 26B or Qwen 3.5 14B)
  - Embeddings: keep nomic-embed-text local (fast, no API needed)
- [ ] Recommended defaults by system:
  - Mac 32GB+: Gemma 4 26B local (all purposes)
  - Mac 16GB: Qwen 3.5 14B Q4 local (~9GB, 45 tok/s)
  - Windows 16GB VRAM: Gemma 4 26B-A4B via LM Studio
  - Low-spec / no GPU: Gemini Flash online (free)
- [ ] Test connection button in settings

### Enrichment Improvements
- [ ] Bulk enrichment progress in UI (currently basic WebSocket updates)
- [ ] Auto-enrich newly scanned plugins (prompt user after scan)
- [ ] LLM searches chat history for faster answers
- [ ] Enrichment queue with pause/resume

### UI/UX
- [ ] Render `<think>` tags as styled/collapsible reasoning block in chat UI
- [ ] Plugin comparison view (side-by-side metadata)
- [ ] Export/import plugin database (JSON/CSV)
- [ ] Dark/light theme toggle
