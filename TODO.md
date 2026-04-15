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
- [x] Settings tab in UI with provider comparison table
- [x] Unified LLM client (Ollama + OpenAI-compatible APIs)
- [x] Providers: Local Ollama, Euria (Swiss/GDPR), OpenRouter (global free), Gemini, OpenAI, DeepSeek, Custom
- [x] Contextual hints with signup links per provider
- [x] API key management (stored locally in SQLite)
- [x] Separate model config for chat vs agents
- [x] System RAM detection with model recommendations
- [x] Test connection button
- [x] Embeddings always stay local (nomic-embed-text via Ollama)

### Enrichment Improvements
- [x] Bulk enrichment progress bar with real-time streaming
- [x] Enrichment queue with pause/resume/cancel + batch limits
- [x] Rate limit auto-detection and auto-pause
- [x] Configurable delay between plugins (throttling)
- [x] Dismiss button on review cards (exclude from enrichment)
- [x] Bulk enrichment skips own plugins
- [x] Re-enrich confirmation dialog (force replace vs fill-only)
- [x] Consistency validation (catches wrong-product data)
- [x] Live-refresh review list during enrichment
- [ ] Auto-enrich newly scanned plugins (prompt user after scan)
- [ ] LLM searches chat history for faster answers

### UI/UX
- [ ] Plugin comparison view (side-by-side metadata)
- [ ] Export/import plugin database (JSON/CSV)
- [ ] Dark/light theme toggle
