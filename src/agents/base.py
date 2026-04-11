"""
Agent Runner - Executes an LLM agent with autonomous tool-calling loop.

The agent receives a goal (system prompt), available tools, and a user message.
It autonomously decides which tools to call, processes results, and returns
a structured JSON answer when it has enough information.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import httpx

from config import (
    OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_KEEP_ALIVE,
    OLLAMA_CONTEXT_LENGTH, OLLAMA_NUM_PREDICT,
)


class AgentRunner:
    """Runs an LLM agent with tool-calling loop via Ollama."""

    def __init__(
        self,
        system_prompt: str,
        tools: list[dict],
        tool_handlers: dict,
        max_iterations: int = 5,
        model: str = None,
        temperature: float = 0.1,
    ):
        self.system_prompt = system_prompt
        self.tools = tools                  # Ollama tool schemas
        self.tool_handlers = tool_handlers  # name -> callable
        self.max_iterations = max_iterations
        self.model = model or OLLAMA_MODEL
        self.temperature = temperature

    def run(self, user_message: str, on_step=None) -> dict:
        """Execute the agent loop. Returns parsed JSON result or empty dict.

        Args:
            user_message: The task/query for the agent.
            on_step: Optional callback(step_type, detail) for progress reporting.
                     step_type is 'tool_call', 'tool_result', 'thinking', or 'answer'.
        """
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_message},
        ]

        for iteration in range(self.max_iterations):
            response = self._call_llm(messages)
            msg = response.get("message", {})

            # Report thinking if present
            if on_step and msg.get("thinking"):
                on_step("thinking", msg["thinking"])

            # Check for tool calls
            tool_calls = msg.get("tool_calls", [])
            if tool_calls:
                # Append assistant message with tool calls
                messages.append(msg)

                for tc in tool_calls:
                    func = tc.get("function", {})
                    tool_name = func.get("name", "")
                    tool_args = func.get("arguments", {})

                    if on_step:
                        on_step("tool_call", {"name": tool_name, "args": tool_args})

                    # Execute the tool
                    handler = self.tool_handlers.get(tool_name)
                    if handler:
                        try:
                            result = handler(**tool_args)
                            result_str = json.dumps(result) if not isinstance(result, str) else result
                        except Exception as e:
                            result_str = f"Error: {e}"
                    else:
                        result_str = f"Error: unknown tool '{tool_name}'"

                    if on_step:
                        on_step("tool_result", {"name": tool_name, "result": result_str[:200]})

                    # Append tool result
                    messages.append({
                        "role": "tool",
                        "content": result_str,
                    })

                continue  # Next iteration with tool results

            # No tool calls - the agent is giving its final answer
            content = msg.get("content", "")
            if content:
                parsed = self._parse_json(content)
                if on_step:
                    on_step("answer", parsed)
                return parsed

        # Max iterations reached - force a final answer without tools
        messages.append({
            "role": "user",
            "content": "You've used all your tool calls. Based on what you've found so far, "
                       "return your best JSON answer now. Set unknown fields to null.",
        })
        response = self._call_llm(messages, include_tools=False)
        content = response.get("message", {}).get("content", "")
        parsed = self._parse_json(content)
        if on_step:
            on_step("answer", parsed)
        return parsed

    def _call_llm(self, messages: list, include_tools: bool = True) -> dict:
        """Send messages to Ollama and return the response."""
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": OLLAMA_NUM_PREDICT,
                "num_ctx": OLLAMA_CONTEXT_LENGTH,
            },
            "keep_alive": OLLAMA_KEEP_ALIVE,
        }
        if include_tools and self.tools:
            payload["tools"] = self.tools

        with httpx.Client(
            timeout=httpx.Timeout(connect=10, read=120, write=10, pool=10)
        ) as client:
            resp = client.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload)
            resp.raise_for_status()
            return resp.json()

    @staticmethod
    def _parse_json(text: str) -> dict:
        """Extract JSON object from LLM response text."""
        # Try direct parse
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try extracting from markdown code block
        if "```" in text:
            for block in text.split("```"):
                block = block.strip()
                if block.startswith("json"):
                    block = block[4:].strip()
                try:
                    return json.loads(block)
                except json.JSONDecodeError:
                    continue

        # Try finding JSON object boundaries
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass

        return {}
