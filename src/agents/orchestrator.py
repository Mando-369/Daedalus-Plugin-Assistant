"""
Enrichment Orchestrator - Coordinates goal-oriented agents to enrich plugin metadata.

Runs Product Info and Sonic Profile agents, merges results, and applies
to the database. Supports single-plugin and batch enrichment.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.agents.product_agent import ProductInfoAgent
from src.agents.sonic_agent import SonicProfileAgent
from src.agents.tools import fetch_page, read_pdf
from src.models import get_db
from src.embeddings import PluginEmbeddingStore

# Fields that agents can fill (maps agent output key → DB column)
_ALL_FIELDS = {
    "developer", "plugin_type", "category", "subcategory", "subtype",
    "emulation_of", "description", "specialty", "best_used_for",
    "character", "signal_chain_position", "tags",
    "hidden_tips", "not_ideal_for",
}


class EnrichmentOrchestrator:
    """Coordinates agents to enrich plugin metadata."""

    def __init__(self, model: str = None):
        self.model = model

    def enrich_single(
        self,
        plugin_id: int,
        url: str = None,
        pdf_path: str = None,
        on_step=None,
    ) -> dict:
        """Enrich a single plugin using goal-oriented agents.

        Args:
            plugin_id: Database ID of the plugin to enrich.
            url: Optional user-provided URL for additional context.
            pdf_path: Optional path to a PDF manual.
            on_step: Optional callback(phase, step_type, detail).

        Returns:
            Merged enrichment result dict.
        """
        # Fetch plugin from DB
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT * FROM plugins WHERE id = ?", (plugin_id,)
            ).fetchone()
            if not row:
                return {"error": f"Plugin {plugin_id} not found"}
            plugin = dict(row)
        finally:
            conn.close()

        # Build context from what we already know
        context_parts = [f"Plugin: {plugin['name']}"]
        if plugin.get("developer"):
            context_parts.append(f"Developer: {plugin['developer']}")
        if plugin.get("plugin_type"):
            context_parts.append(f"Type: {plugin['plugin_type']}")
        if plugin.get("category"):
            context_parts.append(f"Category: {plugin['category']}")

        # Add user-provided sources
        if url:
            if on_step:
                on_step("user_source", "fetching", {"url": url})
            page_text = fetch_page(url)
            context_parts.append(f"\nUser-provided URL content:\n{page_text}")

        if pdf_path:
            if on_step:
                on_step("user_source", "reading", {"path": pdf_path})
            pdf_text = read_pdf(pdf_path)
            context_parts.append(f"\nUser-provided PDF manual:\n{pdf_text}")

        context = "\n".join(context_parts)

        # Run Product Info Agent
        if on_step:
            on_step("product_agent", "starting", {"plugin": plugin["name"]})
        product_agent = ProductInfoAgent(model=self.model, has_pdf=bool(pdf_path))

        def product_step(step_type, detail):
            if on_step:
                on_step("product_agent", step_type, detail)

        product_result = product_agent.run(context, on_step=product_step)

        # Run Sonic Profile Agent
        if on_step:
            on_step("sonic_agent", "starting", {"plugin": plugin["name"]})
        sonic_agent = SonicProfileAgent(model=self.model)

        def sonic_step(step_type, detail):
            if on_step:
                on_step("sonic_agent", step_type, detail)

        sonic_result = sonic_agent.run(context, on_step=sonic_step)

        # Merge results (product agent wins for factual fields)
        merged = {}
        for field in _ALL_FIELDS:
            # Product agent is authoritative for factual fields
            product_val = product_result.get(field)
            sonic_val = sonic_result.get(field)

            if field in ("character", "specialty", "best_used_for",
                        "signal_chain_position", "tags",
                        "hidden_tips", "not_ideal_for"):
                # Sonic agent is authoritative for subjective fields
                merged[field] = sonic_val or product_val
            else:
                # Product agent is authoritative for factual fields
                merged[field] = product_val or sonic_val

        # Apply to DB (non-destructive)
        applied = self._apply_to_db(plugin["name"], merged)

        if on_step:
            on_step("done", "complete", {"applied": applied, "result": merged})

        return merged

    def enrich_batch(self, plugin_ids: list[int] = None, limit: int = None):
        """Generator yielding progress for bulk enrichment.

        Yields dicts with: type, plugin_name, result, progress, total.
        """
        conn = get_db()
        try:
            if plugin_ids:
                placeholders = ",".join("?" * len(plugin_ids))
                rows = conn.execute(
                    f"SELECT * FROM plugins WHERE id IN ({placeholders})",
                    plugin_ids,
                ).fetchall()
            else:
                rows = conn.execute("""
                    SELECT * FROM plugins
                    WHERE classification_confidence IN ('unclassified', 'low')
                       OR developer IS NULL OR developer = ''
                       OR description IS NULL OR description = ''
                    ORDER BY
                        CASE classification_confidence
                            WHEN 'unclassified' THEN 0
                            WHEN 'low' THEN 1
                            ELSE 2
                        END,
                        name
                """).fetchall()
            plugins = [dict(r) for r in rows]
        finally:
            conn.close()

        # Deduplicate by name (AU+VST3+AAX = same plugin)
        seen_names = set()
        unique_plugins = []
        for p in plugins:
            name_lower = p["name"].lower()
            if name_lower not in seen_names:
                seen_names.add(name_lower)
                unique_plugins.append(p)

        if limit:
            unique_plugins = unique_plugins[:limit]

        total = len(unique_plugins)
        enriched = 0
        errors = 0

        for i, plugin in enumerate(unique_plugins):
            yield {
                "type": "progress",
                "plugin_name": plugin["name"],
                "progress": i + 1,
                "total": total,
                "enriched": enriched,
                "errors": errors,
            }

            try:
                result = self.enrich_single(plugin["id"])
                if result and not result.get("error"):
                    enriched += 1
                    yield {
                        "type": "enriched",
                        "plugin_name": plugin["name"],
                        "result": result,
                    }
                else:
                    errors += 1
                    yield {
                        "type": "error",
                        "plugin_name": plugin["name"],
                        "error": result.get("error", "Unknown error"),
                    }
            except Exception as e:
                errors += 1
                yield {
                    "type": "error",
                    "plugin_name": plugin["name"],
                    "error": str(e),
                }

        # Re-embed all plugins after batch enrichment
        try:
            conn = get_db()
            all_plugins = [dict(r) for r in conn.execute("SELECT * FROM plugins").fetchall()]
            conn.close()
            store = PluginEmbeddingStore()
            store.delete_all()
            store.upsert_plugins(all_plugins)
        except Exception as e:
            yield {"type": "warning", "message": f"Re-embedding failed: {e}"}

        yield {
            "type": "done",
            "total": total,
            "enriched": enriched,
            "errors": errors,
        }

    def _apply_to_db(self, plugin_name: str, data: dict) -> int:
        """Apply enrichment to all DB rows with this plugin name.

        Non-destructive: only fills empty fields.
        Returns number of rows updated.
        """
        conn = get_db()
        try:
            # Find all rows with this name (AU + VST3 + AAX)
            rows = conn.execute(
                "SELECT id, * FROM plugins WHERE LOWER(name) = ?",
                (plugin_name.lower(),),
            ).fetchall()

            applied = 0
            for row in rows:
                existing = dict(row)
                updates = {}

                for field in _ALL_FIELDS:
                    new_val = data.get(field)
                    if new_val and str(new_val).strip():
                        old_val = existing.get(field)
                        if not old_val or old_val == "":
                            updates[field] = str(new_val).strip()

                if updates:
                    # Determine confidence based on how many fields got filled
                    all_key_fields = {"developer", "category", "description", "character"}
                    filled_keys = sum(1 for f in all_key_fields
                                      if updates.get(f) or existing.get(f))
                    if filled_keys >= 3:
                        updates["classification_confidence"] = "high"
                        updates["needs_review"] = 0
                    elif existing.get("classification_confidence") in ("unclassified", "low"):
                        updates["classification_confidence"] = "medium"
                        updates["needs_review"] = 0

                    set_parts = [f"{k} = ?" for k in updates]
                    set_parts.append("updated_at = datetime('now')")
                    values = list(updates.values()) + [existing["id"]]

                    conn.execute(
                        f"UPDATE plugins SET {', '.join(set_parts)} WHERE id = ?",
                        values,
                    )
                    applied += 1

            conn.commit()
            return applied
        finally:
            conn.close()
