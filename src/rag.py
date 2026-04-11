"""
RAG Pipeline - Dual search (SQL + ChromaDB) with Ollama LLM generation.
Combines structured database queries with semantic vector search for
comprehensive plugin retrieval and natural language answers.
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import json

import httpx

from config import (
    OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT,
    OLLAMA_TEMPERATURE, OLLAMA_TOP_P, OLLAMA_NUM_PREDICT,
    OLLAMA_KEEP_ALIVE, OLLAMA_CONTEXT_LENGTH,
    LLM_SYSTEM_PROMPT, RAG_MAX_CONTEXT_PLUGINS,
    RAG_CONTEXT_TEMPLATE, SEMANTIC_SEARCH_TOP_K, SQL_SEARCH_LIMIT,
)
from src.models import get_db
from src.embeddings import PluginEmbeddingStore


class RAGPipeline:
    """Orchestrates retrieval and generation for plugin queries."""

    def __init__(self):
        self.embedding_store = PluginEmbeddingStore()

    # ── Structured SQL Search ──────────────────────────

    def sql_search(self, query: str, filters: dict = None) -> list[dict]:
        """
        Search plugins using FTS5 full-text search and optional filters.
        Returns list of plugin dicts.
        """
        conn = get_db()
        try:
            # Build FTS query - escape special chars
            fts_query = query.replace('"', '""')
            terms = fts_query.split()
            # Use prefix matching for each term
            fts_terms = " OR ".join(f'"{t}"*' for t in terms if t.strip())

            if not fts_terms:
                return []

            sql = """
                SELECT p.*, plugins_fts.rank
                FROM plugins p
                JOIN plugins_fts ON p.id = plugins_fts.rowid
                WHERE plugins_fts MATCH ?
            """
            params = [fts_terms]

            # Apply optional filters
            if filters:
                if filters.get("category"):
                    sql += " AND p.category = ?"
                    params.append(filters["category"])
                if filters.get("plugin_type"):
                    sql += " AND p.plugin_type = ?"
                    params.append(filters["plugin_type"])
                if filters.get("developer"):
                    sql += " AND p.developer = ?"
                    params.append(filters["developer"])
                if filters.get("is_own_plugin") is not None:
                    sql += " AND p.is_own_plugin = ?"
                    params.append(1 if filters["is_own_plugin"] else 0)

            sql += " ORDER BY plugins_fts.rank LIMIT ?"
            params.append(SQL_SEARCH_LIMIT)

            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            print(f"  [SQL Search Error] {e}")
            return []
        finally:
            conn.close()

    def filter_search(self, filters: dict) -> list[dict]:
        """Direct filter search without FTS (for browse/filter UI)."""
        conn = get_db()
        try:
            sql = "SELECT * FROM plugins WHERE 1=1"
            params = []

            if filters.get("category"):
                sql += " AND category = ?"
                params.append(filters["category"])
            if filters.get("plugin_type"):
                sql += " AND plugin_type = ?"
                params.append(filters["plugin_type"])
            if filters.get("developer"):
                sql += " AND developer = ?"
                params.append(filters["developer"])
            if filters.get("is_own_plugin") is not None:
                sql += " AND is_own_plugin = ?"
                params.append(1 if filters["is_own_plugin"] else 0)
            if filters.get("needs_review") is not None:
                sql += " AND needs_review = ?"
                params.append(1 if filters["needs_review"] else 0)
            if filters.get("format"):
                sql += " AND format = ?"
                params.append(filters["format"])
            if filters.get("character"):
                sql += " AND character LIKE ?"
                params.append(f"%{filters['character']}%")

            sql += " ORDER BY name LIMIT ?"
            params.append(filters.get("limit", SQL_SEARCH_LIMIT))

            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            print(f"  [Filter Search Error] {e}")
            return []
        finally:
            conn.close()

    # ── Semantic Vector Search ─────────────────────────

    def semantic_search(self, query: str, n_results: int = None) -> list[dict]:
        """
        Search using ChromaDB semantic similarity.
        Returns list of dicts with metadata and similarity scores.
        """
        n = n_results or SEMANTIC_SEARCH_TOP_K
        results = self.embedding_store.search(query, n_results=n)

        # Enrich with full DB data where possible
        enriched = []
        conn = get_db()
        try:
            for r in results:
                meta = r.get("metadata", {})
                plugin_id = meta.get("plugin_id")
                if plugin_id:
                    row = conn.execute(
                        "SELECT * FROM plugins WHERE id = ?", (plugin_id,)
                    ).fetchone()
                    if row:
                        plugin = dict(row)
                        plugin["_search_distance"] = r["distance"]
                        enriched.append(plugin)
                        continue

                # Fallback: use metadata directly
                enriched.append({
                    **meta,
                    "_search_distance": r["distance"],
                    "_document": r["document"],
                })
        finally:
            conn.close()

        return enriched

    # ── Dual Search (Hybrid) ───────────────────────────

    def hybrid_search(self, query: str) -> list[dict]:
        """
        Combine SQL FTS and semantic search results, deduplicate,
        and return the top candidates for LLM context.
        """
        # Run both searches
        sql_results = self.sql_search(query)
        semantic_results = self.semantic_search(query)

        # Merge and deduplicate by plugin name
        seen = {}
        merged = []

        for p in sql_results:
            key = p.get("name", "").lower()
            if key not in seen:
                seen[key] = True
                p["_source"] = "sql"
                merged.append(p)

        for p in semantic_results:
            key = (p.get("name") or p.get("metadata", {}).get("name", "")).lower()
            if key and key not in seen:
                seen[key] = True
                p["_source"] = "semantic"
                merged.append(p)

        # Limit to max context size
        return merged[:RAG_MAX_CONTEXT_PLUGINS]

    # ── Context Building ───────────────────────────────

    def build_context(self, plugins: list[dict]) -> str:
        """Format plugin data into a text context for the LLM."""
        if not plugins:
            return "No relevant plugins found in the database."

        entries = []
        for i, p in enumerate(plugins, 1):
            lines = [f"{i}. {p.get('display_name') or p.get('name', 'Unknown')}"]
            if p.get("developer"):
                lines.append(f"   Developer: {p['developer']}")
            if p.get("category"):
                cat = p["category"]
                if p.get("subcategory"):
                    cat += f" / {p['subcategory']}"
                lines.append(f"   Category: {cat}")
            if p.get("plugin_type"):
                lines.append(f"   Type: {p['plugin_type']}")
            if p.get("subtype"):
                lines.append(f"   Subtype: {p['subtype']}")
            if p.get("emulation_of"):
                lines.append(f"   Emulates: {p['emulation_of']}")
            if p.get("description"):
                lines.append(f"   Description: {p['description']}")
            if p.get("specialty"):
                lines.append(f"   Specialty: {p['specialty']}")
            if p.get("best_used_for"):
                lines.append(f"   Best for: {p['best_used_for']}")
            if p.get("character"):
                lines.append(f"   Character: {p['character']}")
            if p.get("signal_chain_position"):
                lines.append(f"   Chain position: {p['signal_chain_position']}")
            if p.get("tags"):
                lines.append(f"   Tags: {p['tags']}")
            if p.get("notes"):
                lines.append(f"   Notes: {p['notes']}")
            if p.get("is_own_plugin"):
                lines.append(f"   ★ Own plugin ({p.get('own_brand', '')})")
            if p.get("format"):
                lines.append(f"   Format: {p['format']} ({p.get('install_scope', '')})")

            entries.append("\n".join(lines))

        plugin_context = "\n\n".join(entries)
        return RAG_CONTEXT_TEMPLATE.format(plugin_context=plugin_context)

    # ── LLM Generation ─────────────────────────────────

    def generate(self, user_query: str, context: str, chat_history: list = None) -> str:
        """
        Send the query + context to Ollama and return the response.
        Supports streaming internally but returns the full response.
        """
        messages = [{"role": "system", "content": LLM_SYSTEM_PROMPT}]

        # Add chat history for multi-turn conversations
        if chat_history:
            for msg in chat_history[-6:]:  # keep last 6 messages for context
                messages.append(msg)

        # Build the user message with context
        full_prompt = f"{context}\n\nUser question: {user_query}"
        messages.append({"role": "user", "content": full_prompt})

        with httpx.Client(timeout=httpx.Timeout(connect=10, read=300, write=10, pool=10)) as client:
            with client.stream(
                "POST",
                f"{OLLAMA_BASE_URL}/api/chat",
                json={
                    "model": OLLAMA_MODEL,
                    "messages": messages,
                    "stream": True,
                    "options": {
                        "temperature": OLLAMA_TEMPERATURE,
                        "top_p": OLLAMA_TOP_P,
                        "num_predict": OLLAMA_NUM_PREDICT,
                        "num_ctx": OLLAMA_CONTEXT_LENGTH,
                    },
                    "keep_alive": OLLAMA_KEEP_ALIVE,
                },
            ) as response:
                response.raise_for_status()
                content_parts = []
                for line in response.iter_lines():
                    if line:
                        chunk = json.loads(line)
                        content = chunk.get("message", {}).get("content", "")
                        if content:
                            content_parts.append(content)
                        if chunk.get("done"):
                            break
                return "".join(content_parts) or "No response generated."

    def generate_stream(self, user_query: str, context: str, chat_history: list = None):
        """
        Stream the LLM response token by token.
        Yields content chunks as they arrive.
        """
        messages = [{"role": "system", "content": LLM_SYSTEM_PROMPT}]

        if chat_history:
            for msg in chat_history[-6:]:
                messages.append(msg)

        full_prompt = f"{context}\n\nUser question: {user_query}"
        messages.append({"role": "user", "content": full_prompt})

        with httpx.Client(timeout=httpx.Timeout(connect=10, read=300, write=10, pool=10)) as client:
            with client.stream(
                "POST",
                f"{OLLAMA_BASE_URL}/api/chat",
                json={
                    "model": OLLAMA_MODEL,
                    "messages": messages,
                    "stream": True,
                    "options": {
                        "temperature": OLLAMA_TEMPERATURE,
                        "top_p": OLLAMA_TOP_P,
                        "num_predict": OLLAMA_NUM_PREDICT,
                        "num_ctx": OLLAMA_CONTEXT_LENGTH,
                    },
                    "keep_alive": OLLAMA_KEEP_ALIVE,
                },
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if line:
                        chunk = json.loads(line)
                        msg = chunk.get("message", {})
                        thinking = msg.get("thinking", "")
                        content = msg.get("content", "")
                        if thinking:
                            yield ("thinking", thinking)
                        if content:
                            yield ("content", content)
                        if chunk.get("done"):
                            break

    async def async_generate_stream(self, user_query: str, context: str, chat_history: list = None):
        """Async streaming LLM response for use in async WebSocket handlers."""
        messages = [{"role": "system", "content": LLM_SYSTEM_PROMPT}]

        if chat_history:
            for msg in chat_history[-6:]:
                messages.append(msg)

        full_prompt = f"{context}\n\nUser question: {user_query}"
        messages.append({"role": "user", "content": full_prompt})

        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=300, write=10, pool=10)) as client:
            async with client.stream(
                "POST",
                f"{OLLAMA_BASE_URL}/api/chat",
                json={
                    "model": OLLAMA_MODEL,
                    "messages": messages,
                    "stream": True,
                    "options": {
                        "temperature": OLLAMA_TEMPERATURE,
                        "top_p": OLLAMA_TOP_P,
                        "num_predict": OLLAMA_NUM_PREDICT,
                        "num_ctx": OLLAMA_CONTEXT_LENGTH,
                    },
                    "keep_alive": OLLAMA_KEEP_ALIVE,
                },
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line:
                        chunk = json.loads(line)
                        msg = chunk.get("message", {})
                        thinking = msg.get("thinking", "")
                        content = msg.get("content", "")
                        if thinking:
                            yield ("thinking", thinking)
                        if content:
                            yield ("content", content)
                        if chunk.get("done"):
                            break

    # ── Main Query Entry Point ─────────────────────────

    def query(self, user_query: str, chat_history: list = None) -> dict:
        """
        Full RAG pipeline: search → build context → generate answer.
        Returns dict with: answer, sources (plugin names), source_count.
        """
        # 1. Hybrid search
        plugins = self.hybrid_search(user_query)

        # 2. Build context
        context = self.build_context(plugins)

        # 3. Generate answer
        answer = self.generate(user_query, context, chat_history)

        # 4. Return structured result
        sources = [
            {
                "name": p.get("display_name") or p.get("name", "Unknown"),
                "category": p.get("category", ""),
                "developer": p.get("developer", ""),
            }
            for p in plugins
        ]

        return {
            "answer": answer,
            "sources": sources,
            "source_count": len(sources),
        }


if __name__ == "__main__":
    rag = RAGPipeline()
    print("RAG Pipeline ready.")
    print(f"ChromaDB documents: {rag.embedding_store.count()}")

    # Test query (requires Ollama running)
    try:
        result = rag.query("What compressor plugins do I have?")
        print(f"\nAnswer: {result['answer']}")
        print(f"Sources: {result['source_count']} plugins referenced")
    except Exception as e:
        print(f"\nTest query failed (is Ollama running?): {e}")
