"""Configuration management."""

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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


class TlsConfig(BaseModel):
    enabled: bool = False
    certfile: str = ""
    keyfile: str = ""


class ApiConfig(BaseModel):
    auth: AuthConfig = Field(default_factory=AuthConfig)
    cors: CorsConfig = Field(default_factory=CorsConfig)
    tls: TlsConfig = Field(default_factory=TlsConfig)


class ProviderConfig(BaseModel):
    enabled: bool = False
    api_key: str = ""
    base_url: str = ""
    default_model: str = ""
    models: list[str] = Field(default_factory=list)


class ProvidersConfig(BaseModel):
    default: str = "openai"
    timeout: int = 60
    retry_count: int = 2
    openai: ProviderConfig = Field(default_factory=ProviderConfig)
    anthropic: ProviderConfig = Field(default_factory=ProviderConfig)
    google: ProviderConfig = Field(default_factory=ProviderConfig)
    groq: ProviderConfig = Field(default_factory=ProviderConfig)
    ollama: ProviderConfig = Field(default_factory=ProviderConfig)

    def __getitem__(self, item: str) -> ProviderConfig:
        return getattr(self, item)

    def items(self) -> list[tuple[str, ProviderConfig]]:
        return [
            ("openai", self.openai),
            ("anthropic", self.anthropic),
            ("google", self.google),
            ("groq", self.groq),
            ("ollama", self.ollama),
        ]


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


class AxiomConfig(BaseModel):
    enabled: bool = True
    checkpoints_dir: str = "D:\\AXIOM-AETHER\\checkpoints"


class EveConfig(BaseModel):
    enabled: bool = True
    personas: list[str] = Field(default_factory=lambda: ["general", "developer", "researcher"])


class AdamConfig(BaseModel):
    enabled: bool = True
    memory_db: str = "D:\\ADAM\\adam_memory.db"
    genome_path: str = "D:\\ADAM\\adam_genome.json"


class CognitiveConfig(BaseModel):
    axiom: AxiomConfig = Field(default_factory=AxiomConfig)
    eve: EveConfig = Field(default_factory=EveConfig)
    adam: AdamConfig = Field(default_factory=AdamConfig)


class LoggingConfig(BaseModel):
    level: str = "INFO"
    structured: bool = True
    path: str = "logs/openchimera.jsonl"


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
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


def load_settings() -> Settings:
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
    return settings


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result
