"""
Plugin Enrichment Service - Web search + LLM analysis for auto-filling
plugin metadata. For each plugin, searches the web for information,
feeds results to the LLM, and lets the LLM decide what to store.
"""

import json
import re
import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx

from config import (
    OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT,
    OLLAMA_CONTEXT_LENGTH, OLLAMA_KEEP_ALIVE,
)
from src.models import get_db

logger = logging.getLogger(__name__)

# Process one plugin at a time for best accuracy with web context
ENRICHMENT_BATCH_SIZE = 5

# Web search configuration
SEARCH_SITES = [
    "kvraudio.com",
    "pluginboutique.com",
    "plugin-alliance.com",
    "uaudio.com",
    "waves.com",
]

ENRICHMENT_SYSTEM_PROMPT = """You are an expert audio plugin identifier. You will receive a plugin name and web search results about it.

Analyze the web results and your own knowledge to fill in structured metadata for the plugin. Use the web results as your primary source — they contain the most accurate and up-to-date information.

Return a JSON object with these fields:
- name: The plugin name (as given)
- developer: The company/person who made it
- plugin_type: "effect" or "instrument"
- category: Main category (Compressor, EQ, Reverb, Delay, Saturation, Synthesizer, Sampler, Channel Strip, Limiter, De-esser, Gate, Chorus, Flanger, Phaser, Distortion, Filter, Analyzer, Utility, Mastering Suite, etc.)
- subcategory: More specific type (e.g. "FET Compressor", "Parametric EQ", "Plate Reverb", "Multiband Compressor", "Wavetable Synth")
- subtype: One of: original, emulation, clone, utility, special
- emulation_of: If it emulates specific hardware, name it (e.g. "Teletronix LA-2A") — empty string if original design
- description: One-sentence description based on what you found
- specialty: What it's best known for
- best_used_for: Typical use cases (mixing, mastering, sound design, etc.)
- character: Sonic character (e.g. "warm", "transparent", "aggressive", "vintage", "clean")
- signal_chain_position: One of: first, early, insert, late, last
- tags: Comma-separated relevant tags
- confidence: "high" if web results clearly identify the plugin, "medium" if partially identified, "unknown" if you can't determine what it is

Use your judgment on what information is reliable from the search results. If conflicting information exists, prefer official developer sites over third-party reviews.

IMPORTANT: Respond ONLY with a valid JSON object. No explanation, no markdown fences."""

ENRICHMENT_USER_TEMPLATE = """Plugin name: {plugin_name}

Web search results:
{search_results}

Based on the above, identify this audio plugin and return a JSON object with the metadata fields."""

ENRICHMENT_BATCH_TEMPLATE = """I have {count} plugins to identify. For each one I'm providing the plugin name and web search results.

{plugin_entries}

Return a JSON array with one object per plugin containing these fields: name, developer, plugin_type, category, subcategory, subtype, emulation_of, description, specialty, best_used_for, character, signal_chain_position, tags, confidence"""


def _web_search(query: str, num_results: int = 5) -> list[dict]:
    """
    Search the web for plugin information.
    Uses DuckDuckGo HTML search (no API key needed).
    Returns list of {title, url, snippet}.
    """
    results = []
    search_query = f"{query} audio plugin"

    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            resp = client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": search_query},
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                },
            )
            if resp.status_code == 200:
                html = resp.text
                # Parse result blocks from DuckDuckGo HTML
                # Each result is in a <div class="result__body">
                result_blocks = re.findall(
                    r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?'
                    r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
                    html, re.DOTALL
                )
                for url, title, snippet in result_blocks[:num_results]:
                    # Clean HTML tags
                    title = re.sub(r'<[^>]+>', '', title).strip()
                    snippet = re.sub(r'<[^>]+>', '', snippet).strip()
                    # DuckDuckGo wraps URLs in a redirect
                    if "uddg=" in url:
                        url_match = re.search(r'uddg=([^&]+)', url)
                        if url_match:
                            from urllib.parse import unquote
                            url = unquote(url_match.group(1))
                    results.append({"title": title, "url": url, "snippet": snippet})
    except Exception as e:
        logger.warning(f"Web search failed for '{query}': {e}")

    return results


class PluginEnrichmentService:
    """Enriches plugin metadata using web search + LLM analysis."""

    def __init__(self):
        self.stats = {
            "total_processed": 0,
            "enriched": 0,
            "unknown": 0,
            "errors": 0,
        }

    def get_plugins_needing_enrichment(self, limit: int = None) -> list[dict]:
        """Fetch plugins that need enrichment from the database."""
        conn = get_db()
        try:
            sql = """
                SELECT id, name, display_name, file_name, format, install_scope,
                       developer, category, classification_confidence
                FROM plugins
                WHERE classification_confidence IN ('unclassified', 'low')
                   OR developer IS NULL OR developer = ''
                   OR description IS NULL OR description = ''
                ORDER BY
                    CASE classification_confidence
                        WHEN 'unclassified' THEN 0
                        WHEN 'low' THEN 1
                        ELSE 2
                    END,
                    name ASC
            """
            if limit:
                sql += f" LIMIT {int(limit)}"
            rows = conn.execute(sql).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def _search_plugin(self, name: str) -> str:
        """Search the web for a plugin and return formatted results."""
        results = _web_search(name)
        if not results:
            return "No web results found."

        formatted = []
        for r in results:
            formatted.append(f"Title: {r['title']}\nURL: {r['url']}\nSnippet: {r['snippet']}")
        return "\n\n".join(formatted)

    def _call_llm(self, messages: list[dict]) -> dict | list | None:
        """
        Call Ollama with streaming to handle thinking models properly.
        Streams response, separates thinking from content, extracts JSON.
        """
        thinking_buffer = []
        content_buffer = []

        with httpx.Client(timeout=httpx.Timeout(connect=10, read=600, write=10, pool=10)) as client:
            with client.stream(
                "POST",
                f"{OLLAMA_BASE_URL}/api/chat",
                json={
                    "model": OLLAMA_MODEL,
                    "messages": messages,
                    "stream": True,
                    "options": {
                        "temperature": 0.1,
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
                            thinking_buffer.append(thinking)
                        if content:
                            content_buffer.append(content)
                        if chunk.get("done"):
                            break

        full_content = "".join(content_buffer)
        full_thinking = "".join(thinking_buffer)

        if full_content:
            return self._parse_response(full_content)

        # Fallback: if content is empty, try to extract JSON from thinking
        if full_thinking:
            logger.warning(f"LLM produced only thinking ({len(full_thinking)} chars) — extracting from reasoning")
            return self._parse_response(full_thinking)

        logger.error("LLM returned empty response (no content, no thinking)")
        return None

    def _call_llm_single(self, plugin_name: str, search_results: str) -> dict | None:
        """Send a single plugin + web results to the LLM for identification."""
        prompt = ENRICHMENT_USER_TEMPLATE.format(
            plugin_name=plugin_name,
            search_results=search_results,
        )
        messages = [
            {"role": "system", "content": ENRICHMENT_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        result = self._call_llm(messages)
        if isinstance(result, list) and result:
            return result[0]
        return result if isinstance(result, dict) else None

    def _call_llm_batch(self, plugins_with_results: list[tuple[str, str]]) -> list[dict]:
        """Send a batch of plugins + web results to the LLM."""
        entries = []
        for i, (name, search_results) in enumerate(plugins_with_results, 1):
            entries.append(f"--- Plugin {i}: {name} ---\n{search_results}")

        prompt = ENRICHMENT_BATCH_TEMPLATE.format(
            count=len(plugins_with_results),
            plugin_entries="\n\n".join(entries),
        )
        messages = [
            {"role": "system", "content": ENRICHMENT_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        result = self._call_llm(messages)
        if isinstance(result, list):
            return result
        elif isinstance(result, dict):
            return [result]
        return []

    def _parse_response(self, content: str):
        """Extract JSON from LLM response, stripping thinking and markdown."""
        # Strip thinking tags
        if "<think>" in content:
            content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)
        content = content.strip()

        # Remove markdown fences
        if content.startswith("```"):
            lines = content.split("\n")
            end_idx = len(lines)
            for i in range(len(lines) - 1, 0, -1):
                if lines[i].strip() == "```":
                    end_idx = i
                    break
            content = "\n".join(lines[1:end_idx]).strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # Try to find JSON anywhere in the response
            json_match = re.search(r'(\[[\s\S]*\]|\{[\s\S]*\})', content)
            if json_match:
                try:
                    return json.loads(json_match.group(1))
                except json.JSONDecodeError:
                    pass
            logger.error("Failed to parse LLM JSON response")
            logger.debug(f"Raw: {content[:500]}")
            return None

    def _apply_enrichment(self, plugin_id: int, data: dict) -> bool:
        """Apply enrichment data to a plugin in the database. Only fills empty fields."""
        conn = get_db()
        try:
            existing = conn.execute(
                "SELECT * FROM plugins WHERE id = ?", (plugin_id,)
            ).fetchone()
            if not existing:
                return False

            existing = dict(existing)
            updates = {}
            confidence = data.get("confidence", "unknown")

            if confidence == "unknown":
                return False

            field_map = {
                "developer": "developer",
                "plugin_type": "plugin_type",
                "category": "category",
                "subcategory": "subcategory",
                "subtype": "subtype",
                "emulation_of": "emulation_of",
                "description": "description",
                "specialty": "specialty",
                "best_used_for": "best_used_for",
                "character": "character",
                "signal_chain_position": "signal_chain_position",
                "tags": "tags",
            }

            for src_field, db_field in field_map.items():
                new_val = data.get(src_field)
                if new_val and str(new_val).strip() and str(new_val).strip() != "":
                    old_val = existing.get(db_field)
                    if not old_val or old_val == "":
                        updates[db_field] = str(new_val).strip()

            if updates:
                if existing.get("classification_confidence") in ("unclassified", "low"):
                    updates["classification_confidence"] = confidence
                    updates["needs_review"] = 1

                set_parts = [f"{k} = ?" for k in updates]
                set_parts.append("updated_at = datetime('now')")
                values = list(updates.values()) + [plugin_id]

                conn.execute(
                    f"UPDATE plugins SET {', '.join(set_parts)} WHERE id = ?",
                    values,
                )
                conn.commit()
                return True

            return False
        finally:
            conn.close()

    def enrich_all(self, limit: int = None):
        """
        Generator that enriches all plugins needing it.
        Yields progress dicts: {"processed", "total", "current", "stats", "done"}
        """
        plugins = self.get_plugins_needing_enrichment(limit=limit)

        # Deduplicate by name
        seen = set()
        unique = []
        for p in plugins:
            key = p["name"].lower()
            if key not in seen:
                seen.add(key)
                unique.append(p)

        total_unique = len(unique)

        if total_unique == 0:
            yield {"processed": 0, "total": 0, "current": "", "stats": self.stats, "done": True}
            return

        yield {"processed": 0, "total": total_unique, "current": "", "stats": dict(self.stats), "done": False}

        for i in range(0, len(unique), ENRICHMENT_BATCH_SIZE):
            batch = unique[i : i + ENRICHMENT_BATCH_SIZE]

            # Step 1: Web search for each plugin in the batch
            plugins_with_results = []
            for p in batch:
                search_results = self._search_plugin(p["name"])
                plugins_with_results.append((p["name"], search_results))

            # Step 2: Send batch to LLM with web context
            try:
                if len(batch) == 1:
                    name, search_results = plugins_with_results[0]
                    result = self._call_llm_single(name, search_results)
                    results = [result] if result else []
                else:
                    results = self._call_llm_batch(plugins_with_results)

                # Match results to plugins by name
                result_map = {}
                for r in results:
                    if isinstance(r, dict):
                        r_name = r.get("name", "").lower()
                        result_map[r_name] = r

                for p in batch:
                    p_lower = p["name"].lower()
                    enrichment = result_map.get(p_lower)

                    if enrichment:
                        # Apply to ALL DB rows with this name (AU + VST3)
                        conn = get_db()
                        try:
                            all_rows = conn.execute(
                                "SELECT id FROM plugins WHERE LOWER(name) = ?",
                                (p_lower,),
                            ).fetchall()
                        finally:
                            conn.close()

                        applied = False
                        for row in all_rows:
                            if self._apply_enrichment(row["id"], enrichment):
                                applied = True

                        if applied:
                            self.stats["enriched"] += 1
                        else:
                            self.stats["unknown"] += 1
                    else:
                        self.stats["unknown"] += 1

                    self.stats["total_processed"] += 1

            except Exception as e:
                logger.error(f"Enrichment batch error: {e}")
                self.stats["errors"] += 1
                self.stats["total_processed"] += len(batch)

            processed = min(i + ENRICHMENT_BATCH_SIZE, total_unique)
            current = batch[-1]["name"] if batch else ""
            yield {
                "processed": processed,
                "total": total_unique,
                "current": current,
                "stats": dict(self.stats),
                "done": False,
            }

        yield {
            "processed": total_unique,
            "total": total_unique,
            "current": "",
            "stats": dict(self.stats),
            "done": True,
        }
