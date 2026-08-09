"""Provider manager with modern AI provider adapters."""

import time
from typing import Any

from openchimera.config import ProvidersConfig, Settings
from openchimera.providers.base import BaseProvider


class OpenAIProvider(BaseProvider):
    name = "openai"

    async def chat(self, messages, model=None, tools=None):
        import openai
        client = openai.AsyncOpenAI(api_key=self.api_key, base_url=self.base_url or "https://api.openai.com/v1")
        start = time.perf_counter()
        try:
            kwargs = {"model": model or self.default_model, "messages": messages}
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"
            resp = await client.chat.completions.create(**kwargs)
            self._latency_ms = int((time.perf_counter() - start) * 1000)
            self._healthy = True
            msg = resp.choices[0].message
            return {
                "text": msg.content or "",
                "tool_calls": [tc.model_dump() for tc in (msg.tool_calls or [])],
            }
        except Exception as e:
            self._healthy = False
            return {"text": f"Error: {e}", "tool_calls": []}

    async def health_check(self) -> bool:
        try:
            import openai
            client = openai.AsyncOpenAI(api_key=self.api_key, base_url=self.base_url or "https://api.openai.com/v1")
            await client.models.list()
            self._healthy = True
            return True
        except Exception:
            self._healthy = False
            return False


class AnthropicProvider(BaseProvider):
    name = "anthropic"

    async def chat(self, messages, model=None, tools=None):
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=self.api_key, base_url=self.base_url or "https://api.anthropic.com/v1")
        start = time.perf_counter()
        try:
            system = None
            msgs = messages
            if messages and messages[0].get("role") == "system":
                system = messages[0]["content"]
                msgs = messages[1:]
            kwargs = {"model": model or self.default_model, "messages": msgs, "max_tokens": 4096}
            if system:
                kwargs["system"] = system
            if tools:
                kwargs["tools"] = tools
            resp = await client.messages.create(**kwargs)
            self._latency_ms = int((time.perf_counter() - start) * 1000)
            self._healthy = True
            text = ""
            tool_calls = []
            for block in resp.content:
                if block.type == "text":
                    text += block.text
                elif block.type == "tool_use":
                    tool_calls.append({"id": block.id, "type": "function", "function": {"name": block.name, "arguments": block.input}})
            return {"text": text, "tool_calls": tool_calls}
        except Exception as e:
            self._healthy = False
            return {"text": f"Error: {e}", "tool_calls": []}

    async def health_check(self) -> bool:
        try:
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=self.api_key)
            await client.messages.create(model=self.default_model, messages=[{"role": "user", "content": "hi"}], max_tokens=1)
            self._healthy = True
            return True
        except Exception:
            self._healthy = False
            return False


class GoogleProvider(BaseProvider):
    name = "google"

    async def chat(self, messages, model=None, tools=None):
        import google.generativeai as genai
        genai.configure(api_key=self.api_key)
        m = model or self.default_model
        start = time.perf_counter()
        try:
            client = genai.GenerativeModel(m)
            contents = []
            for msg in messages:
                if msg["role"] == "user":
                    contents.append(msg["content"])
                elif msg["role"] == "assistant":
                    contents.append({"role": "model", "parts": [msg["content"]]})
            resp = await client.generate_content_async(contents)
            self._latency_ms = int((time.perf_counter() - start) * 1000)
            self._healthy = True
            return {"text": resp.text or "", "tool_calls": []}
        except Exception as e:
            self._healthy = False
            return {"text": f"Error: {e}", "tool_calls": []}

    async def health_check(self) -> bool:
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            client = genai.GenerativeModel(self.default_model)
            await client.generate_content_async("hello")
            self._healthy = True
            return True
        except Exception:
            self._healthy = False
            return False


class GroqProvider(BaseProvider):
    name = "groq"

    async def chat(self, messages, model=None, tools=None):
        import groq
        client = groq.AsyncGroq(api_key=self.api_key, base_url=self.base_url or "https://api.groq.com/openai/v1")
        start = time.perf_counter()
        try:
            kwargs = {"model": model or self.default_model, "messages": messages}
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"
            resp = await client.chat.completions.create(**kwargs)
            self._latency_ms = int((time.perf_counter() - start) * 1000)
            self._healthy = True
            msg = resp.choices[0].message
            return {
                "text": msg.content or "",
                "tool_calls": [tc.model_dump() for tc in (msg.tool_calls or [])],
            }
        except Exception as e:
            self._healthy = False
            return {"text": f"Error: {e}", "tool_calls": []}

    async def health_check(self) -> bool:
        try:
            import groq
            client = groq.AsyncGroq(api_key=self.api_key)
            await client.models.list()
            self._healthy = True
            return True
        except Exception:
            self._healthy = False
            return False


class OllamaProvider(BaseProvider):
    name = "ollama"

    async def chat(self, messages, model=None, tools=None):
        import ollama
        start = time.perf_counter()
        try:
            resp = await ollama.AsyncClient(host=self.base_url or "http://localhost:11434").chat(
                model=model or self.default_model,
                messages=messages,
                tools=tools,
            )
            self._latency_ms = int((time.perf_counter() - start) * 1000)
            self._healthy = True
            return {
                "text": resp.message.content or "",
                "tool_calls": [tc.model_dump() for tc in (resp.message.tool_calls or [])],
            }
        except Exception as e:
            self._healthy = False
            return {"text": f"Error: {e}", "tool_calls": []}

    async def health_check(self) -> bool:
        try:
            import ollama
            await ollama.AsyncClient(host=self.base_url or "http://localhost:11434").list()
            self._healthy = True
            return True
        except Exception:
            self._healthy = False
            return False


class ProviderManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._providers: dict[str, BaseProvider] = {}
        cfg = settings.providers
        if cfg.openai.enabled:
            self._providers["openai"] = OpenAIProvider(api_key=cfg.openai.api_key, base_url=cfg.openai.base_url, default_model=cfg.openai.default_model)
        if cfg.anthropic.enabled:
            self._providers["anthropic"] = AnthropicProvider(api_key=cfg.anthropic.api_key, base_url=cfg.anthropic.base_url, default_model=cfg.anthropic.default_model)
        if cfg.google.enabled:
            self._providers["google"] = GoogleProvider(api_key=cfg.google.api_key, default_model=cfg.google.default_model)
        if cfg.groq.enabled:
            self._providers["groq"] = GroqProvider(api_key=cfg.groq.api_key, base_url=cfg.groq.base_url, default_model=cfg.groq.default_model)
        if cfg.ollama.enabled:
            self._providers["ollama"] = OllamaProvider(base_url=cfg.ollama.base_url, default_model=cfg.ollama.default_model)

    def get(self, name: str) -> BaseProvider | None:
        return self._providers.get(name)

    def get_default(self) -> BaseProvider:
        return self._providers.get(self.settings.providers.default) or next(iter(self._providers.values()))

    def get_all_status(self) -> list[dict[str, Any]]:
        results = []
        for name, prov in self._providers.items():
            status = prov.to_status()
            status["id"] = name
            status["name"] = name.capitalize()
            status["enabled"] = True
            status["healthy"] = prov.healthy
            status["latency_ms"] = prov.latency_ms
            results.append(status)
        return results

    async def health_check_all(self) -> None:
        for prov in self._providers.values():
            await prov.health_check()
