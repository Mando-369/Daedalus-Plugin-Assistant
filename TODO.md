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
  - Cloud providers: OpenAI, Anthropic, Google, DeepSeek, Qwen API
  - OpenAI-compatible endpoints (covers most providers)
  - Model selection with capability info (size, context window, speed)
  - API key management (stored locally in SQLite, never leaves the machine)
- [ ] Auto-fallback: detect small systems (<16GB RAM) and suggest/enable online LLM
- [ ] Separate model config per purpose: chat model vs agent model (e.g. fast local for agents, powerful cloud for chat)
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
