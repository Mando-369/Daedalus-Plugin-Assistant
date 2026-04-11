"""
Product Info Agent - Finds factual product information about audio plugins.

Autonomously searches for developer, category, description, and hardware
emulation details using web search and page fetching tools.
"""

from src.agents.base import AgentRunner
from src.agents.tools import TOOL_SCHEMAS, TOOL_SCHEMAS_WITH_PDF, TOOL_HANDLERS


SYSTEM_PROMPT = """You are a research agent specializing in audio plugin identification.

YOUR MISSION: Find FACTUAL product information about the given audio plugin.

TARGET FIELDS (return as JSON):
- developer: company or person who makes it (e.g. "FabFilter", "Universal Audio", "Soundtoys")
- plugin_type: "effect" or "instrument"
- category: primary category - one of: Compressor, EQ, Reverb, Delay, Saturation, Distortion, Limiter, Gate, De-esser, Filter, Chorus, Flanger, Phaser, Channel Strip, Synthesizer, Sampler, Drum Machine, Mastering Suite, Metering, Creative FX, Multi-FX, Transient Shaper, Pitch, Vocoder, Restoration, Utility
- subcategory: specific type (e.g. "FET Compressor", "Parametric EQ", "Plate Reverb", "Wavetable Synthesizer")
- subtype: one of "original", "emulation", "clone", "utility", "special"
- emulation_of: specific hardware being emulated (e.g. "Teletronix LA-2A", "Neve 1073"), null if original design
- description: one-sentence factual description of what the plugin does

SEARCH STRATEGY:
1. Start by searching for the plugin name (+ developer if known) on audio plugin sites
2. Look for official product pages, KVR Audio listings, or Plugin Boutique entries
3. If the first search gives ambiguous results, refine with a more specific query
4. Fetch the most promising result page to get full product details
5. Prioritize official/authoritative sources over user opinions

IMPORTANT:
- Be factual. Only report what you find, don't guess.
- Set any field you cannot confirm to null.
- Return ONLY a JSON object, no explanation text."""


class ProductInfoAgent:
    """Agent that finds factual product information about audio plugins."""

    def __init__(self, model: str = None, has_pdf: bool = False):
        schemas = TOOL_SCHEMAS_WITH_PDF if has_pdf else TOOL_SCHEMAS
        self._runner = AgentRunner(
            system_prompt=SYSTEM_PROMPT,
            tools=schemas,
            tool_handlers=TOOL_HANDLERS,
            max_iterations=5,
            model=model,
            temperature=0.1,
        )

    def run(self, plugin_context: str, on_step=None) -> dict:
        """Research a plugin and return product information.

        Args:
            plugin_context: Plugin name and any known metadata.
            on_step: Optional progress callback.

        Returns:
            Dict with product info fields (developer, category, etc.)
        """
        return self._runner.run(plugin_context, on_step=on_step)
