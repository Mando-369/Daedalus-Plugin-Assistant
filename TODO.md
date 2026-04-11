# Daedalus Plugin Assistant - TODO

## Completed
- [x] Git repo init + push to GitHub
- [x] Auto-detect compatible Python (3.10-3.13) in run.sh with venv setup
- [x] Fix duplicate ChromaDB embedding IDs (use DB primary key)
- [x] Fix empty chat responses (increase num_predict for qwen3.5 thinking model)
- [x] Set context/predict limits to match system specs (M4 Max 128GB: 32k ctx, 16k predict)

## In Progress
- [ ] Functional testing and verification

## Planned Features
- [ ] Render `<think>` tags as styled/collapsible reasoning block in chat UI
- [ ] Persistent chat history with search (SQLite-backed, survives page refresh)
- [ ] Plugin enrichment service: automated per-plugin detection + web search to populate full metadata (developer, description, category, character, signal chain position, etc.) for plugins the classifier can't fully identify
- [ ] LLM Settings tab in UI — let users configure their LLM backend:
  - Local Ollama (auto-detected models, system spec check)
  - Remote Ollama (custom URL for cloud-hosted instances)
  - Cloud providers: Qwen API, DeepSeek API, OpenAI-compatible endpoints
  - Model selection with capability info (size, context window, speed)
  - API key management (stored locally, never sent to our servers)
  - For users who can't run local LLMs due to hardware limitations
