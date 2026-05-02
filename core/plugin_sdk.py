"""
Phase 5: Plugin SDK & Skill Marketplace.

Provides:
- PluginSDK: base classes and decorators for building plugins
- SkillMarketplace: registry for discovering, installing, and managing skills
- ModelProviderRegistry: unified interface to multiple LLM providers
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Type

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Plugin SDK
# ---------------------------------------------------------------------------

class PluginState(str, Enum):
    UNLOADED = "unloaded"
    LOADING = "loading"
    ACTIVE = "active"
    ERROR = "error"
    DISABLED = "disabled"


@dataclass
class PluginManifest:
    """Plugin metadata and capabilities declaration."""
    id: str
    name: str
    version: str = "0.1.0"
    description: str = ""
    author: str = ""
    license: str = "MIT"
    chimera_version: str = ">=1.0.0"
    capabilities: List[str] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    entry_point: str = ""
    icon: str = ""
    tags: List[str] = field(default_factory=list)
    homepage: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "license": self.license,
            "chimera_version": self.chimera_version,
            "capabilities": self.capabilities,
            "permissions": self.permissions,
            "dependencies": self.dependencies,
            "entry_point": self.entry_point,
            "tags": self.tags,
            "homepage": self.homepage,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PluginManifest":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class BasePlugin:
    """Base class for all OpenChimera plugins."""

    manifest: PluginManifest = PluginManifest(id="base", name="Base Plugin")

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self.state = PluginState.UNLOADED
        self._hooks: Dict[str, List[Callable]] = {}
        self._loaded_at: Optional[float] = None

    def on_load(self) -> None:
        """Called when plugin is loaded. Override to initialize resources."""
        pass

    def on_unload(self) -> None:
        """Called when plugin is unloaded. Override to clean up resources."""
        pass

    def on_message(self, message: dict) -> Optional[dict]:
        """Called for each message. Override to process messages."""
        return None

    def on_event(self, event_type: str, payload: dict) -> None:
        """Called for system events. Override to handle events."""
        pass

    def register_hook(self, event_type: str, handler: Callable) -> None:
        """Register a hook for a specific event type."""
        self._hooks.setdefault(event_type, []).append(handler)

    def trigger_hook(self, event_type: str, payload: dict) -> List[Any]:
        """Trigger all hooks for an event type."""
        results = []
        for handler in self._hooks.get(event_type, []):
            try:
                result = handler(payload)
                results.append(result)
            except Exception as exc:
                logger.warning("Plugin hook error (%s.%s): %s", self.manifest.id, event_type, exc)
        return results

    def status(self) -> dict:
        return {
            "id": self.manifest.id,
            "name": self.manifest.name,
            "version": self.manifest.version,
            "state": self.state.value,
            "loaded_at": self._loaded_at,
            "hook_types": list(self._hooks.keys()),
        }


def plugin_capability(*capabilities: str):
    """Decorator to declare plugin capabilities."""
    def decorator(cls: Type[BasePlugin]) -> Type[BasePlugin]:
        if hasattr(cls, "manifest"):
            cls.manifest.capabilities = list(capabilities)
        return cls
    return decorator


def plugin_permission(*permissions: str):
    """Decorator to declare required permissions."""
    def decorator(cls: Type[BasePlugin]) -> Type[BasePlugin]:
        if hasattr(cls, "manifest"):
            cls.manifest.permissions = list(permissions)
        return cls
    return decorator


class PluginRegistry:
    """
    Central registry for managing plugin lifecycle.
    """

    def __init__(self):
        self._plugins: Dict[str, BasePlugin] = {}
        self._manifests: Dict[str, PluginManifest] = {}
        self._load_errors: Dict[str, str] = {}

    def register(self, plugin: BasePlugin) -> None:
        """Register and load a plugin."""
        plugin_id = plugin.manifest.id
        try:
            plugin.state = PluginState.LOADING
            plugin.on_load()
            plugin.state = PluginState.ACTIVE
            plugin._loaded_at = time.time()
            self._plugins[plugin_id] = plugin
            self._manifests[plugin_id] = plugin.manifest
            logger.info("Plugin loaded: %s v%s", plugin.manifest.name, plugin.manifest.version)
        except Exception as exc:
            plugin.state = PluginState.ERROR
            self._load_errors[plugin_id] = str(exc)
            logger.error("Plugin load failed (%s): %s", plugin_id, exc)

    def unregister(self, plugin_id: str) -> bool:
        """Unload and remove a plugin."""
        plugin = self._plugins.get(plugin_id)
        if not plugin:
            return False
        try:
            plugin.on_unload()
        except Exception as exc:
            logger.warning("Plugin unload error (%s): %s", plugin_id, exc)
        plugin.state = PluginState.UNLOADED
        del self._plugins[plugin_id]
        return True

    def get(self, plugin_id: str) -> Optional[BasePlugin]:
        return self._plugins.get(plugin_id)

    def list_plugins(self) -> List[dict]:
        return [p.status() for p in self._plugins.values()]

    def dispatch_message(self, message: dict) -> List[dict]:
        """Dispatch a message to all active plugins."""
        responses = []
        for plugin in self._plugins.values():
            if plugin.state == PluginState.ACTIVE:
                try:
                    response = plugin.on_message(message)
                    if response:
                        responses.append(response)
                except Exception as exc:
                    logger.warning("Plugin message error (%s): %s", plugin.manifest.id, exc)
        return responses

    def dispatch_event(self, event_type: str, payload: dict) -> None:
        """Dispatch a system event to all active plugins."""
        for plugin in self._plugins.values():
            if plugin.state == PluginState.ACTIVE:
                try:
                    plugin.on_event(event_type, payload)
                    plugin.trigger_hook(event_type, payload)
                except Exception as exc:
                    logger.warning("Plugin event error (%s): %s", plugin.manifest.id, exc)

    def status(self) -> dict:
        return {
            "total": len(self._plugins),
            "active": sum(1 for p in self._plugins.values() if p.state == PluginState.ACTIVE),
            "errors": len(self._load_errors),
            "plugins": self.list_plugins(),
            "load_errors": self._load_errors,
        }


# ---------------------------------------------------------------------------
# Skill Marketplace
# ---------------------------------------------------------------------------

class SkillCategory(str, Enum):
    PRODUCTIVITY = "productivity"
    COMMUNICATION = "communication"
    ANALYTICS = "analytics"
    AUTOMATION = "automation"
    CREATIVE = "creative"
    DEVELOPER = "developer"
    SECURITY = "security"
    AI_TOOLS = "ai_tools"
    OTHER = "other"


@dataclass
class SkillListing:
    """Skill listing in the marketplace."""
    id: str
    name: str
    description: str
    category: SkillCategory
    version: str = "1.0.0"
    author: str = ""
    downloads: int = 0
    rating: float = 0.0
    rating_count: int = 0
    price: float = 0.0  # 0 = free
    tags: List[str] = field(default_factory=list)
    capabilities: List[str] = field(default_factory=list)
    requirements: List[str] = field(default_factory=list)
    install_command: str = ""
    source_url: str = ""
    verified: bool = False
    featured: bool = False
    published_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category.value,
            "version": self.version,
            "author": self.author,
            "downloads": self.downloads,
            "rating": self.rating,
            "rating_count": self.rating_count,
            "price": self.price,
            "tags": self.tags,
            "capabilities": self.capabilities,
            "requirements": self.requirements,
            "verified": self.verified,
            "featured": self.featured,
            "source_url": self.source_url,
        }


@dataclass
class SkillInstallation:
    """Tracks an installed skill."""
    skill_id: str
    version: str
    installed_at: float = field(default_factory=time.time)
    enabled: bool = True
    config: Dict[str, Any] = field(default_factory=dict)
    install_path: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "skill_id": self.skill_id,
            "version": self.version,
            "installed_at": self.installed_at,
            "enabled": self.enabled,
            "install_path": self.install_path,
        }


class SkillMarketplace:
    """
    Skill marketplace for discovering, installing, and managing skills.
    """

    def __init__(self, install_dir: Optional[Path] = None):
        self._install_dir = install_dir or Path("data/skills")
        self._listings: Dict[str, SkillListing] = {}
        self._installed: Dict[str, SkillInstallation] = {}
        self._download_counts: Dict[str, int] = {}
        self._populate_defaults()

    def _populate_defaults(self) -> None:
        """Populate with built-in skill listings."""
        defaults = [
            SkillListing(
                id="web-search",
                name="Web Search",
                description="Search the web and summarize results",
                category=SkillCategory.PRODUCTIVITY,
                author="OpenChimera Team",
                tags=["search", "web", "information"],
                capabilities=["search", "summarize"],
                verified=True,
                featured=True,
                downloads=1500,
                rating=4.8,
                rating_count=120,
            ),
            SkillListing(
                id="code-executor",
                name="Code Executor",
                description="Execute Python code in a sandboxed environment",
                category=SkillCategory.DEVELOPER,
                author="OpenChimera Team",
                tags=["code", "python", "execution", "sandbox"],
                capabilities=["execute_code", "run_tests"],
                verified=True,
                featured=True,
                downloads=2100,
                rating=4.9,
                rating_count=200,
            ),
            SkillListing(
                id="summarizer",
                name="Document Summarizer",
                description="Summarize documents, articles, and web pages",
                category=SkillCategory.PRODUCTIVITY,
                author="OpenChimera Team",
                tags=["summarize", "document", "text"],
                capabilities=["summarize"],
                verified=True,
                downloads=890,
                rating=4.6,
                rating_count=75,
            ),
            SkillListing(
                id="image-gen",
                name="Image Generator",
                description="Generate images from text descriptions",
                category=SkillCategory.CREATIVE,
                author="OpenChimera Team",
                tags=["image", "generation", "creative", "ai"],
                capabilities=["generate_image"],
                verified=True,
                downloads=3200,
                rating=4.7,
                rating_count=310,
            ),
            SkillListing(
                id="data-analyzer",
                name="Data Analyzer",
                description="Analyze CSV, JSON, and tabular data",
                category=SkillCategory.ANALYTICS,
                author="OpenChimera Team",
                tags=["data", "analytics", "csv", "visualization"],
                capabilities=["analyze_data", "visualize"],
                verified=True,
                downloads=750,
                rating=4.5,
                rating_count=60,
            ),
        ]
        for listing in defaults:
            self._listings[listing.id] = listing

    def search(
        self,
        query: str = "",
        category: Optional[SkillCategory] = None,
        tags: Optional[List[str]] = None,
        free_only: bool = False,
        verified_only: bool = False,
        limit: int = 20,
    ) -> List[dict]:
        """Search the marketplace for skills."""
        results = list(self._listings.values())
        if query:
            q = query.lower()
            results = [s for s in results if q in s.name.lower() or q in s.description.lower() or any(q in t for t in s.tags)]
        if category:
            results = [s for s in results if s.category == category]
        if tags:
            results = [s for s in results if any(t in s.tags for t in tags)]
        if free_only:
            results = [s for s in results if s.price == 0.0]
        if verified_only:
            results = [s for s in results if s.verified]
        # Sort by featured + downloads + rating
        results.sort(key=lambda s: (s.featured, s.downloads, s.rating), reverse=True)
        return [s.to_dict() for s in results[:limit]]

    def get_listing(self, skill_id: str) -> Optional[dict]:
        listing = self._listings.get(skill_id)
        return listing.to_dict() if listing else None

    def install(self, skill_id: str, version: Optional[str] = None, config: Optional[dict] = None) -> dict:
        """Install a skill from the marketplace."""
        listing = self._listings.get(skill_id)
        if not listing:
            return {"status": "error", "reason": "skill_not_found", "skill_id": skill_id}
        if skill_id in self._installed:
            return {"status": "already_installed", "skill_id": skill_id, "version": self._installed[skill_id].version}
        install_version = version or listing.version
        installation = SkillInstallation(
            skill_id=skill_id,
            version=install_version,
            config=config or {},
            install_path=str(self._install_dir / skill_id),
        )
        self._installed[skill_id] = installation
        listing.downloads += 1
        logger.info("Skill installed: %s v%s", skill_id, install_version)
        return {"status": "installed", "skill_id": skill_id, "version": install_version}

    def uninstall(self, skill_id: str) -> dict:
        """Uninstall a skill."""
        if skill_id not in self._installed:
            return {"status": "error", "reason": "not_installed", "skill_id": skill_id}
        del self._installed[skill_id]
        return {"status": "uninstalled", "skill_id": skill_id}

    def publish(self, listing: SkillListing) -> dict:
        """Publish a new skill to the marketplace."""
        self._listings[listing.id] = listing
        return {"status": "published", "skill_id": listing.id, "version": listing.version}

    def rate(self, skill_id: str, rating: float, user_id: str = "anonymous") -> dict:
        """Rate a skill (1-5 stars)."""
        listing = self._listings.get(skill_id)
        if not listing:
            return {"status": "error", "reason": "skill_not_found"}
        if not 1.0 <= rating <= 5.0:
            return {"status": "error", "reason": "invalid_rating"}
        total = listing.rating * listing.rating_count + rating
        listing.rating_count += 1
        listing.rating = round(total / listing.rating_count, 2)
        return {"status": "rated", "skill_id": skill_id, "new_rating": listing.rating}

    def list_installed(self) -> List[dict]:
        return [i.to_dict() for i in self._installed.values()]

    def status(self) -> dict:
        return {
            "total_listings": len(self._listings),
            "installed_count": len(self._installed),
            "featured_count": sum(1 for s in self._listings.values() if s.featured),
            "verified_count": sum(1 for s in self._listings.values() if s.verified),
            "categories": sorted(set(s.category.value for s in self._listings.values())),
        }


# ---------------------------------------------------------------------------
# Model Provider Registry
# ---------------------------------------------------------------------------

class ModelProviderType(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    MISTRAL = "mistral"
    OLLAMA = "ollama"
    GROQ = "groq"
    TOGETHER = "together"
    COHERE = "cohere"
    LOCAL = "local"
    CUSTOM = "custom"


@dataclass
class ModelSpec:
    """Specification for a model within a provider."""
    id: str
    name: str
    provider: ModelProviderType
    context_window: int = 4096
    max_output_tokens: int = 1024
    supports_vision: bool = False
    supports_function_calling: bool = False
    supports_streaming: bool = True
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0
    is_local: bool = False
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "provider": self.provider.value,
            "context_window": self.context_window,
            "max_output_tokens": self.max_output_tokens,
            "supports_vision": self.supports_vision,
            "supports_function_calling": self.supports_function_calling,
            "supports_streaming": self.supports_streaming,
            "cost_per_1k_input": self.cost_per_1k_input,
            "cost_per_1k_output": self.cost_per_1k_output,
            "is_local": self.is_local,
            "tags": self.tags,
        }


@dataclass
class ProviderConfig:
    """Configuration for a model provider."""
    provider: ModelProviderType
    api_key: str = ""
    base_url: str = ""
    default_model: str = ""
    timeout_seconds: float = 30.0
    max_retries: int = 3
    enabled: bool = True
    extra: Dict[str, Any] = field(default_factory=dict)


class ModelProviderRegistry:
    """
    Unified registry for multiple LLM providers.
    Enables model selection, routing, and fallback.
    """

    BUILTIN_MODELS = [
        ModelSpec("gpt-4o", "GPT-4o", ModelProviderType.OPENAI, 128000, 4096, True, True, True, 2.5, 10.0),
        ModelSpec("gpt-4o-mini", "GPT-4o Mini", ModelProviderType.OPENAI, 128000, 4096, True, True, True, 0.15, 0.6),
        ModelSpec("gpt-3.5-turbo", "GPT-3.5 Turbo", ModelProviderType.OPENAI, 16385, 4096, False, True, True, 0.5, 1.5),
        ModelSpec("claude-3-5-sonnet-20241022", "Claude 3.5 Sonnet", ModelProviderType.ANTHROPIC, 200000, 8192, True, True, True, 3.0, 15.0),
        ModelSpec("claude-3-haiku-20240307", "Claude 3 Haiku", ModelProviderType.ANTHROPIC, 200000, 4096, True, True, True, 0.25, 1.25),
        ModelSpec("gemini-1.5-pro", "Gemini 1.5 Pro", ModelProviderType.GOOGLE, 2000000, 8192, True, True, True, 1.25, 5.0),
        ModelSpec("gemini-1.5-flash", "Gemini 1.5 Flash", ModelProviderType.GOOGLE, 1000000, 8192, True, True, True, 0.075, 0.3),
        ModelSpec("mistral-large-latest", "Mistral Large", ModelProviderType.MISTRAL, 128000, 4096, False, True, True, 2.0, 6.0),
        ModelSpec("llama3.2:3b", "Llama 3.2 3B", ModelProviderType.OLLAMA, 128000, 4096, False, True, True, 0.0, 0.0, True),
        ModelSpec("llama3.2:1b", "Llama 3.2 1B", ModelProviderType.OLLAMA, 128000, 4096, False, False, True, 0.0, 0.0, True),
        ModelSpec("mixtral-8x7b-32768", "Mixtral 8x7B", ModelProviderType.GROQ, 32768, 4096, False, True, True, 0.27, 0.27),
    ]

    def __init__(self):
        self._providers: Dict[ModelProviderType, ProviderConfig] = {}
        self._models: Dict[str, ModelSpec] = {}
        self._usage_stats: Dict[str, Dict[str, float]] = {}
        # Register builtin models
        for model in self.BUILTIN_MODELS:
            self._models[model.id] = model

    def configure_provider(self, config: ProviderConfig) -> None:
        """Configure a provider with credentials and settings."""
        self._providers[config.provider] = config
        logger.info("Provider configured: %s", config.provider.value)

    def register_model(self, spec: ModelSpec) -> None:
        """Register a custom model spec."""
        self._models[spec.id] = spec

    def get_model(self, model_id: str) -> Optional[ModelSpec]:
        return self._models.get(model_id)

    def list_models(
        self,
        provider: Optional[ModelProviderType] = None,
        supports_vision: Optional[bool] = None,
        supports_function_calling: Optional[bool] = None,
        local_only: bool = False,
        free_only: bool = False,
    ) -> List[dict]:
        """List available models with optional filters."""
        models = list(self._models.values())
        if provider:
            models = [m for m in models if m.provider == provider]
        if supports_vision is not None:
            models = [m for m in models if m.supports_vision == supports_vision]
        if supports_function_calling is not None:
            models = [m for m in models if m.supports_function_calling == supports_function_calling]
        if local_only:
            models = [m for m in models if m.is_local]
        if free_only:
            models = [m for m in models if m.cost_per_1k_input == 0.0]
        return [m.to_dict() for m in models]

    def select_model(
        self,
        task: str = "general",
        prefer_local: bool = False,
        budget_per_1k: Optional[float] = None,
        require_vision: bool = False,
        require_function_calling: bool = False,
    ) -> Optional[dict]:
        """Intelligently select the best model for a task."""
        models = list(self._models.values())
        if prefer_local:
            local_models = [m for m in models if m.is_local]
            if local_models:
                models = local_models
        if require_vision:
            models = [m for m in models if m.supports_vision]
        if require_function_calling:
            models = [m for m in models if m.supports_function_calling]
        if budget_per_1k is not None:
            models = [m for m in models if m.cost_per_1k_input <= budget_per_1k]
        if not models:
            return None
        # Sort by: local first if preferred, then by cost (ascending)
        models.sort(key=lambda m: (not m.is_local if prefer_local else 0, m.cost_per_1k_input))
        return models[0].to_dict()

    def record_usage(self, model_id: str, input_tokens: int, output_tokens: int) -> None:
        """Record token usage for a model."""
        stats = self._usage_stats.setdefault(model_id, {"input_tokens": 0, "output_tokens": 0, "calls": 0})
        stats["input_tokens"] += input_tokens
        stats["output_tokens"] += output_tokens
        stats["calls"] += 1

    def get_usage_stats(self) -> dict:
        total_cost = 0.0
        for model_id, stats in self._usage_stats.items():
            model = self._models.get(model_id)
            if model:
                total_cost += (stats["input_tokens"] / 1000) * model.cost_per_1k_input
                total_cost += (stats["output_tokens"] / 1000) * model.cost_per_1k_output
        return {
            "per_model": self._usage_stats,
            "total_estimated_cost_usd": round(total_cost, 4),
        }

    def status(self) -> dict:
        return {
            "configured_providers": [p.value for p in self._providers.keys()],
            "total_models": len(self._models),
            "local_models": sum(1 for m in self._models.values() if m.is_local),
            "providers": {p.value: {"enabled": c.enabled, "has_api_key": bool(c.api_key)} for p, c in self._providers.items()},
            "usage": self.get_usage_stats(),
        }
