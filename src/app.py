"""
Daedalus Plugin Assistant - FastAPI Web Application
REST API + WebSocket chat + CRUD for plugin management.
"""

import asyncio
import json
import os
import sys
import traceback
from pathlib import Path
from datetime import datetime

# Kill ChromaDB telemetry before anything imports it
os.environ["ANONYMIZED_TELEMETRY"] = "False"
os.environ["CHROMA_TELEMETRY"] = "False"

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

from config import (
    BASE_DIR, WEB_HOST, WEB_PORT, WEB_RELOAD, WEB_LOG_LEVEL,
    UI_TITLE, UI_PLUGINS_PER_PAGE,
)
from src.models import get_db, init_db
from src.scanner import scan_plugins
from src.classifier import classify_all
from src.embeddings import PluginEmbeddingStore
from src.rag import RAGPipeline

# ── App Setup ──────────────────────────────────────

app = FastAPI(title=UI_TITLE, version="1.0.0")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Lazy-initialized singletons
_rag: RAGPipeline | None = None
_embeddings: PluginEmbeddingStore | None = None


def get_rag() -> RAGPipeline:
    global _rag
    if _rag is None:
        _rag = RAGPipeline()
    return _rag


def get_embeddings() -> PluginEmbeddingStore:
    global _embeddings
    if _embeddings is None:
        _embeddings = PluginEmbeddingStore()
    return _embeddings


# ── Pydantic Models ────────────────────────────────

class PluginUpdate(BaseModel):
    display_name: Optional[str] = None
    developer: Optional[str] = None
    plugin_type: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    subtype: Optional[str] = None
    emulation_of: Optional[str] = None
    description: Optional[str] = None
    specialty: Optional[str] = None
    best_used_for: Optional[str] = None
    character: Optional[str] = None
    signal_chain_position: Optional[str] = None
    tags: Optional[str] = None
    notes: Optional[str] = None
    hidden_tips: Optional[str] = None
    not_ideal_for: Optional[str] = None
    is_own_plugin: Optional[bool] = None
    own_brand: Optional[str] = None
    needs_review: Optional[bool] = None


class ChatMessage(BaseModel):
    message: str
    history: Optional[list] = None


# ── Pages ──────────────────────────────────────────

@app.get("/")
async def index(request: Request):
    """Main page - serves the single-page app."""
    return templates.TemplateResponse("index.html", {
        "request": request,
        "title": UI_TITLE,
    })


# ── Plugin CRUD API ────────────────────────────────

@app.get("/api/plugins")
async def list_plugins(
    page: int = 1,
    per_page: int = UI_PLUGINS_PER_PAGE,
    category: str = None,
    plugin_type: str = None,
    developer: str = None,
    is_own: bool = None,
    needs_review: bool = None,
    format: str = None,
    search: str = None,
    sort_by: str = "name",
    sort_dir: str = "asc",
):
    """List plugins with filtering, pagination, and sorting."""
    conn = get_db()
    try:
        conditions = []
        params = []

        if category:
            conditions.append("category = ?")
            params.append(category)
        if plugin_type:
            conditions.append("plugin_type = ?")
            params.append(plugin_type)
        if developer:
            conditions.append("developer = ?")
            params.append(developer)
        if is_own is not None:
            conditions.append("is_own_plugin = ?")
            params.append(1 if is_own else 0)
        if needs_review is not None:
            conditions.append("needs_review = ?")
            params.append(1 if needs_review else 0)
        if format:
            conditions.append("format = ?")
            params.append(format)
        if search:
            conditions.append(
                "(name LIKE ? OR display_name LIKE ? OR developer LIKE ? OR tags LIKE ?)"
            )
            term = f"%{search}%"
            params.extend([term, term, term, term])

        where = " AND ".join(conditions) if conditions else "1=1"

        # Validate sort
        valid_sorts = ["name", "category", "developer", "plugin_type", "format", "updated_at"]
        if sort_by not in valid_sorts:
            sort_by = "name"
        sort_dir = "DESC" if sort_dir.lower() == "desc" else "ASC"

        # Consolidate: group same-name plugins across formats (AU/VST3)
        # Use the row with the best classification as the representative
        count_sql = f"""
            SELECT COUNT(DISTINCT LOWER(name)) as total
            FROM plugins WHERE {where}
        """
        total = conn.execute(count_sql, params).fetchone()["total"]

        # Fetch all matching rows, then consolidate in Python
        # (SQLite GROUP BY can't easily pick the "best" row + aggregate formats)
        data_sql = f"""
            SELECT * FROM plugins WHERE {where}
            ORDER BY {sort_by} {sort_dir}
        """
        rows = conn.execute(data_sql, params).fetchall()

        # Group by lowercase name, keep best-classified row, merge formats
        consolidated = {}
        confidence_rank = {"high": 3, "medium": 2, "low": 1, "unclassified": 0}
        for r in rows:
            row = dict(r)
            key = row["name"].lower()
            if key not in consolidated:
                row["formats"] = [row["format"]]
                row["all_ids"] = [row["id"]]
                consolidated[key] = row
            else:
                existing = consolidated[key]
                # Add format if not already present
                if row["format"] not in existing["formats"]:
                    existing["formats"].append(row["format"])
                existing["all_ids"].append(row["id"])
                # Replace representative if this row has better classification
                existing_rank = confidence_rank.get(existing.get("classification_confidence", ""), 0)
                new_rank = confidence_rank.get(row.get("classification_confidence", ""), 0)
                if new_rank > existing_rank:
                    formats = existing["formats"]
                    all_ids = existing["all_ids"]
                    consolidated[key] = row
                    consolidated[key]["formats"] = formats
                    consolidated[key]["all_ids"] = all_ids

        # Sort and paginate the consolidated list
        all_plugins = list(consolidated.values())
        offset = (page - 1) * per_page
        total = len(all_plugins)
        page_plugins = all_plugins[offset : offset + per_page]

        return {
            "plugins": page_plugins,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page,
        }
    finally:
        conn.close()


@app.get("/api/plugins/{plugin_id}")
async def get_plugin(plugin_id: int):
    """Get a single plugin by ID."""
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM plugins WHERE id = ?", (plugin_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Plugin not found")
        return dict(row)
    finally:
        conn.close()


@app.put("/api/plugins/{plugin_id}")
async def update_plugin(plugin_id: int, update: PluginUpdate):
    """Update a plugin's metadata (manual editing)."""
    conn = get_db()
    try:
        # Check plugin exists
        existing = conn.execute("SELECT id FROM plugins WHERE id = ?", (plugin_id,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Plugin not found")

        # Build dynamic UPDATE
        fields = {}
        data = update.model_dump(exclude_none=True)
        for key, value in data.items():
            if key == "is_own_plugin":
                fields["is_own_plugin"] = 1 if value else 0
            elif key == "needs_review":
                fields["needs_review"] = 1 if value else 0
            else:
                fields[key] = value

        if not fields:
            return {"status": "no changes"}

        fields["updated_at"] = datetime.now().isoformat()

        set_clause = ", ".join(f"{k} = ?" for k in fields.keys())
        values = list(fields.values()) + [plugin_id]

        conn.execute(f"UPDATE plugins SET {set_clause} WHERE id = ?", values)

        # Re-evaluate confidence based on filled key fields
        row = conn.execute("SELECT * FROM plugins WHERE id = ?", (plugin_id,)).fetchone()
        if row:
            p = dict(row)
            key_fields = ("developer", "category", "description", "character")
            filled = sum(1 for f in key_fields if p.get(f))
            if filled >= 3 and p.get("classification_confidence") != "high":
                conn.execute(
                    "UPDATE plugins SET classification_confidence = 'high', needs_review = 0 WHERE id = ?",
                    (plugin_id,),
                )

        conn.commit()

        # Re-embed this plugin
        row = conn.execute("SELECT * FROM plugins WHERE id = ?", (plugin_id,)).fetchone()
        if row:
            get_embeddings().upsert_plugins([dict(row)])

        return {"status": "updated", "plugin_id": plugin_id}
    finally:
        conn.close()


# ── Conversations API ─────────────────────────────

@app.get("/api/conversations")
async def list_conversations(search: str = None):
    """List all conversations, optionally filtered by search."""
    conn = get_db()
    try:
        if search:
            rows = conn.execute("""
                SELECT DISTINCT c.* FROM conversations c
                LEFT JOIN messages m ON m.conversation_id = c.id
                WHERE c.title LIKE ? OR m.content LIKE ?
                ORDER BY c.updated_at DESC
            """, (f"%{search}%", f"%{search}%")).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM conversations ORDER BY updated_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.post("/api/conversations")
async def create_conversation():
    """Create a new conversation."""
    conn = get_db()
    try:
        cursor = conn.execute("INSERT INTO conversations (title) VALUES ('New Chat')")
        conn.commit()
        conv_id = cursor.lastrowid
        row = conn.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


@app.get("/api/conversations/{conv_id}/messages")
async def get_messages(conv_id: int):
    """Get all messages in a conversation."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at",
            (conv_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.post("/api/conversations/{conv_id}/messages")
async def add_message(conv_id: int, message: dict):
    """Add a message to a conversation and auto-title if first user message."""
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES (?, ?, ?)",
            (conv_id, message["role"], message["content"]),
        )
        # Auto-title from first user message
        if message["role"] == "user":
            conv = conn.execute(
                "SELECT title FROM conversations WHERE id = ?", (conv_id,)
            ).fetchone()
            if conv and conv["title"] == "New Chat":
                title = message["content"][:50]
                if len(message["content"]) > 50:
                    title += "..."
                conn.execute(
                    "UPDATE conversations SET title = ? WHERE id = ?",
                    (title, conv_id),
                )
        conn.execute(
            "UPDATE conversations SET updated_at = datetime('now') WHERE id = ?",
            (conv_id,),
        )
        conn.commit()
        return {"status": "ok"}
    finally:
        conn.close()


@app.delete("/api/conversations/{conv_id}")
async def delete_conversation(conv_id: int):
    """Delete a conversation and its messages."""
    conn = get_db()
    try:
        conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
        conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
        conn.commit()
        return {"status": "deleted"}
    finally:
        conn.close()


# ── Metadata API ───────────────────────────────────

@app.get("/api/categories")
async def list_categories():
    """Get all categories with counts."""
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT category, COUNT(*) as count
            FROM plugins
            WHERE category IS NOT NULL
            GROUP BY category
            ORDER BY category ASC
        """).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.get("/api/developers")
async def list_developers():
    """Get all developers with counts."""
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT developer, COUNT(*) as count
            FROM plugins
            WHERE developer IS NOT NULL AND developer != ''
            GROUP BY developer
            ORDER BY developer ASC
        """).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.get("/api/subcategories")
async def list_subcategories():
    """Get all subcategories alphabetically."""
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT DISTINCT subcategory
            FROM plugins
            WHERE subcategory IS NOT NULL AND subcategory != ''
            ORDER BY subcategory ASC
        """).fetchall()
        return [r["subcategory"] for r in rows]
    finally:
        conn.close()


@app.get("/api/stats")
async def get_stats():
    """Dashboard statistics."""
    conn = get_db()
    try:
        total = conn.execute("SELECT COUNT(*) as c FROM plugins").fetchone()["c"]
        classified = conn.execute(
            "SELECT COUNT(*) as c FROM plugins WHERE classification_confidence IN ('high', 'medium')"
        ).fetchone()["c"]
        needs_review = conn.execute(
            "SELECT COUNT(*) as c FROM plugins WHERE needs_review = 1"
        ).fetchone()["c"]
        own_plugins = conn.execute(
            "SELECT COUNT(*) as c FROM plugins WHERE is_own_plugin = 1"
        ).fetchone()["c"]
        instruments = conn.execute(
            "SELECT COUNT(*) as c FROM plugins WHERE plugin_type = 'instrument'"
        ).fetchone()["c"]
        effects = conn.execute(
            "SELECT COUNT(*) as c FROM plugins WHERE plugin_type = 'effect'"
        ).fetchone()["c"]

        # Top categories
        top_cats = conn.execute("""
            SELECT category, COUNT(*) as count
            FROM plugins WHERE category IS NOT NULL
            GROUP BY category ORDER BY count DESC LIMIT 10
        """).fetchall()

        # Top developers
        top_devs = conn.execute("""
            SELECT developer, COUNT(*) as count
            FROM plugins WHERE developer IS NOT NULL AND developer != ''
            GROUP BY developer ORDER BY count DESC LIMIT 10
        """).fetchall()

        # Format breakdown
        formats = conn.execute("""
            SELECT format, COUNT(*) as count
            FROM plugins GROUP BY format
        """).fetchall()

        return {
            "total": total,
            "classified": classified,
            "needs_review": needs_review,
            "own_plugins": own_plugins,
            "instruments": instruments,
            "effects": effects,
            "top_categories": [dict(r) for r in top_cats],
            "top_developers": [dict(r) for r in top_devs],
            "formats": [dict(r) for r in formats],
            "embeddings_count": get_embeddings().count(),
        }
    finally:
        conn.close()


# ── Chat API (REST fallback) ──────────────────────

@app.post("/api/chat")
async def chat(msg: ChatMessage):
    """REST endpoint for chat (non-streaming)."""
    try:
        rag = get_rag()
        result = rag.query(msg.message, chat_history=msg.history)
        return result
    except Exception as e:
        traceback.print_exc()
        return {"answer": f"Error: {str(e)}", "sources": [], "source_count": 0}


# ── WebSocket Chat (Streaming) ────────────────────

@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """WebSocket endpoint for streaming chat responses."""
    await websocket.accept()

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            user_query = msg.get("message", "")
            history = msg.get("history", [])
            conv_id = msg.get("conversation_id")
            web_context = msg.get("web_context", "")  # optional web search results

            # Save user message to conversation
            if conv_id:
                conn = get_db()
                try:
                    conn.execute(
                        "INSERT INTO messages (conversation_id, role, content) VALUES (?, 'user', ?)",
                        (conv_id, user_query),
                    )
                    # Auto-title from first message
                    conv = conn.execute("SELECT title FROM conversations WHERE id = ?", (conv_id,)).fetchone()
                    if conv and conv["title"] == "New Chat":
                        title = user_query[:50] + ("..." if len(user_query) > 50 else "")
                        conn.execute("UPDATE conversations SET title = ? WHERE id = ?", (title, conv_id))
                    conn.execute("UPDATE conversations SET updated_at = datetime('now') WHERE id = ?", (conv_id,))
                    conn.commit()
                finally:
                    conn.close()

            try:
                rag = get_rag()

                # Search phase
                await websocket.send_json({
                    "type": "status",
                    "content": "Searching plugin database..."
                })

                plugins = await asyncio.to_thread(rag.hybrid_search, user_query)
                context = rag.build_context(plugins)

                # Append web search context if provided
                if web_context:
                    context += f"\n\nAdditional web research:\n{web_context}"

                sources = [
                    {
                        "name": p.get("display_name") or p.get("name", "Unknown"),
                        "category": p.get("category", ""),
                        "developer": p.get("developer", ""),
                    }
                    for p in plugins
                ]

                await websocket.send_json({
                    "type": "sources",
                    "content": sources,
                })

                # Generation phase - stream tokens (async, non-blocking)
                await websocket.send_json({
                    "type": "status",
                    "content": "Generating response..."
                })

                full_response = []
                async for token_type, token_text in rag.async_generate_stream(user_query, context, history):
                    await websocket.send_json({
                        "type": token_type,
                        "content": token_text,
                    })
                    if token_type == "content":
                        full_response.append(token_text)

                # Save assistant response to conversation
                if conv_id and full_response:
                    conn = get_db()
                    try:
                        conn.execute(
                            "INSERT INTO messages (conversation_id, role, content) VALUES (?, 'assistant', ?)",
                            (conv_id, "".join(full_response)),
                        )
                        conn.commit()
                    finally:
                        conn.close()

                await websocket.send_json({"type": "done"})

            except Exception as e:
                traceback.print_exc()
                await websocket.send_json({
                    "type": "error",
                    "content": str(e),
                })

    except WebSocketDisconnect:
        pass


# ── Web Search API ────────────────────────────────

class WebSearchRequest(BaseModel):
    query: str
    fetch_top: int = 2  # how many result pages to fetch full content


@app.post("/api/web-search")
async def web_search_api(request: WebSearchRequest):
    """Search the web via SearXNG/DDG and optionally fetch top result pages."""
    from src.agents.tools import web_search, fetch_page

    results = await asyncio.to_thread(web_search, request.query)

    # Fetch full content from top results
    enriched = []
    for r in results[:request.fetch_top]:
        url = r.get("url", "")
        if url and not r.get("error") and not r.get("info"):
            page_text = await asyncio.to_thread(fetch_page, url)
            r["page_content"] = page_text[:2000] if page_text else None
        enriched.append(r)

    # Keep remaining results without page content
    enriched.extend(results[request.fetch_top:])

    return {"results": enriched}


# ── Scan & Populate API ───────────────────────────

@app.post("/api/scan")
async def trigger_scan():
    """Scan plugin directories and populate the database."""
    try:
        # 1. Scan
        raw_plugins = scan_plugins()

        # 2. Classify
        classified = classify_all(raw_plugins)

        # 3. Insert into SQLite
        conn = get_db()
        inserted = 0
        updated = 0
        new_plugin_ids = []
        try:
            for p in classified:
                existing = conn.execute(
                    "SELECT id FROM plugins WHERE file_name = ? AND format = ? AND install_scope = ?",
                    (p["file_name"], p["format"], p["install_scope"])
                ).fetchone()

                if existing:
                    # Update existing entry (don't overwrite manual edits)
                    # Fill developer and plugin_type if currently empty
                    existing_row = conn.execute(
                        "SELECT developer, plugin_type FROM plugins WHERE id = ?",
                        (existing["id"],),
                    ).fetchone()

                    extra_sets = []
                    extra_vals = []
                    # Plist-extracted developer is ground truth -- always update
                    if p.get("developer") and p["developer"] != existing_row["developer"]:
                        extra_sets.append("developer = ?")
                        extra_vals.append(p["developer"])
                    # Same for plugin_type from AU type codes
                    if p.get("plugin_type") and p["plugin_type"] != existing_row["plugin_type"]:
                        extra_sets.append("plugin_type = ?")
                        extra_vals.append(p["plugin_type"])

                    set_clause = "name = ?, display_name = ?, file_path = ?, is_own_plugin = ?, own_brand = ?"
                    base_vals = [
                        p["name"], p["display_name"], p["file_path"],
                        1 if p.get("is_own_plugin") else 0,
                        p.get("own_brand"),
                    ]
                    if extra_sets:
                        set_clause += ", " + ", ".join(extra_sets)
                        base_vals.extend(extra_vals)

                    conn.execute(
                        f"UPDATE plugins SET {set_clause}, updated_at = datetime('now') WHERE id = ?",
                        base_vals + [existing["id"]],
                    )
                    updated += 1
                else:
                    cursor = conn.execute("""
                        INSERT INTO plugins (
                            name, display_name, developer, is_own_plugin, own_brand,
                            format, file_name, install_scope, file_path,
                            plugin_type, category, subcategory, subtype, emulation_of,
                            description, specialty, best_used_for, character,
                            signal_chain_position, tags, notes,
                            classification_confidence, needs_review
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        p["name"], p["display_name"], p.get("developer"),
                        1 if p.get("is_own_plugin") else 0, p.get("own_brand"),
                        p["format"], p["file_name"], p["install_scope"], p["file_path"],
                        p.get("plugin_type"), p.get("category"), p.get("subcategory"),
                        p.get("subtype"), p.get("emulation_of"),
                        p.get("description"), p.get("specialty"),
                        p.get("best_used_for"), p.get("character"),
                        p.get("signal_chain_position"), p.get("tags"),
                        p.get("notes"),
                        p.get("classification_confidence", "unclassified"),
                        1 if p.get("needs_review") else 0,
                    ))
                    new_plugin_ids.append(cursor.lastrowid)
                    inserted += 1

            conn.commit()
        finally:
            conn.close()

        # 4. Rebuild embeddings
        conn = get_db()
        try:
            all_plugins = [dict(r) for r in conn.execute("SELECT * FROM plugins").fetchall()]
        finally:
            conn.close()

        store = get_embeddings()
        store.delete_all()
        embedded = store.upsert_plugins(all_plugins)

        return {
            "status": "complete",
            "scanned": len(raw_plugins),
            "inserted": inserted,
            "updated": updated,
            "embedded": embedded,
            "new_plugin_ids": new_plugin_ids,
        }

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ── Enrichment API ────────────────────────────────

@app.websocket("/ws/enrich")
async def websocket_enrich(websocket: WebSocket):
    """WebSocket endpoint for streaming enrichment progress using autonomous agents."""
    await websocket.accept()

    try:
        data = await websocket.receive_text()
        msg = json.loads(data)
        limit = msg.get("limit")
        plugin_ids = msg.get("plugin_ids")

        from src.agents.orchestrator import EnrichmentOrchestrator
        orchestrator = EnrichmentOrchestrator()

        def _run_batch():
            return list(orchestrator.enrich_batch(
                plugin_ids=plugin_ids, limit=limit,
            ))

        results = await asyncio.to_thread(_run_batch)

        for progress in results:
            await websocket.send_json(progress)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        traceback.print_exc()
        try:
            await websocket.send_json({"type": "error", "error": str(e)})
        except Exception:
            pass


@app.get("/api/enrichment/status")
async def enrichment_status():
    """Check how many plugins need enrichment."""
    conn = get_db()
    try:
        needs = conn.execute("""
            SELECT COUNT(DISTINCT LOWER(name)) as count
            FROM plugins
            WHERE classification_confidence IN ('unclassified', 'low')
               OR developer IS NULL OR developer = ''
               OR description IS NULL OR description = ''
        """).fetchone()["count"]
        return {"needs_enrichment": needs}
    finally:
        conn.close()


class EnrichRequest(BaseModel):
    url: Optional[str] = None
    pdf_path: Optional[str] = None


@app.post("/api/plugins/{plugin_id}/enrich")
async def enrich_plugin(plugin_id: int, request: EnrichRequest = EnrichRequest()):
    """Enrich a single plugin using autonomous research agents."""
    try:
        # Validate plugin exists
        conn = get_db()
        try:
            plugin = conn.execute(
                "SELECT id, name FROM plugins WHERE id = ?", (plugin_id,)
            ).fetchone()
            if not plugin:
                raise HTTPException(status_code=404, detail="Plugin not found")
        finally:
            conn.close()

        from src.agents.orchestrator import EnrichmentOrchestrator
        orchestrator = EnrichmentOrchestrator()
        result = await asyncio.to_thread(
            orchestrator.enrich_single,
            plugin_id,
            url=request.url,
            pdf_path=request.pdf_path,
        )

        # Re-embed affected plugins
        conn = get_db()
        try:
            affected = [
                dict(r) for r in conn.execute(
                    "SELECT * FROM plugins WHERE LOWER(name) = ?",
                    (plugin["name"].lower(),),
                ).fetchall()
            ]
        finally:
            conn.close()

        store = get_embeddings()
        store.upsert_plugins(affected)

        # Return enrichment result + updated plugin data
        conn = get_db()
        try:
            updated = dict(conn.execute(
                "SELECT * FROM plugins WHERE id = ?", (plugin_id,)
            ).fetchone())
        finally:
            conn.close()

        return {"enrichment": result, "plugin": updated}

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ── Settings API ──────────────────────────────────

@app.get("/api/settings")
async def get_settings():
    """Get all LLM settings."""
    from src.models import get_all_settings
    settings = get_all_settings()
    # Mask API key for display
    if settings.get("llm_api_key"):
        key = settings["llm_api_key"]
        settings["llm_api_key_masked"] = f"{key[:8]}...{key[-4:]}" if len(key) > 12 else "****"
    return settings


@app.put("/api/settings")
async def update_settings(settings: dict):
    """Update LLM settings."""
    from src.models import set_setting
    from src.llm_client import reload_clients

    allowed_keys = {
        "llm_provider", "llm_base_url", "llm_model", "llm_api_key",
        "llm_temperature",
        "agent_provider", "agent_base_url", "agent_model", "agent_api_key",
    }
    for key, value in settings.items():
        if key in allowed_keys:
            set_setting(key, str(value))

    # Reload LLM clients with new settings
    reload_clients()

    return {"status": "updated"}


@app.post("/api/settings/test")
async def test_llm_connection(settings: dict = None):
    """Test LLM connection with current or provided settings."""
    from src.llm_client import LLMClient
    if settings and settings.get("provider"):
        client = LLMClient(
            provider=settings.get("provider", "ollama"),
            base_url=settings.get("base_url"),
            model=settings.get("model"),
            api_key=settings.get("api_key"),
        )
    else:
        from src.llm_client import get_chat_client
        client = get_chat_client()

    result = await asyncio.to_thread(client.test_connection)
    return result


@app.get("/api/settings/system-info")
async def system_info():
    """Get system info for LLM recommendations."""
    from config import _system_ram
    import platform

    ram_gb = _system_ram
    chip = platform.processor() or platform.machine()

    if ram_gb >= 64:
        recommendation = "Gemma 4 26B or Qwen 3.5 27B locally (plenty of RAM)"
    elif ram_gb >= 32:
        recommendation = "Gemma 4 26B locally (good fit for 32GB)"
    elif ram_gb >= 16:
        recommendation = "Qwen 3.5 14B Q4 locally (~9GB) or Euria online (free, Swiss, GDPR)"
    else:
        recommendation = "Euria (free, Swiss-hosted, GDPR) or OpenRouter (free, global)"

    return {
        "ram_gb": ram_gb,
        "chip": chip,
        "platform": platform.system(),
        "recommendation": recommendation,
    }


# ── Startup ────────────────────────────────────────

@app.on_event("startup")
async def startup():
    """Initialize database on startup."""
    init_db()
    print(f"\n  {UI_TITLE} starting on http://{WEB_HOST}:{WEB_PORT}")


# ── Run ────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.app:app",
        host=WEB_HOST,
        port=WEB_PORT,
        reload=WEB_RELOAD,
        log_level=WEB_LOG_LEVEL,
    )
