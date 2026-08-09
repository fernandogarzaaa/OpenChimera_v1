"""Configuration management — declarative provider profiles like Hermes Agent."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# ═══════════════════════════════════════════════════════════════════════════════
# Server & API Config
# ═══════════════════════════════════════════════════════════════════════════════

class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 7870
    workers: int = 1
    reload: bool = False


class AuthConfig(BaseModel):
    enabled: bool = False
    token: str = ""
    admin_token: str = ""


class CorsConfig(BaseModel):
    enabled: bool = True
    origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])


class ApiConfig(BaseModel):
    auth: AuthConfig = Field(default_factory=AuthConfig)
    cors: CorsConfig = Field(default_factory=CorsConfig)


# ═══════════════════════════════════════════════════════════════════════════════
# Declarative Provider Profile (inspired by Hermes Agent)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ProviderProfile:
    """Declarative provider profile — everything about an inference provider."""

    name: str
    display_name: str = ""
    description: str = ""
    signup_url: str = ""
    base_url: str = ""
    models_url: str = ""
    auth_type: str = "api_key"  # api_key | oauth | aws_sdk
    env_var: str = ""  # e.g. OPENAI_API_KEY
    supports_vision: bool = False
    supports_tools: bool = True
    supports_streaming: bool = True
    supports_reasoning: bool = False
    default_model: str = ""
    fallback_models: tuple[str, ...] = ()
    default_headers: dict[str, str] = field(default_factory=dict)
    fixed_temperature: Any = None
    default_max_tokens: int | None = None
    extra_body: dict[str, Any] = field(default_factory=dict)

    def get_base_url(self, override: str | None = None) -> str:
        return (override or self.base_url).rstrip("/")

    def get_models_url(self, override: str | None = None) -> str:
        if self.models_url:
            return self.models_url
        base = self.get_base_url(override)
        return f"{base}/models" if base else ""


# ═══════════════════════════════════════════════════════════════════════════════
# Provider Config (runtime instance config)
# ═══════════════════════════════════════════════════════════════════════════════

class ProviderInstanceConfig(BaseModel):
    enabled: bool = False
    api_key: str = ""
    base_url: str = ""
    default_model: str = ""
    models: list[str] = Field(default_factory=list)
    timeout: int = 60


class ProvidersConfig(BaseModel):
    default: str = "openai"
    timeout: int = 60
    retry_count: int = 2
    openai: ProviderInstanceConfig = Field(default_factory=ProviderInstanceConfig)
    anthropic: ProviderInstanceConfig = Field(default_factory=ProviderInstanceConfig)
    google: ProviderInstanceConfig = Field(default_factory=ProviderInstanceConfig)
    groq: ProviderInstanceConfig = Field(default_factory=ProviderInstanceConfig)
    ollama: ProviderInstanceConfig = Field(default_factory=ProviderInstanceConfig)
    deepseek: ProviderInstanceConfig = Field(default_factory=ProviderInstanceConfig)
    mistral: ProviderInstanceConfig = Field(default_factory=ProviderInstanceConfig)
    cohere: ProviderInstanceConfig = Field(default_factory=ProviderInstanceConfig)
    azure: ProviderInstanceConfig = Field(default_factory=ProviderInstanceConfig)
    together: ProviderInstanceConfig = Field(default_factory=ProviderInstanceConfig)
    fireworks: ProviderInstanceConfig = Field(default_factory=ProviderInstanceConfig)
    xai: ProviderInstanceConfig = Field(default_factory=ProviderInstanceConfig)
    perplexity: ProviderInstanceConfig = Field(default_factory=ProviderInstanceConfig)
    openrouter: ProviderInstanceConfig = Field(default_factory=ProviderInstanceConfig)
    bedrock: ProviderInstanceConfig = Field(default_factory=ProviderInstanceConfig)
    cerebras: ProviderInstanceConfig = Field(default_factory=ProviderInstanceConfig)
    ai21: ProviderInstanceConfig = Field(default_factory=ProviderInstanceConfig)

    def __getitem__(self, item: str) -> ProviderInstanceConfig:
        return getattr(self, item)

    def items(self) -> list[tuple[str, ProviderInstanceConfig]]:
        return [
            ("openai", self.openai),
            ("anthropic", self.anthropic),
            ("google", self.google),
            ("groq", self.groq),
            ("ollama", self.ollama),
            ("deepseek", self.deepseek),
            ("mistral", self.mistral),
            ("cohere", self.cohere),
            ("azure", self.azure),
            ("together", self.together),
            ("fireworks", self.fireworks),
            ("xai", self.xai),
            ("perplexity", self.perplexity),
            ("openrouter", self.openrouter),
            ("bedrock", self.bedrock),
            ("cerebras", self.cerebras),
            ("ai21", self.ai21),
        ]


# ═══════════════════════════════════════════════════════════════════════════════
# MCP, RAG, Cognitive, Logging
# ═══════════════════════════════════════════════════════════════════════════════

class McpConfig(BaseModel):
    enabled: bool = True
    registry_path: str = "data/mcp_registry.json"
    health_check_interval: int = 300
    default_timeout: int = 30


class RagConfig(BaseModel):
    enabled: bool = True
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    vector_store: str = "chroma"
    chunk_size: int = 512
    chunk_overlap: int = 64
    top_k: int = 5
    persist_dir: str = "data/rag_db"


class AxiomConfig(BaseModel):
    enabled: bool = True
    checkpoints_dir: str = "D:\\AXIOM-AETHER\\checkpoints"
    auto_recall: bool = True


class EveConfig(BaseModel):
    enabled: bool = True
    personas: list[str] = Field(default_factory=lambda: ["general", "developer", "researcher"])
    auto_approve: bool = False


class AdamConfig(BaseModel):
    enabled: bool = True
    memory_db: str = "D:\\ADAM\\adam_memory.db"
    genome_path: str = "D:\\ADAM\\adam_genome.json"
    auto_evolve: bool = False


class CognitiveConfig(BaseModel):
    axiom: AxiomConfig = Field(default_factory=AxiomConfig)
    eve: EveConfig = Field(default_factory=EveConfig)
    adam: AdamConfig = Field(default_factory=AdamConfig)


class LoggingConfig(BaseModel):
    level: str = "INFO"
    structured: bool = True
    path: str = "logs/openchimera.jsonl"


class ComputerUseConfig(BaseModel):
    enabled: bool = True
    browser: str = "chromium"  # chromium | firefox | webkit
    headless: bool = True
    screenshot_dir: str = "data/screenshots"
    viewport_width: int = 1280
    viewport_height: int = 720


# ═══════════════════════════════════════════════════════════════════════════════
# Top-level Settings
# ═══════════════════════════════════════════════════════════════════════════════

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OPENCHIMERA_",
        env_nested_separator="__",
        extra="ignore",
    )

    config_path: Path = Path("config/default.yaml")
    server: ServerConfig = Field(default_factory=ServerConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    mcp: McpConfig = Field(default_factory=McpConfig)
    rag: RagConfig = Field(default_factory=RagConfig)
    cognitive: CognitiveConfig = Field(default_factory=CognitiveConfig)
    computer_use: ComputerUseConfig = Field(default_factory=ComputerUseConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


# ═══════════════════════════════════════════════════════════════════════════════
# Settings loader with layered YAML merge
# ═══════════════════════════════════════════════════════════════════════════════

_SETTINGS_CACHE: Settings | None = None


def load_settings(force_reload: bool = False) -> Settings:
    global _SETTINGS_CACHE
    if _SETTINGS_CACHE is not None and not force_reload:
        return _SETTINGS_CACHE

    paths = [
        Path("config/default.yaml"),
        Path("config/local.yaml"),
    ]
    env_path = os.getenv("OPENCHIMERA_CONFIG", "")
    if env_path:
        paths.insert(1, Path(env_path))

    merged: dict[str, Any] = {}
    for p in paths:
        if p.exists():
            with p.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                merged = _deep_merge(merged, data)

    settings = Settings(**merged)
    settings.config_path = paths[0]
    _SETTINGS_CACHE = settings
    return settings


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result
