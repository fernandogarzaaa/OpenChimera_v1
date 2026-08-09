"""Provider manager with 17+ modern AI provider adapters."""

from __future__ import annotations

import json
import time
from typing import Any

from openchimera.config import ProvidersConfig, Settings
from openchimera.providers.base import BaseProvider, get_profile


# ═══════════════════════════════════════════════════════════════════════════════
# OpenAI-compatible providers (OpenAI, Groq, Together, Fireworks, xAI, DeepSeek,
# OpenRouter, Cerebras, AI21, Mistral, Cohere)
# ═══════════════════════════════════════════════════════════════════════════════

class OpenAICompatibleProvider(BaseProvider):
    """Base for all OpenAI-compatible API providers."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._client = None

    def _get_client(self):
        if self._client is None:
            import openai
            base = self.base_url or (self.profile.base_url if self.profile else "https://api.openai.com/v1")
            kwargs: dict[str, Any] = {"api_key": self.api_key, "base_url": base}
            if self.profile and self.profile.default_headers:
                kwargs["default_headers"] = self.profile.default_headers
            self._client = openai.AsyncOpenAI(**kwargs)
        return self._client

    async def chat(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        tools: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        client = self._get_client()
        start = time.perf_counter()
        m = model or self.default_model
        try:
            kwargs: dict[str, Any] = {"model": m, "messages": messages}
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"
            if temperature is not None:
                kwargs["temperature"] = temperature
            if max_tokens is not None:
                kwargs["max_tokens"] = max_tokens
            if stream:
                kwargs["stream"] = True

            # Provider-specific extra body
            if self.profile and self.profile.extra_body:
                kwargs["extra_body"] = self.profile.extra_body.copy()

            resp = await client.chat.completions.create(**kwargs)
            self._latency_ms = int((time.perf_counter() - start) * 1000)
            self._healthy = True

            if stream:
                return {"stream": resp, "provider": self.name, "model": m}

            msg = resp.choices[0].message
            return {
                "text": msg.content or "",
                "tool_calls": [tc.model_dump() for tc in (msg.tool_calls or [])],
                "usage": resp.usage.model_dump() if resp.usage else {},
                "provider": self.name,
                "model": m,
            }
        except Exception as e:
            self._healthy = False
            return {"text": f"Error: {e}", "tool_calls": [], "provider": self.name, "model": m}

    async def health_check(self) -> bool:
        try:
            client = self._get_client()
            await client.models.list()
            self._healthy = True
            return True
        except Exception:
            self._healthy = False
            return False

    async def _fetch_models(self) -> list[str]:
        try:
            client = self._get_client()
            models = await client.models.list()
            self._models = [m.id for m in models.data]
            return self._models
        except Exception:
            return list(self.profile.fallback_models) if self.profile else []


class OpenAIProvider(OpenAICompatibleProvider):
    name = "openai"
    profile = get_profile("openai")


class GroqProvider(OpenAICompatibleProvider):
    name = "groq"
    profile = get_profile("groq")


class TogetherProvider(OpenAICompatibleProvider):
    name = "together"
    profile = get_profile("together")


class FireworksProvider(OpenAICompatibleProvider):
    name = "fireworks"
    profile = get_profile("fireworks")


class XAIProvider(OpenAICompatibleProvider):
    name = "xai"
    profile = get_profile("xai")


class DeepSeekProvider(OpenAICompatibleProvider):
    name = "deepseek"
    profile = get_profile("deepseek")


class OpenRouterProvider(OpenAICompatibleProvider):
    name = "openrouter"
    profile = get_profile("openrouter")


class CerebrasProvider(OpenAICompatibleProvider):
    name = "cerebras"
    profile = get_profile("cerebras")


class AI21Provider(OpenAICompatibleProvider):
    name = "ai21"
    profile = get_profile("ai21")


class MistralProvider(OpenAICompatibleProvider):
    name = "mistral"
    profile = get_profile("mistral")


class CohereProvider(OpenAICompatibleProvider):
    name = "cohere"
    profile = get_profile("cohere")


# ═══════════════════════════════════════════════════════════════════════════════
# Anthropic Provider
# ═══════════════════════════════════════════════════════════════════════════════

class AnthropicProvider(BaseProvider):
    name = "anthropic"
    profile = get_profile("anthropic")

    def _get_client(self):
        import anthropic
        return anthropic.AsyncAnthropic(
            api_key=self.api_key,
            base_url=self.base_url or "https://api.anthropic.com/v1",
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        tools: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        client = self._get_client()
        start = time.perf_counter()
        m = model or self.default_model
        try:
            system = None
            msgs = messages
            if messages and messages[0].get("role") == "system":
                system = messages[0]["content"]
                msgs = messages[1:]

            kwargs: dict[str, Any] = {"model": m, "messages": msgs, "max_tokens": max_tokens or 4096}
            if system:
                kwargs["system"] = system
            if tools:
                kwargs["tools"] = tools
            if temperature is not None:
                kwargs["temperature"] = temperature
            if stream:
                kwargs["stream"] = True

            resp = await client.messages.create(**kwargs)
            self._latency_ms = int((time.perf_counter() - start) * 1000)
            self._healthy = True

            if stream:
                return {"stream": resp, "provider": self.name, "model": m}

            text = ""
            tool_calls = []
            for block in resp.content:
                if block.type == "text":
                    text += block.text
                elif block.type == "tool_use":
                    tool_calls.append({
                        "id": block.id,
                        "type": "function",
                        "function": {"name": block.name, "arguments": block.input},
                    })
            return {
                "text": text,
                "tool_calls": tool_calls,
                "usage": {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens} if resp.usage else {},
                "provider": self.name,
                "model": m,
            }
        except Exception as e:
            self._healthy = False
            return {"text": f"Error: {e}", "tool_calls": [], "provider": self.name, "model": m}

    async def health_check(self) -> bool:
        try:
            client = self._get_client()
            await client.messages.create(
                model=self.default_model,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=1,
            )
            self._healthy = True
            return True
        except Exception:
            self._healthy = False
            return False


# ═══════════════════════════════════════════════════════════════════════════════
# Google Provider (Gemini)
# ═══════════════════════════════════════════════════════════════════════════════

class GoogleProvider(BaseProvider):
    name = "google"
    profile = get_profile("google")

    async def chat(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        tools: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
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

            kwargs: dict[str, Any] = {}
            if temperature is not None:
                kwargs["temperature"] = temperature
            if max_tokens is not None:
                from google.generativeai.types import GenerationConfig
                kwargs["generation_config"] = GenerationConfig(max_output_tokens=max_tokens)

            resp = await client.generate_content_async(contents, **kwargs)
            self._latency_ms = int((time.perf_counter() - start) * 1000)
            self._healthy = True
            return {
                "text": resp.text or "",
                "tool_calls": [],
                "provider": self.name,
                "model": m,
            }
        except Exception as e:
            self._healthy = False
            return {"text": f"Error: {e}", "tool_calls": [], "provider": self.name, "model": m}

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


# ═══════════════════════════════════════════════════════════════════════════════
# Ollama Provider
# ═══════════════════════════════════════════════════════════════════════════════

class OllamaProvider(BaseProvider):
    name = "ollama"
    profile = get_profile("ollama")

    async def chat(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        tools: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        import ollama
        start = time.perf_counter()
        m = model or self.default_model
        try:
            kwargs: dict[str, Any] = {"model": m, "messages": messages}
            if tools:
                kwargs["tools"] = tools
            if stream:
                kwargs["stream"] = True

            resp = await ollama.AsyncClient(host=self.base_url or "http://localhost:11434").chat(**kwargs)
            self._latency_ms = int((time.perf_counter() - start) * 1000)
            self._healthy = True

            if stream:
                return {"stream": resp, "provider": self.name, "model": m}

            return {
                "text": resp.message.content or "",
                "tool_calls": [tc.model_dump() for tc in (resp.message.tool_calls or [])],
                "provider": self.name,
                "model": m,
            }
        except Exception as e:
            self._healthy = False
            return {"text": f"Error: {e}", "tool_calls": [], "provider": self.name, "model": m}

    async def health_check(self) -> bool:
        try:
            import ollama
            await ollama.AsyncClient(host=self.base_url or "http://localhost:11434").list()
            self._healthy = True
            return True
        except Exception:
            self._healthy = False
            return False

    async def _fetch_models(self) -> list[str]:
        try:
            import ollama
            models = await ollama.AsyncClient(host=self.base_url or "http://localhost:11434").list()
            self._models = [m.model for m in models.models]
            return self._models
        except Exception:
            return list(self.profile.fallback_models) if self.profile else []


# ═══════════════════════════════════════════════════════════════════════════════
# Azure OpenAI Provider
# ═══════════════════════════════════════════════════════════════════════════════

class AzureProvider(BaseProvider):
    name = "azure"
    profile = get_profile("azure")

    def _get_client(self):
        import openai
        return openai.AsyncAzureOpenAI(
            api_key=self.api_key,
            azure_endpoint=self.base_url,
            api_version="2024-10-21",
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        tools: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        client = self._get_client()
        start = time.perf_counter()
        m = model or self.default_model
        try:
            kwargs: dict[str, Any] = {"model": m, "messages": messages}
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"
            if temperature is not None:
                kwargs["temperature"] = temperature
            if max_tokens is not None:
                kwargs["max_tokens"] = max_tokens

            resp = await client.chat.completions.create(**kwargs)
            self._latency_ms = int((time.perf_counter() - start) * 1000)
            self._healthy = True
            msg = resp.choices[0].message
            return {
                "text": msg.content or "",
                "tool_calls": [tc.model_dump() for tc in (msg.tool_calls or [])],
                "provider": self.name,
                "model": m,
            }
        except Exception as e:
            self._healthy = False
            return {"text": f"Error: {e}", "tool_calls": [], "provider": self.name, "model": m}

    async def health_check(self) -> bool:
        try:
            client = self._get_client()
            await client.models.list()
            self._healthy = True
            return True
        except Exception:
            self._healthy = False
            return False


# ═══════════════════════════════════════════════════════════════════════════════
# AWS Bedrock Provider
# ═══════════════════════════════════════════════════════════════════════════════

class BedrockProvider(BaseProvider):
    name = "bedrock"
    profile = get_profile("bedrock")

    async def chat(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        tools: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        try:
            import boto3
            from botocore.config import Config as BotoConfig

            start = time.perf_counter()
            m = model or self.default_model
            client = boto3.client(
                "bedrock-runtime",
                config=BotoConfig(connect_timeout=10, read_timeout=60),
            )

            body: dict[str, Any] = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": max_tokens or 4096,
                "messages": messages,
            }
            if temperature is not None:
                body["temperature"] = temperature
            if tools:
                body["tools"] = tools

            resp = client.invoke_model(modelId=m, body=json.dumps(body))
            result = json.loads(resp["body"].read())
            self._latency_ms = int((time.perf_counter() - start) * 1000)
            self._healthy = True

            text = ""
            tool_calls = []
            for block in result.get("content", []):
                if block.get("type") == "text":
                    text += block.get("text", "")
                elif block.get("type") == "tool_use":
                    tool_calls.append({
                        "id": block.get("id"),
                        "type": "function",
                        "function": {"name": block.get("name"), "arguments": block.get("input", {})},
                    })

            return {
                "text": text,
                "tool_calls": tool_calls,
                "provider": self.name,
                "model": m,
            }
        except Exception as e:
            self._healthy = False
            return {"text": f"Error: {e}", "tool_calls": [], "provider": self.name, "model": m}

    async def health_check(self) -> bool:
        try:
            import boto3
            client = boto3.client("bedrock-runtime")
            client.invoke_model(
                modelId=self.default_model,
                body=json.dumps({"anthropic_version": "bedrock-2023-05-31", "max_tokens": 1, "messages": [{"role": "user", "content": "hi"}]}),
            )
            self._healthy = True
            return True
        except Exception:
            self._healthy = False
            return False


# ═══════════════════════════════════════════════════════════════════════════════
# Provider Manager
# ═══════════════════════════════════════════════════════════════════════════════

_PROVIDER_CLASSES: dict[str, type[BaseProvider]] = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "google": GoogleProvider,
    "groq": GroqProvider,
    "ollama": OllamaProvider,
    "deepseek": DeepSeekProvider,
    "mistral": MistralProvider,
    "cohere": CohereProvider,
    "azure": AzureProvider,
    "together": TogetherProvider,
    "fireworks": FireworksProvider,
    "xai": XAIProvider,
    "perplexity": CohereProvider,  # Perplexity is OpenAI-compatible
    "openrouter": OpenRouterProvider,
    "bedrock": BedrockProvider,
    "cerebras": CerebrasProvider,
    "ai21": AI21Provider,
}


class ProviderManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._providers: dict[str, BaseProvider] = {}
        self._init_providers()

    def _init_providers(self) -> None:
        for name, cfg in self.settings.providers.items():
            if not cfg.enabled:
                continue
            cls = _PROVIDER_CLASSES.get(name)
            if not cls:
                continue
            try:
                self._providers[name] = cls(
                    api_key=cfg.api_key,
                    base_url=cfg.base_url,
                    default_model=cfg.default_model,
                    config=cfg,
                )
            except Exception:
                pass

    def get(self, name: str) -> BaseProvider | None:
        return self._providers.get(name)

    def get_default(self) -> BaseProvider:
        default = self._providers.get(self.settings.providers.default)
        if default:
            return default
        if self._providers:
            return next(iter(self._providers.values()))
        raise RuntimeError("No providers configured")

    def get_all_status(self) -> list[dict[str, Any]]:
        results = []
        for name, prov in self._providers.items():
            status = prov.to_status()
            status["enabled"] = True
            results.append(status)
        # Also include disabled providers for visibility
        for name, cfg in self.settings.providers.items():
            if name not in self._providers:
                profile = get_profile(name)
                results.append({
                    "id": name,
                    "name": profile.display_name if profile else name.capitalize(),
                    "enabled": False,
                    "healthy": False,
                    "latency_ms": None,
                    "default_model": cfg.default_model or (profile.default_model if profile else ""),
                    "models": list(profile.fallback_models) if profile else [],
                    "supports_vision": profile.supports_vision if profile else False,
                    "supports_tools": profile.supports_tools if profile else True,
                })
        return results

    async def health_check_all(self) -> None:
        import asyncio
        await asyncio.gather(
            *[prov.health_check() for prov in self._providers.values()],
            return_exceptions=True,
        )

    @property
    def available_providers(self) -> list[str]:
        return list(self._providers.keys())
