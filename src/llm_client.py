"""
Unified LLM Client - Abstracts Ollama and OpenAI-compatible APIs.

Supports local Ollama and cloud providers (Gemini, OpenAI, Anthropic,
DeepSeek) through the OpenAI chat completions format. Embeddings always
stay local via Ollama.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx

# Known provider base URLs
PROVIDER_URLS = {
    "ollama": "http://127.0.0.1:11434",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "deepseek": "https://api.deepseek.com",
}

# Default models per provider
PROVIDER_DEFAULTS = {
    "ollama": "gemma4:26b",
    "gemini": "gemini-2.5-flash",
    "openai": "gpt-4o-mini",
    "deepseek": "deepseek-chat",
}


class LLMClient:
    """Unified LLM client for Ollama and OpenAI-compatible providers."""

    def __init__(
        self,
        provider: str = "ollama",
        base_url: str = None,
        model: str = None,
        api_key: str = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        context_length: int = 8192,
        keep_alive: str = "10m",
    ):
        self.provider = provider
        self.base_url = (base_url or PROVIDER_URLS.get(provider, "")).rstrip("/")
        self.model = model or PROVIDER_DEFAULTS.get(provider, "")
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.context_length = context_length
        self.keep_alive = keep_alive

    # ── Sync Chat (non-streaming) ────────────────

    def chat(self, messages: list, tools: list = None, **kwargs) -> dict:
        """Synchronous chat completion. Returns normalized response dict.

        Returns: {"message": {"content": str, "thinking": str, "tool_calls": list}}
        """
        if self.provider == "ollama":
            return self._ollama_chat(messages, tools, stream=False, **kwargs)
        else:
            return self._openai_chat(messages, tools, **kwargs)

    # ── Sync Streaming Chat ──────────────────────

    def chat_stream(self, messages: list, **kwargs):
        """Synchronous streaming chat. Yields (type, content) tuples.

        type is "thinking", "content", or "done".
        """
        if self.provider == "ollama":
            yield from self._ollama_stream(messages, **kwargs)
        else:
            yield from self._openai_stream(messages, **kwargs)

    # ── Async Streaming Chat ─────────────────────

    async def achat_stream(self, messages: list, **kwargs):
        """Async streaming chat. Yields (type, content) tuples."""
        if self.provider == "ollama":
            async for item in self._ollama_astream(messages, **kwargs):
                yield item
        else:
            async for item in self._openai_astream(messages, **kwargs):
                yield item

    # ── Embeddings (always local Ollama) ─────────

    def embed(self, texts: list[str], model: str = "nomic-embed-text",
              ollama_url: str = "http://127.0.0.1:11434") -> list[list[float]]:
        """Generate embeddings via local Ollama. Always local, never cloud."""
        with httpx.Client(timeout=120) as client:
            resp = client.post(
                f"{ollama_url}/api/embed",
                json={
                    "model": model,
                    "input": texts,
                    "keep_alive": self.keep_alive,
                },
            )
            resp.raise_for_status()
            return resp.json().get("embeddings", [])

    # ── Test Connection ──────────────────────────

    def test_connection(self) -> dict:
        """Test if the LLM provider is reachable. Returns status dict."""
        try:
            if self.provider == "ollama":
                with httpx.Client(timeout=5) as client:
                    resp = client.get(f"{self.base_url}/api/tags")
                    resp.raise_for_status()
                    models = [m["name"] for m in resp.json().get("models", [])]
                    return {
                        "status": "connected",
                        "provider": "ollama",
                        "model": self.model,
                        "model_available": any(
                            self.model.split(":")[0] in m for m in models
                        ),
                        "available_models": models,
                    }
            else:
                # OpenAI-compatible: try listing models
                headers = self._openai_headers()
                with httpx.Client(timeout=10) as client:
                    resp = client.get(
                        f"{self.base_url}/models",
                        headers=headers,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        models = [m["id"] for m in data.get("data", [])]
                        return {
                            "status": "connected",
                            "provider": self.provider,
                            "model": self.model,
                            "model_available": self.model in models,
                            "available_models": models[:20],
                        }
                    else:
                        # Some providers don't support /models but still work
                        # Try a minimal chat request
                        resp = client.post(
                            f"{self.base_url}/chat/completions",
                            headers=headers,
                            json={
                                "model": self.model,
                                "messages": [{"role": "user", "content": "hi"}],
                                "max_tokens": 5,
                            },
                        )
                        resp.raise_for_status()
                        return {
                            "status": "connected",
                            "provider": self.provider,
                            "model": self.model,
                            "model_available": True,
                            "available_models": [self.model],
                        }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    # ── Ollama Backend ───────────────────────────

    def _ollama_chat(self, messages, tools=None, stream=False, **kwargs):
        """Ollama /api/chat call."""
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
            "options": {
                "temperature": kwargs.get("temperature", self.temperature),
                "num_predict": kwargs.get("max_tokens", self.max_tokens),
                "num_ctx": self.context_length,
            },
            "keep_alive": self.keep_alive,
        }
        if kwargs.get("top_p") is not None:
            payload["options"]["top_p"] = kwargs["top_p"]
        if tools:
            payload["tools"] = tools

        timeout = httpx.Timeout(connect=10, read=300, write=10, pool=10)
        with httpx.Client(timeout=timeout) as client:
            if stream:
                content_parts = []
                with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if line:
                            chunk = json.loads(line)
                            content = chunk.get("message", {}).get("content", "")
                            if content:
                                content_parts.append(content)
                            if chunk.get("done"):
                                break
                return {
                    "message": {
                        "content": "".join(content_parts),
                        "role": "assistant",
                    }
                }
            else:
                resp = client.post(f"{self.base_url}/api/chat", json=payload)
                resp.raise_for_status()
                return resp.json()

    def _ollama_stream(self, messages, **kwargs):
        """Ollama streaming yields (type, content) tuples."""
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": kwargs.get("temperature", self.temperature),
                "num_predict": kwargs.get("max_tokens", self.max_tokens),
                "num_ctx": self.context_length,
            },
            "keep_alive": self.keep_alive,
        }
        if kwargs.get("top_p") is not None:
            payload["options"]["top_p"] = kwargs["top_p"]

        timeout = httpx.Timeout(connect=10, read=300, write=10, pool=10)
        with httpx.Client(timeout=timeout) as client:
            with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if line:
                        chunk = json.loads(line)
                        msg = chunk.get("message", {})
                        if msg.get("thinking"):
                            yield ("thinking", msg["thinking"])
                        if msg.get("content"):
                            yield ("content", msg["content"])
                        if chunk.get("done"):
                            break

    async def _ollama_astream(self, messages, **kwargs):
        """Async Ollama streaming."""
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": kwargs.get("temperature", self.temperature),
                "num_predict": kwargs.get("max_tokens", self.max_tokens),
                "num_ctx": self.context_length,
            },
            "keep_alive": self.keep_alive,
        }
        if kwargs.get("top_p") is not None:
            payload["options"]["top_p"] = kwargs["top_p"]

        timeout = httpx.Timeout(connect=10, read=300, write=10, pool=10)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line:
                        chunk = json.loads(line)
                        msg = chunk.get("message", {})
                        if msg.get("thinking"):
                            yield ("thinking", msg["thinking"])
                        if msg.get("content"):
                            yield ("content", msg["content"])
                        if chunk.get("done"):
                            break

    # ── OpenAI-Compatible Backend ────────────────

    def _openai_headers(self):
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _openai_chat(self, messages, tools=None, **kwargs):
        """OpenAI-compatible /v1/chat/completions call."""
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", self.temperature),
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
        }
        if tools:
            payload["tools"] = tools

        with httpx.Client(timeout=httpx.Timeout(connect=10, read=120, write=10, pool=10)) as client:
            resp = client.post(
                f"{self.base_url}/chat/completions",
                headers=self._openai_headers(),
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

            # Normalize to Ollama-like format
            choice = data.get("choices", [{}])[0]
            msg = choice.get("message", {})
            return {
                "message": {
                    "content": msg.get("content", ""),
                    "role": msg.get("role", "assistant"),
                    "tool_calls": msg.get("tool_calls", []),
                }
            }

    def _openai_stream(self, messages, **kwargs):
        """OpenAI-compatible streaming. Yields (type, content) tuples."""
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", self.temperature),
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "stream": True,
        }

        with httpx.Client(timeout=httpx.Timeout(connect=10, read=300, write=10, pool=10)) as client:
            with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=self._openai_headers(),
                json=payload,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield ("content", content)
                        except json.JSONDecodeError:
                            continue

    async def _openai_astream(self, messages, **kwargs):
        """Async OpenAI-compatible streaming."""
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", self.temperature),
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "stream": True,
        }

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10, read=300, write=10, pool=10)
        ) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=self._openai_headers(),
                json=payload,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield ("content", content)
                        except json.JSONDecodeError:
                            continue


# ── Singleton / Factory ──────────────────────────

_chat_client = None
_agent_client = None


def get_chat_client() -> LLMClient:
    """Get the chat LLM client (lazy init from settings)."""
    global _chat_client
    if _chat_client is None:
        _chat_client = _build_client_from_settings("chat")
    return _chat_client


def get_agent_client() -> LLMClient:
    """Get the agent LLM client (lazy init, falls back to chat client)."""
    global _agent_client
    if _agent_client is None:
        _agent_client = _build_client_from_settings("agent")
    return _agent_client


def reload_clients():
    """Force reload clients from settings (after settings change)."""
    global _chat_client, _agent_client
    _chat_client = None
    _agent_client = None


def _build_client_from_settings(purpose: str) -> LLMClient:
    """Build an LLMClient from DB settings or config.py defaults."""
    try:
        from src.models import get_setting
        provider = get_setting(f"{purpose}_provider") or get_setting("llm_provider")
        base_url = get_setting(f"{purpose}_base_url") or get_setting("llm_base_url")
        model = get_setting(f"{purpose}_model") or get_setting("llm_model")
        api_key = get_setting(f"{purpose}_api_key") or get_setting("llm_api_key")
        temperature = float(get_setting("llm_temperature") or "0.3")
    except Exception:
        provider = None

    if not provider:
        # Fall back to config.py defaults
        from config import (
            OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_TEMPERATURE,
            OLLAMA_NUM_PREDICT, OLLAMA_CONTEXT_LENGTH,
        )
        return LLMClient(
            provider="ollama",
            base_url=OLLAMA_BASE_URL,
            model=OLLAMA_MODEL,
            temperature=OLLAMA_TEMPERATURE,
            max_tokens=OLLAMA_NUM_PREDICT,
            context_length=OLLAMA_CONTEXT_LENGTH,
        )

    return LLMClient(
        provider=provider,
        base_url=base_url,
        model=model,
        api_key=api_key,
        temperature=temperature,
    )
