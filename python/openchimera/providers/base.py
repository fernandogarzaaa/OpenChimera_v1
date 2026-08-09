"""Provider base class and profiles — declarative architecture inspired by Hermes Agent."""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

from openchimera.config import ProviderInstanceConfig, ProviderProfile


class BaseProvider(ABC):
    """Abstract base for all AI providers."""

    name: str = "base"
    profile: ProviderProfile | None = None

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "",
        default_model: str = "",
        config: ProviderInstanceConfig | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.default_model = default_model or (self.profile.default_model if self.profile else "")
        self.config = config
        self._healthy: bool | None = None
        self._latency_ms: int | None = None
        self._models: list[str] = []

    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        tools: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        ...

    async def list_models(self) -> list[str]:
        """Return cached or fetched model list."""
        if self._models:
            return self._models
        return await self._fetch_models()

    async def _fetch_models(self) -> list[str]:
        """Override to fetch live model catalog."""
        return []

    @property
    def healthy(self) -> bool:
        return self._healthy or False

    @property
    def latency_ms(self) -> int | None:
        return self._latency_ms

    def to_status(self) -> dict[str, Any]:
        return {
            "id": self.name,
            "name": (self.profile.display_name if self.profile else self.name).capitalize(),
            "enabled": bool(self.api_key or self.base_url),
            "healthy": self.healthy,
            "latency_ms": self.latency_ms,
            "default_model": self.default_model,
            "models": self._models or [self.default_model],
            "supports_vision": self.profile.supports_vision if self.profile else False,
            "supports_tools": self.profile.supports_tools if self.profile else True,
            "last_error": None,
            "last_checked": None,
        }

    def _prepare_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Provider-specific message preprocessing. Override in subclass."""
        if self.profile and self.profile.prepare_messages:
            return self.profile.prepare_messages(messages)
        return messages

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.profile and self.profile.default_headers:
            headers.update(self.profile.default_headers)
        if self.api_key and self.profile and self.profile.auth_type == "api_key":
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers


# ── Provider Profile Registry ──────────────────────────────────────────────

PROVIDER_PROFILES: dict[str, ProviderProfile] = {
    "openai": ProviderProfile(
        name="openai",
        display_name="OpenAI",
        description="OpenAI GPT models (GPT-4o, o1, o3-mini)",
        signup_url="https://platform.openai.com",
        base_url="https://api.openai.com/v1",
        env_var="OPENAI_API_KEY",
        supports_vision=True,
        supports_tools=True,
        supports_streaming=True,
        supports_reasoning=True,
        default_model="gpt-4o",
        fallback_models=("gpt-4o", "gpt-4o-mini", "o1", "o3-mini", "gpt-4.1"),
    ),
    "anthropic": ProviderProfile(
        name="anthropic",
        display_name="Anthropic",
        description="Claude models by Anthropic",
        signup_url="https://console.anthropic.com",
        base_url="https://api.anthropic.com/v1",
        env_var="ANTHROPIC_API_KEY",
        supports_vision=True,
        supports_tools=True,
        supports_streaming=True,
        default_model="claude-3-5-sonnet-20241022",
        fallback_models=(
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-opus-20240229",
            "claude-3-7-sonnet-20250219",
        ),
    ),
    "google": ProviderProfile(
        name="google",
        display_name="Google AI",
        description="Google Gemini models",
        signup_url="https://ai.google.dev",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        env_var="GOOGLE_API_KEY",
        supports_vision=True,
        supports_tools=True,
        supports_streaming=True,
        default_model="gemini-1.5-flash-latest",
        fallback_models=("gemini-1.5-flash-latest", "gemini-1.5-pro-latest", "gemini-2.0-flash-exp"),
    ),
    "groq": ProviderProfile(
        name="groq",
        display_name="Groq",
        description="Ultra-fast inference via Groq",
        signup_url="https://console.groq.com",
        base_url="https://api.groq.com/openai/v1",
        env_var="GROQ_API_KEY",
        supports_vision=True,
        supports_tools=True,
        supports_streaming=True,
        default_model="llama-3.3-70b-versatile",
        fallback_models=("llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"),
    ),
    "ollama": ProviderProfile(
        name="ollama",
        display_name="Ollama",
        description="Local LLMs via Ollama",
        signup_url="https://ollama.com",
        base_url="http://localhost:11434",
        env_var="OLLAMA_HOST",
        auth_type="none",
        supports_vision=True,
        supports_tools=True,
        supports_streaming=True,
        default_model="llama3.2",
        fallback_models=("llama3.2", "llama3.1", "mistral", "phi4"),
    ),
    "deepseek": ProviderProfile(
        name="deepseek",
        display_name="DeepSeek",
        description="DeepSeek chat and reasoning models",
        signup_url="https://platform.deepseek.com",
        base_url="https://api.deepseek.com/v1",
        env_var="DEEPSEEK_API_KEY",
        supports_vision=False,
        supports_tools=True,
        supports_streaming=True,
        supports_reasoning=True,
        default_model="deepseek-chat",
        fallback_models=("deepseek-chat", "deepseek-reasoner"),
    ),
    "mistral": ProviderProfile(
        name="mistral",
        display_name="Mistral AI",
        description="Mistral and Codestral models",
        signup_url="https://console.mistral.ai",
        base_url="https://api.mistral.ai/v1",
        env_var="MISTRAL_API_KEY",
        supports_vision=True,
        supports_tools=True,
        supports_streaming=True,
        default_model="mistral-large-latest",
        fallback_models=("mistral-large-latest", "mistral-medium-latest", "codestral-latest"),
    ),
    "cohere": ProviderProfile(
        name="cohere",
        display_name="Cohere",
        description="Command R+ and other Cohere models",
        signup_url="https://cohere.com",
        base_url="https://api.cohere.ai/v1",
        env_var="COHERE_API_KEY",
        supports_vision=False,
        supports_tools=True,
        supports_streaming=True,
        default_model="command-r-plus",
        fallback_models=("command-r-plus", "command-r", "command"),
    ),
    "azure": ProviderProfile(
        name="azure",
        display_name="Azure OpenAI",
        description="OpenAI models on Azure",
        signup_url="https://azure.microsoft.com",
        base_url="",
        env_var="AZURE_OPENAI_API_KEY",
        auth_type="api_key",
        supports_vision=True,
        supports_tools=True,
        supports_streaming=True,
        default_model="gpt-4o",
        fallback_models=("gpt-4o", "gpt-4o-mini", "gpt-4-turbo"),
    ),
    "together": ProviderProfile(
        name="together",
        display_name="Together AI",
        description="Open-source models via Together AI",
        signup_url="https://api.together.xyz",
        base_url="https://api.together.xyz/v1",
        env_var="TOGETHER_API_KEY",
        supports_vision=True,
        supports_tools=True,
        supports_streaming=True,
        default_model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
        fallback_models=("meta-llama/Llama-3.3-70B-Instruct-Turbo", "mistralai/Mixtral-8x7B-Instruct-v0.1"),
    ),
    "fireworks": ProviderProfile(
        name="fireworks",
        display_name="Fireworks AI",
        description="Fast inference for open-source models",
        signup_url="https://fireworks.ai",
        base_url="https://api.fireworks.ai/inference/v1",
        env_var="FIREWORKS_API_KEY",
        supports_vision=True,
        supports_tools=True,
        supports_streaming=True,
        default_model="accounts/fireworks/models/llama-v3p3-70b-instruct",
        fallback_models=("accounts/fireworks/models/llama-v3p3-70b-instruct",),
    ),
    "xai": ProviderProfile(
        name="xai",
        display_name="xAI",
        description="Grok models by xAI",
        signup_url="https://x.ai",
        base_url="https://api.x.ai/v1",
        env_var="XAI_API_KEY",
        supports_vision=True,
        supports_tools=True,
        supports_streaming=True,
        default_model="grok-2-latest",
        fallback_models=("grok-2-latest", "grok-2-vision-latest"),
    ),
    "perplexity": ProviderProfile(
        name="perplexity",
        display_name="Perplexity",
        description="Perplexity search-augmented models",
        signup_url="https://perplexity.ai",
        base_url="https://api.perplexity.ai",
        env_var="PERPLEXITY_API_KEY",
        supports_vision=False,
        supports_tools=False,
        supports_streaming=True,
        default_model="sonar-pro",
        fallback_models=("sonar-pro", "sonar", "sonar-reasoning"),
    ),
    "openrouter": ProviderProfile(
        name="openrouter",
        display_name="OpenRouter",
        description="Unified API for 200+ models",
        signup_url="https://openrouter.ai",
        base_url="https://openrouter.ai/api/v1",
        env_var="OPENROUTER_API_KEY",
        supports_vision=True,
        supports_tools=True,
        supports_streaming=True,
        default_model="openai/gpt-4o",
        fallback_models=("openai/gpt-4o", "anthropic/claude-3.5-sonnet", "meta-llama/llama-3.3-70b-instruct"),
        default_headers={"HTTP-Referer": "https://github.com/fernandogarzaaa/OpenChimera_v1"},
    ),
    "bedrock": ProviderProfile(
        name="bedrock",
        display_name="AWS Bedrock",
        description="Amazon Bedrock managed models",
        signup_url="https://aws.amazon.com/bedrock",
        base_url="",
        env_var="AWS_ACCESS_KEY_ID",
        auth_type="aws_sdk",
        supports_vision=True,
        supports_tools=True,
        supports_streaming=True,
        default_model="anthropic.claude-3-5-sonnet-20241022-v2:0",
        fallback_models=("anthropic.claude-3-5-sonnet-20241022-v2:0",),
    ),
    "cerebras": ProviderProfile(
        name="cerebras",
        display_name="Cerebras",
        description="Ultra-fast inference on Cerebras hardware",
        signup_url="https://cloud.cerebras.ai",
        base_url="https://api.cerebras.ai/v1",
        env_var="CEREBRAS_API_KEY",
        supports_vision=False,
        supports_tools=True,
        supports_streaming=True,
        default_model="llama3.1-70b",
        fallback_models=("llama3.1-70b", "llama-3.3-70b"),
    ),
    "ai21": ProviderProfile(
        name="ai21",
        display_name="AI21 Labs",
        description="Jamba and Jurassic models",
        signup_url="https://studio.ai21.com",
        base_url="https://api.ai21.com/studio/v1",
        env_var="AI21_API_KEY",
        supports_vision=False,
        supports_tools=True,
        supports_streaming=True,
        default_model="jamba-1.5-large",
        fallback_models=("jamba-1.5-large", "jamba-1.5-mini"),
    ),
}


def get_profile(name: str) -> ProviderProfile | None:
    return PROVIDER_PROFILES.get(name)
