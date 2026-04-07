from __future__ import annotations

import json
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from core.transactions import atomic_write_json


PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def _resolve_workspace_root() -> Path:
    override = os.getenv("OPENCHIMERA_ROOT")
    if override:
        return Path(override).expanduser().resolve()

    cwd = Path.cwd().resolve()
    if (cwd / "core").is_dir() and ((cwd / "run.py").exists() or (cwd / "pyproject.toml").exists()):
        return cwd

    return PACKAGE_ROOT


ROOT = _resolve_workspace_root()
DEFAULT_AETHER_ROOT = ROOT / "external" / "aether"
DEFAULT_WRAITH_ROOT = ROOT / "external" / "wraith"
DEFAULT_EVO_ROOT = ROOT / "external" / "evo"
DEFAULT_APPFORGE_ROOT = ROOT / "external" / "appforge"
DEFAULT_AEGIS_MOBILE_ROOT = ROOT / "external" / "aegis-mobile"
DEFAULT_LEGACY_WORKSPACE_ROOT = ROOT / "external" / "legacy-workspace"
DEFAULT_OPENCLAW_ROOT = DEFAULT_LEGACY_WORKSPACE_ROOT
DEFAULT_AEGIS_ROOT = DEFAULT_LEGACY_WORKSPACE_ROOT / "aegis_swarm"
DEFAULT_ASCENSION_ROOT = DEFAULT_AEGIS_ROOT
DEFAULT_ABO_ROOT = DEFAULT_LEGACY_WORKSPACE_ROOT / "abo"
DEFAULT_HARNESS_REPO_ROOT = ROOT / "external" / "upstream-harness-repo"
DEFAULT_LEGACY_HARNESS_SNAPSHOT_ROOT = DEFAULT_LEGACY_WORKSPACE_ROOT / "integrations" / "legacy-harness-snapshot"
DEFAULT_MINIMIND_ROOT = ROOT / "external" / "minimind"
DEFAULT_PROVIDER_HOST = "127.0.0.1"
DEFAULT_PROVIDER_PORT = 7870
DEFAULT_API_AUTH_HEADER = "Authorization"
DEFAULT_RUNTIME_PROFILE_OVERRIDE_FILENAME = "runtime_profile.local.json"


def _is_truthy_env(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def is_loopback_host(host: str) -> bool:
    normalized = str(host or "").strip().lower()
    return normalized in {"127.0.0.1", "localhost", "::1"}


def is_insecure_bind_allowed() -> bool:
    env_value = os.getenv("OPENCHIMERA_ALLOW_INSECURE_BIND", "").strip().lower()
    if env_value:
        return env_value in {"1", "true", "yes", "on"}
    profile = load_runtime_profile()
    api_profile = profile.get("api", {}) if isinstance(profile.get("api", {}), dict) else {}
    security = api_profile.get("security", {}) if isinstance(api_profile.get("security", {}), dict) else {}
    return bool(security.get("allow_insecure_bind", False))


def get_runtime_profile_path() -> Path:
    return ROOT / "config" / "runtime_profile.json"


def get_runtime_profile_override_path() -> Path:
    override_path = os.getenv("OPENCHIMERA_RUNTIME_PROFILE")
    if override_path:
        return Path(override_path).expanduser()
    return ROOT / "config" / DEFAULT_RUNTIME_PROFILE_OVERRIDE_FILENAME


def default_runtime_profile() -> dict[str, Any]:
    return {
        "generated_at": "bootstrap-default",
        "api": {
            "auth": {
                "enabled": False,
                "header": DEFAULT_API_AUTH_HEADER,
                "token": "",
                "admin_token": "",
            },
            "tls": {
                "enabled": False,
                "certfile": "",
                "keyfile": "",
                "key_password": "",
            },
        },
        "external_roots": {
            "aether": str(DEFAULT_AETHER_ROOT),
            "wraith": str(DEFAULT_WRAITH_ROOT),
            "evo": str(DEFAULT_EVO_ROOT),
            "appforge": str(DEFAULT_APPFORGE_ROOT),
            "legacy_workspace": str(DEFAULT_LEGACY_WORKSPACE_ROOT),
            "openclaw": str(DEFAULT_OPENCLAW_ROOT),
            "aegis": str(DEFAULT_AEGIS_ROOT),
            "ascension": str(DEFAULT_ASCENSION_ROOT),
            "aegis_mobile": str(DEFAULT_AEGIS_MOBILE_ROOT),
        },
        "integration_roots": {
            "harness_repo": str(DEFAULT_HARNESS_REPO_ROOT),
            "legacy_harness_snapshot": str(DEFAULT_LEGACY_HARNESS_SNAPSHOT_ROOT),
            "minimind": str(DEFAULT_MINIMIND_ROOT),
        },
        "providers": {
            "enabled": ["openchimera-gateway", "local-llama-cpp", "minimind"],
            "preferred_cloud_provider": "",
            "prefer_free_models": False,
            "failover_chain": [],
        },
        "onboarding": {
            "completed_at": None,
            "preferred_channel_id": "",
            "selected_cloud_provider": "",
        },
        "hardware": {
            "cpu_count": os.cpu_count() or 4,
            "ram_gb": 0.0,
            "gpu": {
                "available": False,
                "name": "unknown",
                "vram_gb": 0.0,
                "device_count": 0,
            },
        },
        "local_runtime": {
            "mode": "bootstrap-safe",
            "preferred_local_models": ["llama-3.2-3b", "phi-3.5-mini"],
            "local_max_tokens": 128,
            "local_timeout_s": 35.0,
            "cpu_threads": os.cpu_count() or 4,
            "reasoning_engine": "minimind",
            "worker_runtime": "llama.cpp",
            "context_length": 4096,
            "reasoning_engine_config": {
                "python_executable": "",
                "api_host": DEFAULT_PROVIDER_HOST,
                "api_port": 8998,
                "auto_start_server": False,
                "shutdown_with_provider": True,
                "device": "cpu",
                "serve_weight": "reason",
                "serve_max_seq_len": 8192,
                "hidden_size": 512,
                "num_hidden_layers": 8,
                "training_num_workers": 0,
                "training_epochs": 1,
                "training_batch_size": 4,
                "training_from_weight": "full_sft",
                "training_save_dir": "data/minimind",
            },
            "launcher": {
                "enabled": True,
                "auto_start": False,
                "shutdown_with_manager": False,
                "llama_server_path": "",
                "shared_args": [],
                "model_args": {},
            },
        },
        "autonomy": {
            "enabled": True,
            "auto_start": True,
            "artifacts": {
                "retention": {
                    "max_history_entries": 100,
                    "max_age_days": 30,
                }
            },
            "alerts": {
                "enabled": True,
                "dispatch_topic": "system/autonomy/alert",
                "minimum_severity": "high",
            },
            "digests": {
                "dispatch_topic": "system/briefing/daily",
                "history_limit": 5,
            },
            "jobs": {
                "sync_scouted_models": {"enabled": True, "interval_seconds": 900},
                "discover_free_models": {"enabled": True, "interval_seconds": 3600},
                "learn_fallback_rankings": {"enabled": True, "interval_seconds": 1800},
                "audit_skill_bridges": {"enabled": True, "interval_seconds": 1800},
                "refresh_harness_dataset": {"enabled": True, "interval_seconds": 21600},
                "check_degradation_chains": {"enabled": True, "interval_seconds": 1800},
                "run_self_audit": {"enabled": True, "interval_seconds": 3600},
                "preview_self_repair": {"enabled": True, "interval_seconds": 7200},
                "dispatch_operator_digest": {"enabled": True, "interval_seconds": 14400},
            },
        },
        "supervision": {
            "enabled": True,
            "interval_seconds": 15,
            "restart_cooldown_seconds": 30,
        },
        "observability": {
            "recent_limit": 64,
            "persistence": {
                "enabled": True,
                "path": "data/observability.db",
            },
        },
        "logging": {
            "level": "INFO",
            "structured": {
                "enabled": True,
                "path": "logs/openchimera-runtime.jsonl",
            },
        },
        "model_inventory": {
            "models_dir": str(ROOT / "models"),
            "available_models": [],
            "model_files": {},
            "known_models": {},
            "discovery_sources": [],
        },
        "reasoning_engine": {
            "name": "minimind",
            "training_output_dir": "data/minimind",
            "api_base_url": "http://127.0.0.1:8998",
        },
    }


def normalize_runtime_profile(profile: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
    base = default_runtime_profile()
    changed = False
    incoming = profile if isinstance(profile, dict) else {}

    def merge_dict(target: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
        nonlocal changed
        merged: dict[str, Any] = {}
        for key, value in target.items():
            if key not in source:
                merged[key] = value
                changed = True
                continue
            source_value = source[key]
            if isinstance(value, dict) and isinstance(source_value, dict):
                merged[key] = merge_dict(value, source_value)
            else:
                merged[key] = source_value
        for key, value in source.items():
            if key not in merged:
                merged[key] = value
        return merged

    normalized = merge_dict(base, incoming)
    return normalized, changed


def validate_runtime_profile(profile: dict[str, Any] | None) -> list[str]:
    normalized = profile if isinstance(profile, dict) else {}
    errors: list[str] = []

    api = normalized.get("api", {}) if isinstance(normalized.get("api", {}), dict) else {}
    auth = api.get("auth", {}) if isinstance(api.get("auth", {}), dict) else {}
    tls = api.get("tls", {}) if isinstance(api.get("tls", {}), dict) else {}
    providers = normalized.get("providers", {}) if isinstance(normalized.get("providers", {}), dict) else {}
    local_runtime = normalized.get("local_runtime", {}) if isinstance(normalized.get("local_runtime", {}), dict) else {}
    autonomy = normalized.get("autonomy", {}) if isinstance(normalized.get("autonomy", {}), dict) else {}
    supervision = normalized.get("supervision", {}) if isinstance(normalized.get("supervision", {}), dict) else {}

    auth_enabled = bool(auth.get("enabled", False) or os.getenv("OPENCHIMERA_API_TOKEN", "").strip())
    auth_token = os.getenv("OPENCHIMERA_API_TOKEN", "").strip() or str(auth.get("token", "")).strip()
    auth_header = os.getenv("OPENCHIMERA_API_AUTH_HEADER", "").strip() or str(auth.get("header", DEFAULT_API_AUTH_HEADER)).strip()
    if auth_enabled and not auth_token:
        errors.append("api.auth.enabled requires a user token in the runtime profile or OPENCHIMERA_API_TOKEN")
    if auth_enabled and not auth_header:
        errors.append("api.auth.enabled requires a non-empty auth header")

    tls_enabled = bool(tls.get("enabled", False) or _is_truthy_env(os.getenv("OPENCHIMERA_TLS_ENABLED", "")))
    tls_certfile = os.getenv("OPENCHIMERA_TLS_CERTFILE", "").strip() or str(tls.get("certfile", "")).strip()
    tls_keyfile = os.getenv("OPENCHIMERA_TLS_KEYFILE", "").strip() or str(tls.get("keyfile", "")).strip()
    if tls_enabled and not tls_certfile:
        errors.append("api.tls.enabled requires a certfile in the runtime profile or OPENCHIMERA_TLS_CERTFILE")
    if tls_enabled and not tls_keyfile:
        errors.append("api.tls.enabled requires a keyfile in the runtime profile or OPENCHIMERA_TLS_KEYFILE")

    preferred_cloud_provider = str(providers.get("preferred_cloud_provider", "")).strip()
    enabled_providers = [str(item).strip() for item in providers.get("enabled", []) if str(item).strip()]
    if preferred_cloud_provider and preferred_cloud_provider not in enabled_providers:
        errors.append("providers.preferred_cloud_provider must also appear in providers.enabled")
    failover_chain = providers.get("failover_chain", [])
    if not isinstance(failover_chain, list):
        errors.append("providers.failover_chain must be a list of provider IDs")

    context_length = local_runtime.get("context_length", 4096)
    try:
        if int(context_length) <= 0:
            raise ValueError()
    except (TypeError, ValueError):
        errors.append("local_runtime.context_length must be a positive integer")

    supervision_interval = supervision.get("interval_seconds", 15)
    supervision_cooldown = supervision.get("restart_cooldown_seconds", 30)
    try:
        if float(supervision_interval) <= 0:
            raise ValueError()
    except (TypeError, ValueError):
        errors.append("supervision.interval_seconds must be greater than zero")
    try:
        if float(supervision_cooldown) < 0:
            raise ValueError()
    except (TypeError, ValueError):
        errors.append("supervision.restart_cooldown_seconds must be zero or greater")

    jobs = autonomy.get("jobs", {}) if isinstance(autonomy.get("jobs", {}), dict) else {}
    for job_name, job_config in jobs.items():
        if not isinstance(job_config, dict) or not bool(job_config.get("enabled", True)):
            continue
        interval_seconds = job_config.get("interval_seconds", 0)
        try:
            if int(interval_seconds) <= 0:
                raise ValueError()
        except (TypeError, ValueError):
            errors.append(f"autonomy.jobs.{job_name}.interval_seconds must be greater than zero when enabled")

    return errors


def save_runtime_profile(profile: dict[str, Any]) -> None:
    profile_path = get_runtime_profile_path()
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(profile_path, profile)
    load_runtime_profile.cache_clear()


def is_supported_harness_repo_root(candidate: Path) -> bool:
    src_root = candidate / "src"
    required_files = [
        src_root / "main.py",
        src_root / "port_manifest.py",
        src_root / "query_engine.py",
        src_root / "commands.py",
        src_root / "tools.py",
    ]
    blocked_markers = [
        candidate / "extract-sources.js",
        candidate / "package" / "cli.js",
        candidate / "package" / "cli.js.map",
        candidate / "restored-src",
    ]
    return all(path.exists() for path in required_files) and not any(path.exists() for path in blocked_markers)


def resolve_root(env_var: str, configured_path: Path | None, default_path: Path) -> Path:
    env_override = os.getenv(env_var)
    if env_override:
        return Path(env_override).expanduser()

    default_candidate = default_path.expanduser()
    if configured_path is None:
        return default_candidate

    configured_candidate = configured_path.expanduser()
    if configured_candidate.exists() or not default_candidate.exists():
        return configured_candidate
    return default_candidate


def get_aether_root() -> Path:
    profile = load_runtime_profile()
    configured = profile.get("external_roots", {}).get("aether")
    return resolve_root("AETHER_ROOT", Path(configured) if configured else None, DEFAULT_AETHER_ROOT)


def get_wraith_root() -> Path:
    profile = load_runtime_profile()
    configured = profile.get("external_roots", {}).get("wraith")
    return resolve_root("WRAITH_ROOT", Path(configured) if configured else None, DEFAULT_WRAITH_ROOT)


def get_evo_root() -> Path:
    profile = load_runtime_profile()
    configured = profile.get("external_roots", {}).get("evo")
    return resolve_root("EVO_ROOT", Path(configured) if configured else None, DEFAULT_EVO_ROOT)


def get_appforge_root() -> Path:
    profile = load_runtime_profile()
    configured = profile.get("external_roots", {}).get("appforge")
    return resolve_root("APPFORGE_ROOT", Path(configured) if configured else None, DEFAULT_APPFORGE_ROOT)


def get_openclaw_root() -> Path:
    profile = load_runtime_profile()
    configured = profile.get("external_roots", {}).get("openclaw")
    return resolve_root("OPENCLAW_ROOT", Path(configured) if configured else None, DEFAULT_OPENCLAW_ROOT)


def get_aegis_root() -> Path:
    profile = load_runtime_profile()
    configured = profile.get("external_roots", {}).get("aegis")
    return resolve_root("AEGIS_ROOT", Path(configured) if configured else None, DEFAULT_AEGIS_ROOT)


def get_abo_root() -> Path:
    profile = load_runtime_profile()
    configured = profile.get("external_roots", {}).get("abo")
    return resolve_root("ABO_ROOT", Path(configured) if configured else None, DEFAULT_ABO_ROOT)


def get_aegis_mobile_root() -> Path:
    profile = load_runtime_profile()
    configured = profile.get("external_roots", {}).get("aegis_mobile")
    return resolve_root("AEGIS_MOBILE_ROOT", Path(configured) if configured else None, DEFAULT_AEGIS_MOBILE_ROOT)


def get_legacy_workspace_root() -> Path:
    profile = load_runtime_profile()
    external_roots = profile.get("external_roots", {})
    configured = external_roots.get("legacy_workspace") or external_roots.get("openclaw")
    env_override = os.getenv("OPENCHIMERA_LEGACY_ROOT") or os.getenv("OPENCLAW_ROOT")
    if env_override:
        return Path(env_override).expanduser()
    return resolve_root("OPENCHIMERA_LEGACY_ROOT", Path(configured) if configured else None, DEFAULT_LEGACY_WORKSPACE_ROOT)


def get_ascension_root() -> Path:
    return get_legacy_workspace_root()




def get_harness_repo_root() -> Path:
    configured = os.getenv("OPENCHIMERA_HARNESS_ROOT")
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.exists() and is_supported_harness_repo_root(candidate):
            return candidate
    profile = load_runtime_profile()
    profile_candidate = Path(str(profile.get("integration_roots", {}).get("harness_repo") or DEFAULT_HARNESS_REPO_ROOT)).expanduser()
    if profile_candidate.exists() and is_supported_harness_repo_root(profile_candidate):
        return profile_candidate
    return DEFAULT_HARNESS_REPO_ROOT


def get_legacy_harness_snapshot_root() -> Path:
    profile = load_runtime_profile()
    stored = profile.get("integration_roots", {}).get("legacy_harness_snapshot")
    return resolve_root(
        "OPENCHIMERA_LEGACY_HARNESS_ROOT",
        Path(stored).expanduser() if stored else None,
        DEFAULT_LEGACY_HARNESS_SNAPSHOT_ROOT,
    )


def get_minimind_root() -> Path:
    profile = load_runtime_profile()
    configured = profile.get("integration_roots", {}).get("minimind")
    return resolve_root("MINIMIND_ROOT", Path(configured) if configured else None, DEFAULT_MINIMIND_ROOT)


def get_minimind_python_executable() -> Path:
    env_override = os.getenv("OPENCHIMERA_MINIMIND_PYTHON")
    if env_override:
        return Path(env_override)
    profile = load_runtime_profile()
    configured = profile.get("local_runtime", {}).get("reasoning_engine_config", {}).get("python_executable")
    if configured:
        return Path(configured)
    candidate = get_legacy_workspace_root() / "venv" / "Scripts" / "python.exe"
    return candidate if candidate.exists() else Path(sys.executable)


def get_minimind_api_host() -> str:
    profile = load_runtime_profile()
    return str(profile.get("local_runtime", {}).get("reasoning_engine_config", {}).get("api_host", DEFAULT_PROVIDER_HOST))


def get_minimind_api_port() -> int:
    profile = load_runtime_profile()
    configured = profile.get("local_runtime", {}).get("reasoning_engine_config", {}).get("api_port", 8998)
    try:
        return int(configured)
    except (TypeError, ValueError):
        return 8998


def get_minimind_api_base_url() -> str:
    return f"http://{get_minimind_api_host()}:{get_minimind_api_port()}"


def get_provider_host() -> str:
    return os.getenv("OPENCHIMERA_HOST", DEFAULT_PROVIDER_HOST)


def get_provider_port() -> int:
    raw_port = os.getenv("OPENCHIMERA_PORT", str(DEFAULT_PROVIDER_PORT))
    try:
        return int(raw_port)
    except ValueError:
        return DEFAULT_PROVIDER_PORT


def get_provider_max_workers() -> int:
    raw = os.getenv("OPENCHIMERA_MAX_WORKERS", "").strip()
    try:
        value = int(raw)
        return max(1, value)
    except ValueError:
        return 32


def is_provider_tls_enabled() -> bool:
    env_enabled = os.getenv("OPENCHIMERA_TLS_ENABLED", "").strip().lower()
    if env_enabled:
        return env_enabled in {"1", "true", "yes", "on"}
    profile = load_runtime_profile()
    return bool(profile.get("api", {}).get("tls", {}).get("enabled", False))


def get_provider_tls_certfile() -> Path | None:
    env_value = os.getenv("OPENCHIMERA_TLS_CERTFILE", "").strip()
    if env_value:
        return Path(env_value).expanduser()
    profile = load_runtime_profile()
    configured = str(profile.get("api", {}).get("tls", {}).get("certfile", "")).strip()
    if configured:
        return Path(configured).expanduser()
    return None


def get_provider_tls_keyfile() -> Path | None:
    env_value = os.getenv("OPENCHIMERA_TLS_KEYFILE", "").strip()
    if env_value:
        return Path(env_value).expanduser()
    profile = load_runtime_profile()
    configured = str(profile.get("api", {}).get("tls", {}).get("keyfile", "")).strip()
    if configured:
        return Path(configured).expanduser()
    return None


def get_provider_tls_key_password() -> str | None:
    env_value = os.getenv("OPENCHIMERA_TLS_KEY_PASSWORD", "")
    if env_value:
        return env_value
    profile = load_runtime_profile()
    configured = str(profile.get("api", {}).get("tls", {}).get("key_password", ""))
    return configured or None


def get_provider_scheme() -> str:
    return "https" if is_provider_tls_enabled() else "http"


def get_provider_base_url() -> str:
    return f"{get_provider_scheme()}://{get_provider_host()}:{get_provider_port()}"


def get_api_auth_header() -> str:
    env_header = os.getenv("OPENCHIMERA_API_AUTH_HEADER")
    if env_header:
        return env_header
    profile = load_runtime_profile()
    return str(profile.get("api", {}).get("auth", {}).get("header", DEFAULT_API_AUTH_HEADER))


def get_api_auth_token() -> str:
    env_token = os.getenv("OPENCHIMERA_API_TOKEN")
    if env_token:
        return env_token
    profile = load_runtime_profile()
    return str(profile.get("api", {}).get("auth", {}).get("token", ""))


def get_api_admin_token() -> str:
    env_token = os.getenv("OPENCHIMERA_ADMIN_TOKEN")
    if env_token:
        return env_token
    profile = load_runtime_profile()
    configured = str(profile.get("api", {}).get("auth", {}).get("admin_token", ""))
    return configured or get_api_auth_token()


def is_api_auth_enabled() -> bool:
    env_token = os.getenv("OPENCHIMERA_API_TOKEN")
    if env_token:
        return True
    profile = load_runtime_profile()
    auth = profile.get("api", {}).get("auth", {})
    return bool(auth.get("enabled") and auth.get("token"))


def get_chimera_kb_path() -> Path:
    return ROOT / "chimera_kb.json"


def get_rag_storage_path() -> Path:
    return ROOT / "rag_storage.json"


def get_observability_recent_limit() -> int:
    configured = load_runtime_profile().get("observability", {}).get("recent_limit", 64)
    try:
        return max(1, int(configured))
    except (TypeError, ValueError):
        return 64


def get_observability_db_path() -> Path | None:
    override = os.getenv("OPENCHIMERA_OBSERVABILITY_DB", "").strip()
    if override:
        if override.lower() in {"0", "false", "off", "disabled", "none"}:
            return None
        return Path(override).expanduser()

    observability = load_runtime_profile().get("observability", {})
    persistence = observability.get("persistence", {}) if isinstance(observability, dict) else {}
    if not bool(persistence.get("enabled", True)):
        return None
    configured_path = persistence.get("path") or (ROOT / "data" / "observability.db")
    return Path(configured_path).expanduser()


def get_log_level() -> str:
    env_value = os.getenv("OPENCHIMERA_LOG_LEVEL", "").strip()
    if env_value:
        return env_value.upper()
    profile = load_runtime_profile()
    return str(profile.get("logging", {}).get("level", "INFO")).upper()


def get_structured_log_path() -> Path | None:
    env_enabled = os.getenv("OPENCHIMERA_STRUCTURED_LOG_ENABLED", "").strip().lower()
    if env_enabled in {"0", "false", "off", "disabled", "no"}:
        return None

    env_path = os.getenv("OPENCHIMERA_STRUCTURED_LOG_PATH", "").strip()
    if env_path:
        return Path(env_path).expanduser()

    profile = load_runtime_profile()
    logging_profile = profile.get("logging", {}) if isinstance(profile.get("logging", {}), dict) else {}
    structured = logging_profile.get("structured", {}) if isinstance(logging_profile.get("structured", {}), dict) else {}
    if not bool(structured.get("enabled", True)):
        return None
    configured_path = structured.get("path") or (ROOT / "logs" / "openchimera-runtime.jsonl")
    return Path(str(configured_path)).expanduser()


def get_runtime_mode() -> str:
    env_value = os.getenv("OPENCHIMERA_RUNTIME_MODE", "").strip().lower()
    if env_value:
        return env_value
    if os.getenv("KUBERNETES_SERVICE_HOST"):
        return "kubernetes"
    if os.getenv("OPENCHIMERA_CONTAINERIZED", "").strip().lower() in {"1", "true", "yes", "on"}:
        return "container"
    if os.getenv("DOTNET_RUNNING_IN_CONTAINER") or os.getenv("container"):
        return "container"
    if Path("/.dockerenv").exists():
        return "docker"
    if Path("/run/.containerenv").exists():
        return "container"
    return "local"


def build_deployment_status() -> dict[str, Any]:
    override_path = get_runtime_profile_override_path()
    structured_log_path = get_structured_log_path()
    observability_db_path = get_observability_db_path()
    certfile = get_provider_tls_certfile()
    keyfile = get_provider_tls_keyfile()
    mode = get_runtime_mode()
    return {
        "mode": mode,
        "containerized": mode in {"docker", "container", "kubernetes"},
        "base_url": get_provider_base_url(),
        "runtime_profile": {
            "path": str(get_runtime_profile_path()),
            "override_path": str(override_path),
            "override_active": override_path.exists(),
            "override_from_env": bool(os.getenv("OPENCHIMERA_RUNTIME_PROFILE", "").strip()),
        },
        "transport": {
            "scheme": get_provider_scheme(),
            "tls_enabled": is_provider_tls_enabled(),
            "cert_configured": certfile is not None,
            "key_configured": keyfile is not None,
        },
        "observability": {
            "persistence_enabled": observability_db_path is not None,
            "db_path": str(observability_db_path) if observability_db_path is not None else "",
        },
        "logging": {
            "level": get_log_level(),
            "structured_enabled": structured_log_path is not None,
            "structured_log_path": str(structured_log_path) if structured_log_path is not None else "",
        },
    }


def build_runtime_configuration_status() -> dict[str, Any]:
    profile = load_runtime_profile()
    deployment = build_deployment_status()
    override_path = get_runtime_profile_override_path()
    provider_host = get_provider_host()
    provider_port = get_provider_port()
    auth_enabled = is_api_auth_enabled()
    model_inventory = profile.get("model_inventory", {}) if isinstance(profile.get("model_inventory", {}), dict) else {}
    local_runtime = profile.get("local_runtime", {}) if isinstance(profile.get("local_runtime", {}), dict) else {}
    supervision = profile.get("supervision", {}) if isinstance(profile.get("supervision", {}), dict) else {}
    providers = profile.get("providers", {}) if isinstance(profile.get("providers", {}), dict) else {}
    return {
        "provider_url": get_provider_base_url(),
        "network": {
            "host": provider_host,
            "port": provider_port,
            "public_bind": not is_loopback_host(provider_host),
        },
        "profile_sources": {
            "default": str(get_runtime_profile_path()),
            "local_override": str(override_path),
            "local_override_exists": override_path.exists(),
            "local_override_from_env": bool(os.getenv("OPENCHIMERA_RUNTIME_PROFILE", "").strip()),
        },
        "auth": {
            "enabled": auth_enabled,
            "header": get_api_auth_header(),
            "user_token_configured": bool(get_api_auth_token()),
            "admin_token_configured": bool(get_api_admin_token()),
            "allow_insecure_bind": is_insecure_bind_allowed(),
        },
        "deployment": deployment,
        "providers": {
            "enabled": providers.get("enabled", []),
            "preferred_cloud_provider": providers.get("preferred_cloud_provider", ""),
            "prefer_free_models": bool(providers.get("prefer_free_models", False)),
            "failover_chain": list(providers.get("failover_chain", [])),
        },
        "local_runtime": {
            "mode": local_runtime.get("mode", "bootstrap-safe"),
            "context_length": int(local_runtime.get("context_length", 4096) or 4096),
            "models_dir": str(model_inventory.get("models_dir") or (ROOT / "models")),
        },
        "supervision": {
            "enabled": bool(supervision.get("enabled", True)),
            "interval_seconds": float(supervision.get("interval_seconds", 15) or 15),
            "restart_cooldown_seconds": float(supervision.get("restart_cooldown_seconds", 30) or 30),
        },
    }


def get_minimind_training_output_dir() -> Path:
    profile = load_runtime_profile()
    configured = (
        profile.get("reasoning_engine", {}).get("training_output_dir")
        or profile.get("local_runtime", {}).get("reasoning_engine_config", {}).get("training_output_dir")
    )
    if configured:
        return Path(configured)
    return ROOT / "data" / "minimind"


def _load_profile_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _merge_profile_overrides(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_profile_overrides(dict(merged[key]), value)
        else:
            merged[key] = value
    return merged


@lru_cache(maxsize=1)
def load_runtime_profile() -> dict[str, Any]:
    normalized, _ = normalize_runtime_profile(_load_profile_file(get_runtime_profile_path()))
    override_path = get_runtime_profile_override_path()
    if override_path.exists():
        normalized = _merge_profile_overrides(normalized, _load_profile_file(override_path))
        normalized, _ = normalize_runtime_profile(normalized)
    validation_errors = validate_runtime_profile(normalized)
    if validation_errors:
        raise ValueError("Invalid runtime profile: " + "; ".join(validation_errors))
    return normalized


def get_watch_files() -> list[str]:
    preferred = [
        ROOT / "README.md",
        get_chimera_kb_path(),
        get_rag_storage_path(),
        ROOT / "config" / "runtime_profile.json",
        ROOT / "memory" / "evo_memory.json",
    ]

    watch_files: list[str] = []
    for path in preferred:
        if path.exists():
            watch_files.append(str(path))
    return watch_files


def build_identity_snapshot() -> dict[str, Any]:
    runtime_profile = load_runtime_profile()
    hardware = runtime_profile.get("hardware", {})
    local_runtime = runtime_profile.get("local_runtime", {})
    model_inventory = runtime_profile.get("model_inventory", {})
    reasoning_engine = local_runtime.get("reasoning_engine", "unknown")
    supervision = runtime_profile.get("supervision", {})
    return {
        "root": str(ROOT),
        "provider_url": get_provider_base_url(),
        "watch_files": get_watch_files(),
        "hardware": hardware,
        "local_runtime": local_runtime,
        "reasoning_engine": reasoning_engine,
        "supervision": supervision,
        "launcher": local_runtime.get("launcher", {}),
        "model_inventory": model_inventory,
        "external_roots": {
            "aether": str(get_aether_root()),
            "wraith": str(get_wraith_root()),
            "evo": str(get_evo_root()),
            "legacy_workspace": str(get_legacy_workspace_root()),
            "openclaw": str(get_openclaw_root()),
            "aegis": str(get_aegis_root()),
            "ascension": str(get_ascension_root()),
        },
        "integration_roots": {
            "harness_repo": str(get_harness_repo_root()),
            "legacy_harness_snapshot": str(get_legacy_harness_snapshot_root()),
            "minimind": str(get_minimind_root()),
            "minimind_training_output": str(get_minimind_training_output_dir()),
        },
    }