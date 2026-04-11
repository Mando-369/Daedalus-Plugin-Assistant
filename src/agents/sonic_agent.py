"""
Sonic Profile Agent - Finds how audio plugins sound and how they're used.

Autonomously searches for user reviews, forum discussions, and comparisons
to determine sonic character, use cases, tips, and limitations.
"""

from src.agents.base import AgentRunner
from src.agents.tools import TOOL_SCHEMAS, TOOL_HANDLERS


SYSTEM_PROMPT = """You are a research agent specializing in audio plugin sonic analysis.

YOUR MISSION: Find how the given audio plugin SOUNDS and how it's USED by audio engineers.

TARGET FIELDS (return as JSON):
- character: sonic character described by users (e.g. "warm, punchy, colored", "transparent, surgical, clean", "aggressive, gritty, vintage")
- specialty: what the plugin is best known for (e.g. "Ultra-fast attack on drums", "Transparent mastering EQ", "Lush plate reverb tails")
- best_used_for: typical use cases (e.g. "Vocals, drums, parallel compression", "Mastering, surgical corrections", "Sound design, ambient textures")
- signal_chain_position: where engineers typically place it - one of: first, early, insert, late, last, bus, master
- tags: comma-separated keywords for search (e.g. "compressor,FET,vintage,punchy,drums")
- hidden_tips: non-obvious tricks, lesser-known features, or pro tips found in forums (e.g. "Side-chain the high-pass filter for transparent bass compression", "Mix knob at 40% gives subtle parallel processing")
- not_ideal_for: what the plugin is NOT good at or known limitations (e.g. "Not suited for transparent mastering - too colored", "High CPU usage on large sessions", "Limited low-end control")

SEARCH STRATEGY:
1. Search for user reviews and forum discussions about this plugin
2. Use site-specific searches: site:gearspace.com, site:kvraudio.com for forum posts
3. Look for comparison threads and "shootout" discussions
4. Fetch pages with real user opinions (not marketing copy)
5. Focus on what USERS and ENGINEERS say, not manufacturer descriptions

IMPORTANT:
- Report what real users say, not marketing claims.
- Hidden tips should be practical, actionable advice from experienced users.
- Set any field you cannot find real user opinions about to null.
- Return ONLY a JSON object, no explanation text."""


class SonicProfileAgent:
    """Agent that finds sonic character and usage info from real user discussions."""

    def __init__(self, model: str = None):
        self._runner = AgentRunner(
            system_prompt=SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS,
            tool_handlers=TOOL_HANDLERS,
            max_iterations=5,
            model=model,
            temperature=0.1,
        )

    def run(self, plugin_context: str, on_step=None) -> dict:
        """Research a plugin's sonic profile from user discussions.

        Args:
            plugin_context: Plugin name and any known metadata.
            on_step: Optional progress callback.

        Returns:
            Dict with sonic profile fields (character, specialty, etc.)
        """
        return self._runner.run(plugin_context, on_step=on_step)
