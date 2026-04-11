"""
Daedalus Plugin Assistant - FastAPI Web Application
REST API + WebSocket chat + CRUD for plugin management.
"""

import json
import sys
import traceback
from pathlib import Path
from datetime import datetime

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
        conn.commit()

        # Re-embed this plugin
        row = conn.execute("SELECT * FROM plugins WHERE id = ?", (plugin_id,)).fetchone()
        if row:
            get_embeddings().upsert_plugins([dict(row)])

        return {"status": "updated", "plugin_id": plugin_id}
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

            try:
                rag = get_rag()

                # Search phase
                await websocket.send_json({
                    "type": "status",
                    "content": "Searching plugin database..."
                })

                plugins = rag.hybrid_search(user_query)
                context = rag.build_context(plugins)

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

                # Generation phase - stream tokens
                await websocket.send_json({
                    "type": "status",
                    "content": "Generating response..."
                })

                for token_type, token_text in rag.generate_stream(user_query, context, history):
                    await websocket.send_json({
                        "type": token_type,  # "thinking" or "content"
                        "content": token_text,
                    })

                await websocket.send_json({"type": "done"})

            except Exception as e:
                traceback.print_exc()
                await websocket.send_json({
                    "type": "error",
                    "content": str(e),
                })

    except WebSocketDisconnect:
        pass


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
        try:
            for p in classified:
                existing = conn.execute(
                    "SELECT id FROM plugins WHERE file_name = ? AND format = ? AND install_scope = ?",
                    (p["file_name"], p["format"], p["install_scope"])
                ).fetchone()

                if existing:
                    # Update existing entry (don't overwrite manual edits for classified fields)
                    conn.execute("""
                        UPDATE plugins SET
                            name = ?, display_name = ?, file_path = ?,
                            is_own_plugin = ?, own_brand = ?,
                            updated_at = datetime('now')
                        WHERE id = ?
                    """, (
                        p["name"], p["display_name"], p["file_path"],
                        1 if p.get("is_own_plugin") else 0,
                        p.get("own_brand"),
                        existing["id"],
                    ))
                    updated += 1
                else:
                    conn.execute("""
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
        }

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ── Enrichment API ────────────────────────────────

@app.websocket("/ws/enrich")
async def websocket_enrich(websocket: WebSocket):
    """WebSocket endpoint for streaming enrichment progress."""
    await websocket.accept()

    try:
        data = await websocket.receive_text()
        msg = json.loads(data)
        limit = msg.get("limit")

        from src.enrichment import PluginEnrichmentService
        service = PluginEnrichmentService()

        for progress in service.enrich_all(limit=limit):
            await websocket.send_json(progress)

        # Re-embed all plugins after enrichment
        await websocket.send_json({
            "processed": progress["total"],
            "total": progress["total"],
            "current": "Re-embedding plugins...",
            "stats": progress["stats"],
            "done": False,
        })

        conn = get_db()
        try:
            all_plugins = [dict(r) for r in conn.execute("SELECT * FROM plugins").fetchall()]
        finally:
            conn.close()

        store = get_embeddings()
        store.delete_all()
        store.upsert_plugins(all_plugins)

        await websocket.send_json({
            "processed": progress["total"],
            "total": progress["total"],
            "current": "",
            "stats": progress["stats"],
            "done": True,
        })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        traceback.print_exc()
        try:
            await websocket.send_json({"error": str(e), "done": True})
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
