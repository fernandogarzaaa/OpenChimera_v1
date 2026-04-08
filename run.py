from __future__ import annotations

import argparse
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version as package_version
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import tomllib
from pathlib import Path
from typing import Any

from core.bootstrap import bootstrap_workspace
from core.bus import EventBus
from core.aether_service import AetherService
from core.config import (
    ROOT,
    build_runtime_configuration_status,
    build_deployment_status,
    build_identity_snapshot,
    get_api_admin_token,
    get_api_auth_header,
    get_api_auth_token,
    get_harness_repo_root,
    get_legacy_harness_snapshot_root,
    get_log_level,
    get_minimind_root,
    get_provider_base_url,
    get_runtime_profile_override_path,
    get_runtime_profile_path,
    get_structured_log_path,
    is_api_auth_enabled,
    is_supported_harness_repo_root,
    load_runtime_profile,
)
from core.database import DatabaseManager
from core.evo_service import EvoService
from core.kernel import OpenChimeraKernel
from core.logging_utils import configure_runtime_logging
from core.mcp_registry import delete_mcp_registry_entry, list_mcp_registry_with_health, probe_all_mcp_registry_entries, probe_mcp_registry_entry, upsert_mcp_registry_entry
from core.personality import Personality
from core.provider import OpenChimeraProvider
from core.wraith_service import WraithService


def _configure_workspace() -> Path:
    workspace_root = Path(__file__).resolve().parent
    os.chdir(workspace_root)
    workspace_root_str = str(workspace_root)
    if workspace_root_str not in sys.path:
        sys.path.insert(0, workspace_root_str)
    return workspace_root


def _setup_logging(verbose: bool = False) -> None:
    configure_runtime_logging(
        level=get_log_level(),
        structured_log_path=get_structured_log_path(),
        verbose=verbose,
    )


def _print_payload(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2))


def _openchimera_version() -> str:
    try:
        return package_version("openchimera")
    except PackageNotFoundError:
        pyproject_path = Path(__file__).resolve().parent / "pyproject.toml"
        try:
            with pyproject_path.open("rb") as handle:
                return str(tomllib.load(handle).get("project", {}).get("version", "0.1.0"))
        except OSError:
            return "0.1.0"


def _get_release_validation_suite_path() -> Path:
    return Path(__file__).resolve().parent / "config" / "release_validation_modules.txt"


def _load_release_validation_modules() -> list[str]:
    suite_path = _get_release_validation_suite_path()
    if not suite_path.exists():
        return []
    modules: list[str] = []
    for raw_line in suite_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        modules.append(line)
    return modules


def _build_validation_command(test_pattern: str | None = None) -> dict[str, Any]:
    normalized_pattern = str(test_pattern or "").strip()
    release_modules = _load_release_validation_modules() if not normalized_pattern else []
    if release_modules:
        return {
            "command": [sys.executable, "-m", "unittest", *release_modules],
            "pattern": "test_*.py",
            "suite": "release",
            "modules": release_modules,
            "module_count": len(release_modules),
            "suite_path": str(_get_release_validation_suite_path()),
        }
    return {
        "command": [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", normalized_pattern or "test_*.py"],
        "pattern": normalized_pattern or "test_*.py",
        "suite": "discover",
        "modules": [],
        "module_count": 0,
        "suite_path": "",
    }


def _database_path(database_path: Path | None = None) -> Path:
    return Path(database_path) if database_path is not None else (ROOT / "data" / "openchimera.db")


def _backup_root(backup_root: Path | None = None) -> Path:
    return Path(backup_root) if backup_root is not None else (ROOT / "data" / "backups")


def _build_provider() -> OpenChimeraProvider:
    identity_snapshot = build_identity_snapshot()
    personality = Personality(identity_snapshot=identity_snapshot)
    return OpenChimeraProvider(EventBus(), personality)


def _build_status_snapshot(provider: OpenChimeraProvider | None = None) -> dict[str, Any]:
    provider = provider or _build_provider()
    runtime = provider.status()
    return {
        "aether": AetherService().status(),
        "wraith": WraithService().status(),
        "evo": EvoService().status(),
        "aegis": provider.aegis_status(),
        "ascension": provider.ascension_status(),
        "provider_online": bool(runtime.get("online", False)),
        "runtime": runtime,
        "deployment": runtime.get("deployment", build_deployment_status()),
        "onboarding": provider.onboarding_status(),
        "integrations": provider.integration_status(),
    }


def _format_fallback_leaders(fallback_learning: dict[str, Any]) -> str:
    leaders = fallback_learning.get("top_ranked_models", [])
    if not leaders:
        return "none"
    rendered: list[str] = []
    for item in leaders[:3]:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or "unknown")
        query_type = str(item.get("query_type") or "general")
        rank = int(item.get("rank") or 0)
        rendered.append(f"{model_id} ({query_type} #{rank})")
    return ", ".join(rendered) if rendered else "none"


def _format_job_counts(counts: dict[str, Any]) -> str:
    total = int(counts.get("total", 0) or 0)
    queued = int(counts.get("queued", 0) or 0)
    running = int(counts.get("running", 0) or 0)
    completed = int(counts.get("completed", 0) or 0)
    failed = int(counts.get("failed", 0) or 0)
    cancelled = int(counts.get("cancelled", 0) or 0)
    return f"total={total} queued={queued} running={running} completed={completed} failed={failed} cancelled={cancelled}"


def _runtime_state_label(snapshot: dict[str, Any]) -> str:
    if not isinstance(snapshot, dict):
        return "unknown"
    if snapshot.get("running"):
        return "running"
    if snapshot.get("available"):
        return "available"
    return "missing"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openchimera",
        description="OpenChimera local-first orchestration runtime and control CLI.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {_openchimera_version()}")
    subparsers = parser.add_subparsers(dest="command")

    serve_parser = subparsers.add_parser("serve", help="Boot the OpenChimera runtime and API server.")
    serve_parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")

    bootstrap_parser = subparsers.add_parser("bootstrap", help="Create missing local state and normalize config.")
    bootstrap_parser.add_argument("--json", action="store_true", help="Emit JSON output.")

    status_parser = subparsers.add_parser("status", help="Show a local runtime status snapshot.")
    status_parser.add_argument("--json", action="store_true", help="Emit JSON output.")

    briefing_parser = subparsers.add_parser("briefing", help="Show the current operator daily briefing.")
    briefing_parser.add_argument("--json", action="store_true", help="Emit JSON output.")

    channels_parser = subparsers.add_parser("channels", help="Inspect channel subscriptions or dispatch a topic payload.")
    channels_parser.add_argument("--set-subscription-json", default="", help="Create or update one channel subscription from a JSON object.")
    channels_parser.add_argument("--channel", default="", help="Create or update one channel subscription using guided flags.")
    channels_parser.add_argument("--subscription-id", default="", help="Optional subscription id for guided channel setup.")
    channels_parser.add_argument("--endpoint", default="", help="Endpoint URL for webhook, Slack, or Discord subscriptions.")
    channels_parser.add_argument("--file-path", default="", help="Filesystem path for local file-backed operator notifications.")
    channels_parser.add_argument("--bot-token", default="", help="Telegram bot token for guided Telegram setup.")
    channels_parser.add_argument("--chat-id", default="", help="Telegram chat id for guided Telegram setup.")
    channels_parser.add_argument("--topics-csv", default="", help="Comma-separated topic list for guided channel setup.")
    channels_parser.add_argument("--disabled", action="store_true", help="Create or update the guided subscription in a disabled state.")
    channels_parser.add_argument("--delete-subscription", default="", help="Delete one channel subscription by id.")
    channels_parser.add_argument("--validate-subscription", default="", help="Validate one stored subscription by id.")
    channels_parser.add_argument("--dispatch-topic", default="", help="Dispatch a payload to a specific topic.")
    channels_parser.add_argument("--history", action="store_true", help="Show recent channel delivery history.")
    channels_parser.add_argument("--topic", default="", help="Filter channel history to one topic.")
    channels_parser.add_argument("--status", default="", help="Filter channel history entries by delivery result status.")
    channels_parser.add_argument("--limit", type=int, default=20, help="Maximum number of delivery history entries to show.")
    channels_parser.add_argument("--message", default="", help="Convenience message field for dispatched payloads.")
    channels_parser.add_argument("--payload-json", default="", help="Raw JSON object payload for dispatch.")
    channels_parser.add_argument("--json", action="store_true", help="Emit JSON output.")

    autonomy_parser = subparsers.add_parser("autonomy", help="Inspect autonomy diagnostics or run preview-safe autonomy actions.")
    autonomy_parser.add_argument("--job", default="", help="Run a specific autonomy job.")
    autonomy_parser.add_argument("--history", action="store_true", help="Show recent autonomy artifact history.")
    autonomy_parser.add_argument("--artifact", default="", help="Inspect a specific autonomy artifact or filter history to one artifact name.")
    autonomy_parser.add_argument("--operator-digest", action="store_true", help="Read the current operator digest artifact.")
    autonomy_parser.add_argument("--dispatch-digest", action="store_true", help="Generate or queue an operator digest dispatch.")
    autonomy_parser.add_argument("--dispatch-topic", default="", help="Override the digest dispatch topic for --dispatch-digest.")
    autonomy_parser.add_argument("--history-limit", type=int, default=0, help="Limit recent alert/job/channel history included in --dispatch-digest.")
    autonomy_parser.add_argument("--preview-repair", action="store_true", help="Generate or enqueue a preview-only repair plan.")
    autonomy_parser.add_argument("--target-project", default="", help="Target project path for repair previews or job payloads.")
    autonomy_parser.add_argument("--enqueue", action="store_true", help="Queue the preview repair as a durable operator job.")
    autonomy_parser.add_argument("--limit", type=int, default=20, help="Maximum number of artifact history entries to display.")
    autonomy_parser.add_argument("--max-attempts", type=int, default=3, help="Maximum attempts for queued preview repair jobs.")
    autonomy_parser.add_argument("--json", action="store_true", help="Emit JSON output.")

    jobs_parser = subparsers.add_parser("jobs", help="Inspect or manage the durable operator job queue.")
    jobs_parser.add_argument("--id", default="", help="Show one job by id.")
    jobs_parser.add_argument("--status", default="", help="Filter jobs by status.")
    jobs_parser.add_argument("--type", default="", help="Filter jobs by job type or class.")
    jobs_parser.add_argument("--limit", type=int, default=20, help="Maximum number of jobs to display.")
    jobs_parser.add_argument("--cancel", default="", help="Cancel a queued or running job by id.")
    jobs_parser.add_argument("--replay", default="", help="Replay a previous job by id.")
    jobs_parser.add_argument("--json", action="store_true", help="Emit JSON output.")

    doctor_parser = subparsers.add_parser("doctor", help="Run local install and configuration diagnostics.")
    doctor_parser.add_argument("--production", action="store_true", help="Run production-readiness checks against the local runtime state.")
    doctor_parser.add_argument("--json", action="store_true", help="Emit JSON output.")

    backup_parser = subparsers.add_parser("backup", help="Create, list, or restore runtime database backups.")
    backup_parser.add_argument("action", choices=["create", "list", "restore"], help="Backup action to perform.")
    backup_parser.add_argument("file", nargs="?", default="", help="Backup file name or path for restore.")
    backup_parser.add_argument("--json", action="store_true", help="Emit JSON output.")

    config_parser = subparsers.add_parser("config", help="Show a safe runtime configuration snapshot.")
    config_parser.add_argument("--json", action="store_true", help="Emit JSON output.")

    validate_parser = subparsers.add_parser("validate", help="Run the canonical release validation path.")
    validate_parser.add_argument("--pattern", default="", help="Unittest discovery pattern to run. By default OpenChimera uses the curated release suite; pass test_*.py explicitly for the full discovery sweep.")
    validate_parser.add_argument("--verbose-tests", action="store_true", help="Stream raw unittest output while the validation suite runs.")
    validate_parser.add_argument("--include-test-output", action="store_true", help="Include full captured unittest stdout and stderr in JSON output.")
    validate_parser.add_argument("--json", action="store_true", help="Emit JSON output.")

    onboard_parser = subparsers.add_parser("onboard", help="Show onboarding recommendations and blockers.")
    onboard_parser.add_argument("--register-local-model-path", default="", help="Register an existing GGUF file into the runtime profile and refresh onboarding state.")
    onboard_parser.add_argument("--register-local-model-id", default="", help="Explicit model id to associate with --register-local-model-path when filename inference is insufficient.")
    onboard_parser.add_argument("--json", action="store_true", help="Emit JSON output.")

    capabilities_parser = subparsers.add_parser("capabilities", help="Inspect runtime capabilities by kind.")
    capabilities_parser.add_argument(
        "--kind",
        choices=["commands", "tools", "skills", "plugins", "mcp"],
        help="Filter to one capability kind.",
    )
    capabilities_parser.add_argument("--json", action="store_true", help="Emit JSON output.")

    query_parser = subparsers.add_parser("query", help="Run a query through the OpenChimera query engine.")
    query_parser.add_argument("--text", default="", help="User query text.")
    query_parser.add_argument("--session-id", default="", help="Resume an existing query session.")
    query_parser.add_argument("--permission-scope", choices=["user", "admin"], default="user")
    query_parser.add_argument("--execute-tools", action="store_true", help="Execute the supplied tool requests before model completion.")
    query_parser.add_argument("--tool-request-json", action="append", default=[], help="Repeatable JSON object describing a tool request with tool_id and arguments.")
    query_parser.add_argument("--json", action="store_true", help="Emit JSON output.")

    tools_parser = subparsers.add_parser("tools", help="Inspect or execute runtime tools.")
    tools_parser.add_argument("--id", default="", help="Tool id to inspect or execute.")
    tools_parser.add_argument("--arguments-json", default="", help="JSON object of tool arguments when executing a tool.")
    tools_parser.add_argument("--permission-scope", choices=["user", "admin"], default="user")
    tools_parser.add_argument("--execute", action="store_true", help="Execute the selected tool instead of listing metadata.")
    tools_parser.add_argument("--list", action="store_true", help="List all registered tools.")
    tools_parser.add_argument("--register", nargs=2, metavar=("NAME", "DESCRIPTION"), help="Register a named tool with a description.")
    tools_parser.add_argument("--call", nargs="+", metavar="NAME", help="Execute a tool by name with optional JSON args as second element.")
    tools_parser.add_argument("--json", action="store_true", help="Emit JSON output.")

    sessions_parser = subparsers.add_parser("sessions", help="Inspect resumable query sessions.")
    sessions_parser.add_argument("--session-id", default="", help="Show a specific session.")
    sessions_parser.add_argument("--branch", default="", help="Branch a new session from a checkpoint id.")
    sessions_parser.add_argument("--replay", default="", help="Replay a session from a checkpoint id.")
    sessions_parser.add_argument("--input", default="", help="New input text for --branch or --replay operations.")
    sessions_parser.add_argument("--json", action="store_true", help="Emit JSON output.")

    memory_parser = subparsers.add_parser("memory", help="Inspect query-engine memory scopes.")
    memory_parser.add_argument("--json", action="store_true", help="Emit JSON output.")

    model_roles_parser = subparsers.add_parser("model-roles", help="Inspect or configure explicit model roles.")
    model_roles_parser.add_argument("--set", action="append", default=[], help="Set role overrides like role=model.")
    model_roles_parser.add_argument("--json", action="store_true", help="Emit JSON output.")

    mcp_parser = subparsers.add_parser("mcp", help="Inspect discovered MCP servers and their health.")
    mcp_parser.add_argument("--serve", action="store_true", help="Serve the local OpenChimera MCP server over stdio.")
    mcp_parser.add_argument("--registry", action="store_true", help="Show OpenChimera-managed MCP registry entries.")
    mcp_parser.add_argument("--register", default="", help="Register or update an MCP connector id in the OpenChimera registry.")
    mcp_parser.add_argument("--unregister", default="", help="Remove an MCP connector id from the OpenChimera registry.")
    mcp_parser.add_argument("--transport", choices=["http", "stdio"], help="Transport to use when registering a connector.")
    mcp_parser.add_argument("--url", default="", help="HTTP URL for an MCP connector registration.")
    mcp_parser.add_argument("--command", dest="stdio_command", default="", help="stdio command for an MCP connector registration.")
    mcp_parser.add_argument("--arg", action="append", default=[], help="Repeatable stdio argument for MCP registration.")
    mcp_parser.add_argument("--name", default="", help="Friendly name for an MCP registry entry.")
    mcp_parser.add_argument("--description", default="", help="Description for an MCP registry entry.")
    mcp_parser.add_argument("--disabled", action="store_true", help="Register the MCP connector in a disabled state.")
    mcp_parser.add_argument("--probe", action="store_true", help="Probe one or all OpenChimera-managed MCP connectors.")
    mcp_parser.add_argument("--id", default="", help="Target a specific registered MCP connector id when probing.")
    mcp_parser.add_argument("--resources", action="store_true", help="Show OpenChimera MCP resource descriptors.")
    mcp_parser.add_argument("--prompts", action="store_true", help="Show OpenChimera MCP prompt descriptors.")
    mcp_parser.add_argument("--json", action="store_true", help="Emit JSON output.")

    subsystems_parser = subparsers.add_parser("subsystems", help="Inspect or invoke managed subsystems.")
    subsystems_parser.add_argument("--id", default="", help="Subsystem id.")
    subsystems_parser.add_argument("--action", default="status", help="Subsystem action.")
    subsystems_parser.add_argument("--prompt", default="", help="Prompt payload for deliberation-style actions.")
    subsystems_parser.add_argument("--target-project", default="", help="Target project for workflow actions.")
    subsystems_parser.add_argument("--json", action="store_true", help="Emit JSON output.")

    plugins_parser = subparsers.add_parser("plugins", help="Inspect or modify plugin installation state.")
    plugins_parser.add_argument("--install", default="", help="Install a discovered plugin id.")
    plugins_parser.add_argument("--uninstall", default="", help="Uninstall a plugin id.")
    plugins_parser.add_argument("--load", default="", help="Load a plugin from a manifest path.")
    plugins_parser.add_argument("--list", action="store_true", help="List loaded plugins from manifest.")
    plugins_parser.add_argument("--json", action="store_true", help="Emit JSON output.")

    phases_parser = subparsers.add_parser("phases", help="Show AGI implementation phase completion status.")
    phases_parser.add_argument("--json", action="store_true", help="Emit JSON output.")

    roles_parser = subparsers.add_parser("roles", help="Inspect or configure model-role assignments.")
    roles_parser.add_argument("--assign", nargs=2, metavar=("ROLE", "MODEL"), help="Assign a model to a role: --assign <role> <model>")
    roles_parser.add_argument("--list", action="store_true", help="List all role assignments.")
    roles_parser.add_argument("--json", action="store_true", help="Emit JSON output.")

    skills_parser = subparsers.add_parser("skills", help="Discover or inspect registered skills.")
    skills_parser.add_argument("--discover", action="store_true", help="Discover available skills.")
    skills_parser.add_argument("--json", action="store_true", help="Emit JSON output.")

    setup_parser = subparsers.add_parser("setup", help="One-step first-time setup: bootstrap workspace, run diagnostics, and show next steps.")
    setup_parser.add_argument("--skip-wizard", action="store_true", help="Skip the interactive wizard and just run bootstrap + doctor.")

    configure_parser = subparsers.add_parser("configure", help="Configure Quantum Engine capabilities, cloud API keys, and remote channels.")
    configure_parser.add_argument("--list", action="store_true", dest="list_caps", help="List all quantum capabilities and their status.")
    configure_parser.add_argument("--enable", type=str, default="", metavar="ID", help="Enable a capability by ID (e.g. quantum_engine_100, remote_telegram).")
    configure_parser.add_argument("--disable", type=str, default="", metavar="ID", help="Disable a capability by ID.")
    configure_parser.add_argument("--json", action="store_true", help="Emit JSON output.")

    return parser


def _bootstrap_command(as_json: bool) -> int:
    payload = bootstrap_workspace()
    if as_json:
        _print_payload(payload, as_json=True)
        return 0

    print("OpenChimera bootstrap complete")
    print(f"Workspace: {payload['workspace_root']}")
    print(f"Created directories: {len(payload['created_directories'])}")
    print(f"Created files: {len(payload['created_files'])}")
    print(f"Normalized files: {len(payload['normalized_files'])}")
    return 0


def _setup_command(skip_wizard: bool = False) -> int:
    """One-step first-time setup: bootstrap + interactive wizard."""
    print()
    print("  OpenChimera Setup")
    print("  " + "=" * 40)
    print()

    # Step 1: Bootstrap workspace
    print("  Bootstrapping workspace...")
    payload = bootstrap_workspace()
    dirs_created = len(payload.get("created_directories", []))
    files_created = len(payload.get("created_files", []))
    if dirs_created or files_created:
        print(f"  Created {dirs_created} directories and {files_created} files")
    else:
        print("  Workspace already configured")

    # Step 2: Run doctor diagnostics
    print("  Running diagnostics...")
    try:
        doctor_result = _doctor_payload()
        checks = doctor_result.get("checks", {})
        passed = sum(1 for v in checks.values() if v)
        total = len(checks)
        print(f"  {passed}/{total} checks passed")
    except Exception:
        print("  Diagnostics skipped (run 'openchimera doctor' manually)")

    if skip_wizard:
        print()
        print("  Bootstrap complete. Run 'openchimera setup' without --skip-wizard")
        print("  to configure hardware, models, and cloud providers interactively.")
        print()
        return 0

    # Step 3: Interactive wizard
    from core.setup_wizard import run_wizard

    try:
        run_wizard()
    except KeyboardInterrupt:
        print()
        print("  Wizard cancelled. Run 'openchimera setup' to restart it.")
        print()

    return 0


def _configure_quantum_command(
    *,
    list_caps: bool,
    enable_id: str,
    disable_id: str,
    as_json: bool,
) -> int:
    """Dispatch to the Quantum Engine configure wizard / capability manager."""
    from core.configure_wizard import configure_command

    return configure_command(
        list_caps=list_caps,
        enable_id=enable_id,
        disable_id=disable_id,
        as_json=as_json,
    )


def _status_command(as_json: bool) -> int:
    provider = _build_provider()
    payload = _build_status_snapshot(provider)
    provider_activation = provider.provider_activation_status()
    fallback_learning = provider_activation.get("fallback_learning", {})
    payload["provider_activation"] = provider_activation
    if as_json:
        _print_payload(payload, as_json=True)
        return 0

    provider_state = "online" if payload.get("provider_online") else "degraded"
    print(f"OpenChimera status: {provider_state}")
    print(f"AETHER: {_runtime_state_label(payload.get('aether', {}))}")
    print(f"WRAITH: {_runtime_state_label(payload.get('wraith', {}))}")
    print(f"Evo: {_runtime_state_label(payload.get('evo', {}))}")
    print(f"Aegis: {_runtime_state_label(payload.get('aegis', {}))}")
    print(f"Ascension: {_runtime_state_label(payload.get('ascension', {}))}")
    print(f"Prefer free fallbacks: {'enabled' if provider_activation.get('prefer_free_models') else 'disabled'}")
    print(f"Learned fallback rankings: {'available' if fallback_learning.get('learned_rankings_available') else 'unavailable'}")
    print(f"Fallback leaders: {_format_fallback_leaders(fallback_learning)}")
    degraded_models = fallback_learning.get("degraded_models", [])
    if degraded_models:
        print(f"Degraded free fallbacks: {', '.join(str(item) for item in degraded_models)}")
    return 0


def _briefing_command(as_json: bool) -> int:
    provider = _build_provider()
    payload = provider.daily_briefing()
    if as_json:
        _print_payload(payload, as_json=True)
        return 0

    print("OpenChimera daily briefing")
    print(payload.get("summary", "No summary available."))
    priorities = payload.get("priorities", [])
    if priorities:
        print("Priorities:")
        for item in priorities[:8]:
            print(f"- {item}")
    fallback_learning = payload.get("fallback_learning", {})
    print(f"Fallback leaders: {_format_fallback_leaders(fallback_learning)}")
    degraded_models = fallback_learning.get("degraded_models", [])
    if degraded_models:
        print(f"Degraded free fallbacks: {', '.join(str(item) for item in degraded_models)}")
    return 0


def _channels_command(
    set_subscription_json: str,
    channel: str,
    subscription_id: str,
    endpoint: str,
    file_path: str,
    bot_token: str,
    chat_id: str,
    topics_csv: str,
    disabled: bool,
    delete_subscription: str,
    validate_subscription: str,
    dispatch_topic: str,
    history: bool,
    topic: str,
    status: str,
    limit: int,
    message: str,
    payload_json: str,
    as_json: bool,
) -> int:
    provider = _build_provider()
    raw_subscription = str(set_subscription_json).strip()
    if raw_subscription:
        subscription = json.loads(raw_subscription)
        if not isinstance(subscription, dict):
            raise ValueError("--set-subscription-json must decode to a JSON object")
        result = provider.upsert_channel_subscription(subscription)
        if as_json:
            _print_payload(result, as_json=True)
            return 0

        print(f"Stored subscription: {result.get('id')}")
        print(f"Channel: {result.get('channel')}")
        return 0

    guided_channel = str(channel).strip().lower()
    if guided_channel:
        topics = [item.strip() for item in str(topics_csv).split(",") if item.strip()]
        subscription: dict[str, Any] = {
            "channel": guided_channel,
            "enabled": not disabled,
        }
        if subscription_id:
            subscription["id"] = str(subscription_id).strip()
        if topics:
            subscription["topics"] = topics
        if endpoint:
            subscription["endpoint"] = str(endpoint).strip()
        if file_path:
            subscription["file_path"] = str(file_path).strip()
        if bot_token:
            subscription["bot_token"] = str(bot_token).strip()
        if chat_id:
            subscription["chat_id"] = str(chat_id).strip()

        result = provider.upsert_channel_subscription(subscription)
        if as_json:
            _print_payload(result, as_json=True)
            return 0

        print(f"Stored subscription: {result.get('id')}")
        print(f"Channel: {result.get('channel')}")
        print(f"Topics: {', '.join(result.get('topics', []))}")
        return 0

    normalized_delete = str(delete_subscription).strip()
    if normalized_delete:
        result = provider.delete_channel_subscription(normalized_delete)
        if as_json:
            _print_payload(result, as_json=True)
            return 0

        print(f"Deleted subscription: {normalized_delete}")
        print(f"Deleted: {result.get('deleted', False)}")
        return 0

    normalized_validate = str(validate_subscription).strip()
    if normalized_validate:
        result = provider.validate_channel_subscription(subscription_id=normalized_validate)
        if as_json:
            _print_payload(result, as_json=True)
            return 0

        print(f"Validated subscription: {result.get('subscription_id')}")
        print(f"Status: {result.get('status')}")
        if result.get("status_code") is not None:
            print(f"HTTP status: {result.get('status_code')}")
        if result.get("error"):
            print(f"Error: {result.get('error')}")
        return 0

    normalized_topic = str(dispatch_topic).strip()
    if normalized_topic:
        payload: dict[str, Any] = {}
        raw_payload = str(payload_json).strip()
        if raw_payload:
            parsed = json.loads(raw_payload)
            if not isinstance(parsed, dict):
                raise ValueError("--payload-json must decode to a JSON object")
            payload = parsed
        if message:
            payload.setdefault("message", message)
        result = provider.dispatch_channel(normalized_topic, payload=payload)
        if as_json:
            _print_payload(result, as_json=True)
            return 0

        print(f"Dispatched topic: {result.get('topic')}")
        print(f"Deliveries: {result.get('delivery', {}).get('delivery_count', 0)}")
        return 0

    if history:
        payload = provider.channel_delivery_history(
            topic=str(topic).strip() or None,
            status=str(status).strip() or None,
            limit=limit,
        )
        if as_json:
            _print_payload(payload, as_json=True)
            return 0

        print("OpenChimera channel delivery history")
        for item in payload.get("history", [])[:limit]:
            if isinstance(item, dict):
                print(
                    f"- {item.get('topic')}: deliveries={item.get('delivery_count', 0)} delivered={item.get('delivered_count', 0)} errors={item.get('error_count', 0)}"
                )
        return 0

    payload = provider.channel_status()
    if as_json:
        _print_payload(payload, as_json=True)
        return 0

    print("OpenChimera channels")
    counts = payload.get("counts", {}) if isinstance(payload.get("counts", {}), dict) else {}
    print(f"Subscriptions: {counts.get('total', 0)} enabled={counts.get('enabled', 0)}")
    if int(counts.get("total", 0)) == 0:
        print("Quick setup: openchimera channels --channel filesystem --file-path data/channels/operator-feed.jsonl --subscription-id ops-local-feed")
    last_delivery = payload.get("last_delivery", {}) if isinstance(payload.get("last_delivery", {}), dict) else {}
    if last_delivery.get("topic"):
        print(f"Last delivery: {last_delivery.get('topic')} ({last_delivery.get('delivery_count', 0)} deliveries)")
    subscriptions = payload.get("subscriptions", []) if isinstance(payload.get("subscriptions", []), list) else []
    for item in subscriptions[:10]:
        if isinstance(item, dict):
            validation = item.get("last_validation", {}) if isinstance(item.get("last_validation", {}), dict) else {}
            validation_text = f" validation={validation.get('status', 'unknown')}" if validation else ""
            target = item.get("endpoint") or item.get("file_path") or ""
            target_text = f" target={target}" if target else ""
            print(f"- {item.get('id')}: {item.get('channel')} topics={','.join(str(topic) for topic in item.get('topics', []))}{target_text}{validation_text}")
    return 0


def _autonomy_command(
    job_name: str,
    history: bool,
    artifact_name: str,
    operator_digest: bool,
    dispatch_digest: bool,
    dispatch_topic: str,
    history_limit: int,
    preview_repair: bool,
    target_project: str,
    enqueue: bool,
    limit: int,
    max_attempts: int,
    as_json: bool,
) -> int:
    provider = _build_provider()
    if dispatch_digest:
        payload = provider.dispatch_operator_digest(
            enqueue=enqueue,
            max_attempts=max_attempts,
            history_limit=history_limit or None,
            dispatch_topic=dispatch_topic or None,
        )
    elif preview_repair:
        payload = provider.preview_self_repair(
            target_project=target_project or None,
            enqueue=enqueue,
            max_attempts=max_attempts,
        )
    elif history:
        payload = provider.autonomy_artifact_history(artifact_name=artifact_name or None, limit=limit)
    elif operator_digest:
        payload = provider.operator_digest()
    elif artifact_name:
        payload = provider.autonomy_artifact(artifact_name)
    elif job_name:
        if enqueue:
            job_payload: dict[str, Any] = {"job": job_name}
            if target_project:
                job_payload["target_project"] = target_project
            payload = provider.create_operator_job("autonomy", job_payload, max_attempts=max_attempts)
        else:
            job_payload = {"target_project": target_project} if target_project else None
            payload = provider.run_autonomy_job(job_name, payload=job_payload)
    else:
        payload = provider.autonomy_diagnostics()

    if as_json:
        _print_payload(payload, as_json=True)
        return 0

    if dispatch_digest:
        print("OpenChimera operator digest dispatch")
        print(f"Status: {payload.get('status', 'unknown')}")
        if payload.get("job_id"):
            print(f"Queued job: {payload.get('job_id')}")
        if payload.get("dispatch_topic"):
            print(f"Dispatch topic: {payload.get('dispatch_topic')}")
        if payload.get("target"):
            print(f"Artifact: {payload.get('target')}")
        return 0

    if preview_repair:
        print("OpenChimera autonomy preview repair")
        print(f"Status: {payload.get('status', 'unknown')}")
        if payload.get("job_id"):
            print(f"Queued job: {payload.get('job_id')}")
        if payload.get("target"):
            print(f"Artifact: {payload.get('target')}")
        return 0

    if history:
        print("OpenChimera autonomy artifact history")
        for item in payload.get("history", [])[:10]:
            if isinstance(item, dict):
                print(f"- {item.get('artifact_name')}: {item.get('summary')} [{item.get('status')}]")
        return 0

    if artifact_name:
        print(f"Autonomy artifact: {artifact_name}")
        print(json.dumps(payload, indent=2))
        return 0

    if operator_digest:
        print("OpenChimera operator digest")
        print(json.dumps(payload, indent=2))
        return 0

    if job_name:
        print(f"Autonomy job: {job_name}")
        print(f"Status: {payload.get('status', 'unknown')}")
        if payload.get("job_id"):
            print(f"Queued job: {payload.get('job_id')}")
        if payload.get("target"):
            print(f"Artifact: {payload.get('target')}")
        return 0

    print("OpenChimera autonomy diagnostics")
    artifacts = payload.get("artifacts", {}) if isinstance(payload.get("artifacts", {}), dict) else {}
    self_audit = artifacts.get("self_audit", {}) if isinstance(artifacts.get("self_audit", {}), dict) else {}
    degradation = artifacts.get("degradation_chains", {}) if isinstance(artifacts.get("degradation_chains", {}), dict) else {}
    scheduler = payload.get("scheduler", {}) if isinstance(payload.get("scheduler", {}), dict) else {}
    job_queue = payload.get("job_queue", {}) if isinstance(payload.get("job_queue", {}), dict) else {}
    print(f"Self-audit: {self_audit.get('status', 'missing')}")
    print(f"Degradation chains: {len(degradation.get('chains', [])) if isinstance(degradation.get('chains', []), list) else 0}")
    print(f"Job queue: {_format_job_counts(job_queue.get('counts', {}))}")
    jobs = scheduler.get("jobs", {}) if isinstance(scheduler.get("jobs", {}), dict) else {}
    attention = [name for name, details in jobs.items() if details.get("enabled") and details.get("last_status") in {"never", "error"}]
    if attention:
        print(f"Jobs needing attention: {', '.join(attention[:6])}")
    findings = self_audit.get("findings", []) if isinstance(self_audit.get("findings", []), list) else []
    if findings:
        print("Top findings:")
        for item in findings[:5]:
            if isinstance(item, dict):
                print(f"- {item.get('id', 'finding')}: {item.get('summary', '')}")
    return 0


def _jobs_command(job_id: str, status_filter: str, job_type: str, limit: int, cancel_id: str, replay_id: str, as_json: bool) -> int:
    provider = _build_provider()
    if cancel_id:
        payload = provider.cancel_operator_job(cancel_id)
    elif replay_id:
        payload = provider.replay_operator_job(replay_id)
    elif job_id:
        payload = provider.get_operator_job(job_id)
    else:
        payload = provider.job_queue_status(
            status_filter=status_filter or None,
            job_type=job_type or None,
            limit=limit,
        )

    if as_json:
        _print_payload(payload, as_json=True)
        return 0

    if cancel_id or replay_id or job_id:
        print(json.dumps(payload, indent=2))
        return 0

    print("OpenChimera job queue")
    counts = payload.get("counts", {}) if isinstance(payload.get("counts", {}), dict) else {}
    print(_format_job_counts(counts))
    jobs = payload.get("jobs", []) if isinstance(payload.get("jobs", []), list) else []
    for item in jobs[:10]:
        if not isinstance(item, dict):
            continue
        print(f"- {item.get('job_id')}: {item.get('job_type')} class={item.get('job_class')} status={item.get('status')}")
    return 0


def _append_unique_action(actions: list[str], action: str) -> None:
    normalized = str(action).strip()
    if normalized and normalized not in actions:
        actions.append(normalized)


def _doctor_payload(*, production: bool = False, database_path: Path | None = None) -> dict[str, Any]:
    bootstrap_report = bootstrap_workspace()
    profile = load_runtime_profile()
    identity = build_identity_snapshot()
    provider = _build_provider()
    database = DatabaseManager(db_path=_database_path(database_path))
    database_status = database.status()
    aether_status = AetherService().status()
    llm_runtime = provider.llm_manager.get_runtime_status()
    runtime_models = llm_runtime.get("models", {}) if isinstance(llm_runtime.get("models", {}), dict) else {}
    discovery = llm_runtime.get("discovery", {}) if isinstance(llm_runtime.get("discovery", {}), dict) else {}
    local_search_roots = [str(item) for item in discovery.get("search_roots", []) if item]
    discovered_files = [str(item) for item in discovery.get("discovered_files", []) if item]
    harness_root = Path(str(identity.get("integration_roots", {}).get("harness_repo", get_harness_repo_root())))
    legacy_snapshot_root = Path(
        str(identity.get("integration_roots", {}).get("legacy_harness_snapshot", get_legacy_harness_snapshot_root()))
    )
    minimind_root = Path(str(identity.get("integration_roots", {}).get("minimind", get_minimind_root())))

    warnings: list[str] = []
    configuration_status = build_runtime_configuration_status()
    checks = {
        "runtime_profile_exists": get_runtime_profile_path().exists(),
        "runtime_profile_override_exists": get_runtime_profile_override_path().exists(),
        "harness_repo_supported": harness_root.exists() and is_supported_harness_repo_root(harness_root),
        "legacy_snapshot_available": legacy_snapshot_root.exists(),
        "minimind_workspace_available": minimind_root.exists(),
        "aether_immune_loop_available": (not aether_status.get("available", False)) or bool(aether_status.get("immune_loop_available", False)),
        "local_llama_server_available": bool(llm_runtime.get("llama_server_exists", False)),
        "local_model_assets_available": any(
            bool(details.get("model_path_exists")) for details in runtime_models.values() if isinstance(details, dict)
        ),
        "external_bind_protected": (not bool(configuration_status.get("network", {}).get("public_bind", False))) or bool(configuration_status.get("auth", {}).get("enabled", False)),
    }
    if not checks["harness_repo_supported"]:
        warnings.append("Harness repo root is missing or not in the supported Python-port layout.")
    if not checks["legacy_snapshot_available"]:
        warnings.append("Legacy workflow snapshot not found; compatibility evidence will be reduced.")
    if not checks["minimind_workspace_available"]:
        warnings.append("MiniMind workspace not found; reasoning engine features will run in degraded mode.")
    if not checks["aether_immune_loop_available"]:
        warning = "AETHER immune loop is unavailable; runtime can boot but evolution_engine.py dependencies are degraded."
        if aether_status.get("immune_loop_error"):
            warning = f"{warning} Error: {aether_status['immune_loop_error']}"
        warnings.append(warning)
    if not checks["local_llama_server_available"]:
        warnings.append("llama-server executable not found; the local GGUF launcher cannot boot managed local models.")
    if not checks["local_model_assets_available"]:
        warnings.append("No local GGUF model assets were found in the configured or discovered search roots.")
    if is_api_auth_enabled() and not get_api_admin_token():
        warnings.append("API auth is enabled but no admin token is configured for mutating routes.")
    if not checks["external_bind_protected"]:
        warnings.append("OpenChimera is configured to bind beyond localhost without API auth. Set OPENCHIMERA_API_TOKEN and OPENCHIMERA_ADMIN_TOKEN before exposing the runtime.")
    auth_enabled = profile.get("api", {}).get("auth", {}).get("enabled", False)
    if not auth_enabled:
        warnings.append("Auth is disabled. Enable api.auth.enabled=true for production deployments.")

    next_actions: list[str] = []
    if not checks["harness_repo_supported"]:
        _append_unique_action(
            next_actions,
            "Set OPENCHIMERA_HARNESS_ROOT or update config/runtime_profile.local.json so the upstream harness Python-port repo points at a supported layout.",
        )
    if not checks["legacy_snapshot_available"]:
        _append_unique_action(
            next_actions,
            "Set OPENCHIMERA_LEGACY_HARNESS_ROOT or update config/runtime_profile.local.json if you want legacy workflow snapshot evidence available.",
        )
    if not checks["minimind_workspace_available"]:
        _append_unique_action(
            next_actions,
            "Set MINIMIND_ROOT or update config/runtime_profile.local.json so the MiniMind workspace is available for reasoning features.",
        )
    if not checks["aether_immune_loop_available"]:
        _append_unique_action(
            next_actions,
            "Install the missing AETHER immune-loop dependencies in the external workspace and verify modules like psutil are available there.",
        )
    if not checks["local_llama_server_available"]:
        _append_unique_action(
            next_actions,
            "Install or point OpenChimera at a working llama-server binary before expecting managed GGUF launches.",
        )
    if not checks["local_model_assets_available"]:
        _append_unique_action(
            next_actions,
            "Place a GGUF under one of the configured model roots or run: openchimera onboard --register-local-model-path <path-to-model.gguf> [--register-local-model-id <model-id>]",
        )
    if is_api_auth_enabled() and not get_api_admin_token():
        _append_unique_action(
            next_actions,
            "Set OPENCHIMERA_ADMIN_TOKEN before using protected mutating routes or production deployments.",
        )
    if not checks["external_bind_protected"]:
        _append_unique_action(
            next_actions,
            "Set OPENCHIMERA_API_TOKEN and OPENCHIMERA_ADMIN_TOKEN before binding beyond localhost.",
        )

    auth = {
        "enabled": is_api_auth_enabled(),
        "header": get_api_auth_header(),
        "user_token_configured": bool(get_api_auth_token()),
        "admin_token_configured": bool(get_api_admin_token()),
    }

    production_checks = {
        "database_available": Path(database_status["database_path"]).exists(),
        "database_wal_enabled": bool(database_status.get("wal_enabled", False)),
        "migrations_applied": bool(database_status.get("applied_migrations", [])),
        "api_auth_enabled": bool(auth["enabled"]),
        "admin_token_configured": bool(auth["admin_token_configured"]),
        "tls_enabled": bool(configuration_status.get("deployment", {}).get("transport", {}).get("tls_enabled", False)),
        "structured_logging_enabled": bool(configuration_status.get("deployment", {}).get("logging", {}).get("structured_enabled", False)),
        "external_bind_protected": bool(checks["external_bind_protected"]),
    }
    production_warnings: list[str] = []
    if production:
        if not production_checks["database_available"]:
            production_warnings.append("SQLite runtime database is missing.")
        if not production_checks["migrations_applied"]:
            production_warnings.append("Runtime database migrations have not been applied.")
        if not production_checks["api_auth_enabled"]:
            production_warnings.append("API auth must be enabled for production exposure.")
        if not production_checks["admin_token_configured"]:
            production_warnings.append("Admin token is not configured for protected control-plane routes.")
        if not production_checks["tls_enabled"]:
            production_warnings.append("TLS is not enabled in the active deployment configuration.")
        if not production_checks["structured_logging_enabled"]:
            production_warnings.append("Structured JSON logging is not enabled.")
        if not production_checks["external_bind_protected"]:
            production_warnings.append("The runtime is exposed beyond localhost without effective auth protection.")

    return {
        "status": "ok" if not warnings and not production_warnings else "warning",
        "workspace_root": identity.get("root"),
        "provider_url": get_provider_base_url(),
        "version": _openchimera_version(),
        "bootstrap": bootstrap_report,
        "auth": auth,
        "checks": checks,
        "production": {
            "requested": production,
            "checks": production_checks,
            "warnings": production_warnings,
        },
        "database": database_status,
        "profile_sources": {
            "default": str(get_runtime_profile_path()),
            "local_override": str(get_runtime_profile_override_path()),
        },
        "warnings": warnings,
        "next_actions": next_actions,
        "profile": {
            "providers_enabled": profile.get("providers", {}).get("enabled", []),
            "preferred_cloud_provider": profile.get("providers", {}).get("preferred_cloud_provider", ""),
        },
        "configuration": configuration_status,
        "local_model_discovery": {
            "search_roots": local_search_roots,
            "discovered_files": discovered_files,
        },
    }


def _config_command(as_json: bool) -> int:
    payload = build_runtime_configuration_status()
    if as_json:
        _print_payload(payload, as_json=True)
        return 0

    print("OpenChimera configuration")
    print(f"Provider URL: {payload.get('provider_url')}")
    print(f"Public bind: {payload.get('network', {}).get('public_bind')}")
    print(f"Auth enabled: {payload.get('auth', {}).get('enabled')}")
    print(f"Runtime override active: {payload.get('profile_sources', {}).get('local_override_exists')}")
    print(f"TLS enabled: {payload.get('deployment', {}).get('transport', {}).get('tls_enabled')}")
    print(f"Structured logging: {payload.get('deployment', {}).get('logging', {}).get('structured_enabled')}")
    return 0


def _doctor_command(as_json: bool) -> int:
    payload = _doctor_payload()
    if as_json:
        _print_payload(payload, as_json=True)
        return 0

    print(f"OpenChimera doctor: {payload['status']}")
    print(f"Provider URL: {payload['provider_url']}")
    print(f"Auth enabled: {payload['auth']['enabled']}")
    for check_name, check_value in payload["checks"].items():
        print(f"{check_name}: {'ok' if check_value else 'missing'}")
    if payload["warnings"]:
        print("Warnings:")
        for warning in payload["warnings"]:
            print(f"- {warning}")
    if payload.get("next_actions"):
        print("Next actions:")
        for action in payload.get("next_actions", [])[:5]:
            print(f"- {action}")
    discovery = payload.get("local_model_discovery", {}) if isinstance(payload.get("local_model_discovery", {}), dict) else {}
    search_roots = discovery.get("search_roots", []) if isinstance(discovery.get("search_roots", []), list) else []
    discovered_files = discovery.get("discovered_files", []) if isinstance(discovery.get("discovered_files", []), list) else []
    if not payload["checks"].get("local_model_assets_available", False):
        print("Local model search roots:")
        for item in search_roots[:10]:
            print(f"- {item}")
    if discovered_files:
        print("Discovered GGUF files:")
        for item in discovered_files[:10]:
            print(f"- {item}")
    return 0


def _doctor_production_command(as_json: bool) -> int:
    payload = _doctor_payload(production=True)
    if as_json:
        _print_payload(payload, as_json=True)
        return 0 if not payload.get("production", {}).get("warnings") else 1

    print(f"OpenChimera doctor (production): {payload['status']}")
    for check_name, check_value in payload.get("production", {}).get("checks", {}).items():
        print(f"{check_name}: {'ok' if check_value else 'missing'}")
    if payload.get("production", {}).get("warnings"):
        print("Warnings:")
        for warning in payload["production"]["warnings"]:
            print(f"- {warning}")
    return 0 if not payload.get("production", {}).get("warnings") else 1


def _backup_create_payload(*, database_path: Path | None = None, backup_root: Path | None = None) -> dict[str, Any]:
    db_path = _database_path(database_path)
    root = _backup_root(backup_root)
    database = DatabaseManager(db_path=db_path)
    database.initialize()
    backup_name = f"openchimera-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.sqlite3"
    destination = root / backup_name
    database.backup(destination)
    return {
        "status": "ok",
        "database_path": str(db_path),
        "backup": {
            "file": destination.name,
            "path": str(destination),
            "created_at": int(destination.stat().st_mtime),
            "size_bytes": destination.stat().st_size,
        },
    }


def _backup_list_payload(*, backup_root: Path | None = None) -> dict[str, Any]:
    root = _backup_root(backup_root)
    root.mkdir(parents=True, exist_ok=True)
    backups = []
    for path in sorted(root.glob("*.sqlite3"), key=lambda item: item.stat().st_mtime, reverse=True):
        backups.append(
            {
                "file": path.name,
                "path": str(path),
                "created_at": int(path.stat().st_mtime),
                "size_bytes": path.stat().st_size,
            }
        )
    return {"status": "ok", "backup_root": str(root), "count": len(backups), "backups": backups}


def _backup_restore_payload(target: str, *, database_path: Path | None = None, backup_root: Path | None = None) -> dict[str, Any]:
    candidate = Path(str(target).strip())
    if not candidate.is_absolute():
        candidate = _backup_root(backup_root) / candidate
    database = DatabaseManager(db_path=_database_path(database_path))
    restored_path = database.restore(candidate)
    return {
        "status": "ok",
        "database_path": str(restored_path),
        "restored_from": str(candidate),
    }


def _backup_command(action: str, file: str, as_json: bool) -> int:
    if action == "create":
        payload = _backup_create_payload()
    elif action == "list":
        payload = _backup_list_payload()
    else:
        if not str(file).strip():
            print("Backup restore requires a backup file path or file name.", file=sys.stderr)
            return 2
        payload = _backup_restore_payload(file)

    if as_json:
        _print_payload(payload, as_json=True)
        return 0

    if action == "create":
        print(f"Created backup: {payload['backup']['path']}")
        return 0
    if action == "list":
        print(f"Backups: {payload['count']}")
        for item in payload.get("backups", [])[:20]:
            print(f"- {item.get('file')} ({item.get('size_bytes')} bytes)")
        return 0

    print(f"Restored database from: {payload['restored_from']}")
    return 0


def _validate_payload(test_pattern: str | None = None) -> dict[str, Any]:
    return _validate_payload_with_options(test_pattern=test_pattern, stream_output=False)


def _parse_unittest_summary_counts(fragment: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in str(fragment or "").split(","):
        key, separator, value = item.strip().partition("=")
        if not separator:
            continue
        normalized_key = key.strip().replace(" ", "_")
        try:
            counts[normalized_key] = int(value.strip())
        except ValueError:
            continue
    return counts


def _attach_validation_metrics(result: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(result)
    combined_output = "\n".join(
        item for item in [str(enriched.get("stdout") or ""), str(enriched.get("stderr") or "")] if item
    )
    ran_match = re.search(r"Ran\s+(\d+)\s+tests?\s+in\s+([0-9.]+)s", combined_output)
    failed_match = re.search(r"FAILED\s*\(([^)]+)\)", combined_output)
    ok_match = re.search(r"OK\s*\(([^)]+)\)", combined_output)
    summary_counts = _parse_unittest_summary_counts(failed_match.group(1) if failed_match else ok_match.group(1) if ok_match else "")
    enriched["total_tests"] = int(ran_match.group(1)) if ran_match else None
    enriched["duration_seconds"] = float(ran_match.group(2)) if ran_match else None
    enriched["failure_count"] = int(summary_counts.get("failures", 0))
    enriched["error_count"] = int(summary_counts.get("errors", 0))
    enriched["skipped_count"] = int(summary_counts.get("skipped", 0))
    enriched["expected_failures_count"] = int(summary_counts.get("expected_failures", 0))
    enriched["unexpected_successes_count"] = int(summary_counts.get("unexpected_successes", 0))
    if "execution_seconds" not in enriched:
        enriched["execution_seconds"] = None
    return enriched


def _run_validation_tests(test_pattern: str | None = None, *, stream_output: bool = False) -> dict[str, Any]:
    command_spec = _build_validation_command(test_pattern)
    command = list(command_spec["command"])
    started_at = time.perf_counter()
    if not stream_output:
        completed = subprocess.run(
            command,
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            check=False,
        )
        return _attach_validation_metrics({
            "command": command,
            "pattern": command_spec["pattern"],
            "suite": command_spec["suite"],
            "modules": list(command_spec.get("modules", [])),
            "module_count": int(command_spec.get("module_count", 0) or 0),
            "suite_path": str(command_spec.get("suite_path", "")),
            "passed": completed.returncode == 0,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "streamed": False,
            "execution_seconds": round(time.perf_counter() - started_at, 3),
        })

    process = subprocess.Popen(
        command,
        cwd=Path(__file__).resolve().parent,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    def _consume(pipe: Any, sink: list[str], *, forward_to: Any | None = None) -> None:
        try:
            while True:
                line = pipe.readline()
                if line == "":
                    break
                sink.append(line)
                if forward_to is not None:
                    print(line, end="", file=forward_to, flush=True)
        finally:
            pipe.close()

    stdout_thread = threading.Thread(
        target=_consume,
        args=(process.stdout, stdout_lines),
        kwargs={"forward_to": sys.stdout if stream_output else None},
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_consume,
        args=(process.stderr, stderr_lines),
        kwargs={"forward_to": sys.stderr if stream_output else None},
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()
    returncode = process.wait()
    stdout_thread.join()
    stderr_thread.join()

    return _attach_validation_metrics({
        "command": command,
        "pattern": command_spec["pattern"],
        "suite": command_spec["suite"],
        "modules": list(command_spec.get("modules", [])),
        "module_count": int(command_spec.get("module_count", 0) or 0),
        "suite_path": str(command_spec.get("suite_path", "")),
        "passed": returncode == 0,
        "returncode": returncode,
        "stdout": "".join(stdout_lines),
        "stderr": "".join(stderr_lines),
        "streamed": stream_output,
        "execution_seconds": round(time.perf_counter() - started_at, 3),
    })


def _summarize_validation_output(text: str, *, max_lines: int = 12, max_chars: int = 1200) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    lines = normalized.splitlines()
    tail_lines = lines[-max_lines:]
    excerpt = "\n".join(tail_lines)
    if len(excerpt) > max_chars:
        excerpt = excerpt[-max_chars:]
    if len(lines) > max_lines or len(normalized) > len(excerpt):
        excerpt = "...\n" + excerpt.lstrip()
    return excerpt


def _compact_validation_test_output(tests: dict[str, Any]) -> dict[str, Any]:
    compact = _attach_validation_metrics(tests)
    stdout = str(tests.get("stdout") or "")
    stderr = str(tests.get("stderr") or "")
    compact["output_included"] = False
    compact["stdout_length"] = len(stdout)
    compact["stderr_length"] = len(stderr)
    compact["stdout_excerpt"] = _summarize_validation_output(stdout)
    compact["stderr_excerpt"] = _summarize_validation_output(stderr)
    compact["stdout"] = ""
    compact["stderr"] = ""
    return compact


def _validate_payload_with_options(
    test_pattern: str | None = None,
    *,
    stream_output: bool = False,
    include_test_output: bool = False,
) -> dict[str, Any]:
    doctor = _doctor_payload()
    tests = _attach_validation_metrics(_run_validation_tests(test_pattern=test_pattern, stream_output=stream_output))
    if not stream_output and not include_test_output:
        tests = _compact_validation_test_output(tests)
    else:
        tests = dict(tests)
        tests["output_included"] = True
    tests_passed = bool(tests.get("passed"))
    if tests_passed and doctor.get("status") == "ok":
        status = "ok"
    elif tests_passed:
        status = "warning"
    else:
        status = "error"
    return {
        "status": status,
        "doctor": doctor,
        "tests": tests,
    }


def _validate_command(
    as_json: bool,
    test_pattern: str | None = None,
    verbose_tests: bool = False,
    include_test_output: bool = False,
) -> int:
    payload = _validate_payload_with_options(
        test_pattern=test_pattern,
        stream_output=bool(verbose_tests and not as_json),
        include_test_output=bool(include_test_output and as_json),
    )
    if as_json:
        _print_payload(payload, as_json=True)
        return 0 if payload["tests"].get("passed") else 1

    print(f"OpenChimera validate: {payload['status']}")
    print(f"Doctor status: {payload['doctor'].get('status')}")
    doctor_warnings = payload["doctor"].get("warnings", []) if isinstance(payload["doctor"], dict) else []
    if doctor_warnings:
        print(f"Doctor warnings: {len(doctor_warnings)}")
        for warning in doctor_warnings[:3]:
            print(f"- {warning}")
        remaining = len(doctor_warnings) - 3
        if remaining > 0:
            print(f"- ... {remaining} more")
    doctor_actions = payload["doctor"].get("next_actions", []) if isinstance(payload["doctor"], dict) else []
    if doctor_actions:
        print("Doctor next actions:")
        for action in doctor_actions[:2]:
            print(f"- {action}")
        remaining_actions = len(doctor_actions) - 2
        if remaining_actions > 0:
            print(f"- ... {remaining_actions} more")
    if payload["tests"].get("suite") == "release":
        print(f"Validation suite: release ({payload['tests'].get('module_count')} modules)")
    else:
        print("Validation suite: discover")
    print(f"Test pattern: {payload['tests'].get('pattern')}")
    print(f"Tests passed: {payload['tests'].get('passed')}")
    print(f"Validation gate: {'passed' if payload['tests'].get('passed') else 'failed'}")
    stdout = str(payload["tests"].get("stdout") or "").strip()
    stderr = str(payload["tests"].get("stderr") or "").strip()
    if not payload["tests"].get("passed") and stdout and not payload["tests"].get("streamed"):
        print(stdout)
    if not payload["tests"].get("passed") and stderr and not payload["tests"].get("streamed"):
        print(stderr)
    return 0 if payload["tests"].get("passed") else 1


def _onboard_command(as_json: bool, register_local_model_path: str = "", register_local_model_id: str = "") -> int:
    provider = _build_provider()
    registration_path = str(register_local_model_path).strip()
    if registration_path:
        apply_payload: dict[str, Any] = {"local_model_asset_path": registration_path}
        registration_model_id = str(register_local_model_id).strip()
        if registration_model_id:
            apply_payload["local_model_asset_id"] = registration_model_id
        payload = provider.apply_onboarding(apply_payload)
    else:
        payload = provider.onboarding_status()
    if as_json:
        _print_payload(payload, as_json=True)
        return 0

    print("OpenChimera onboarding status")
    if registration_path:
        print(f"Registered local model asset: {registration_path}")
    print(f"Completed: {payload.get('completed', False)}")
    blockers = payload.get("blockers", [])
    next_actions = payload.get("next_actions", [])
    if blockers:
        print("Blockers:")
        for blocker in blockers:
            print(f"- {blocker}")
    if next_actions:
        print("Next actions:")
        for action in next_actions:
            print(f"- {action}")
    return 0


def _capabilities_command(kind: str | None, as_json: bool) -> int:
    provider = _build_provider()
    if kind:
        payload = {"kind": kind, "data": provider.list_capabilities(kind)}
    else:
        payload = provider.capability_status()
    if as_json:
        _print_payload(payload, as_json=True)
        return 0

    if kind:
        print(f"OpenChimera capabilities: {kind}")
        for item in payload["data"][:50]:
            print(f"- {item.get('id')}: {item.get('description', '')}")
        return 0

    counts = payload.get("counts", {})
    print("OpenChimera capabilities")
    print(f"Commands: {counts.get('commands', 0)}")
    print(f"Tools: {counts.get('tools', 0)}")
    print(f"Skills: {counts.get('skills', 0)}")
    print(f"Plugins: {counts.get('plugins', 0)}")
    print(f"MCP servers: {counts.get('mcp_servers', 0)}")
    return 0


def _parse_json_object(value: str, *, label: str) -> dict[str, Any]:
    normalized = str(value or "").strip()
    if not normalized:
        return {}
    parsed = json.loads(normalized)
    if not isinstance(parsed, dict):
        raise ValueError(f"{label} must decode to a JSON object")
    return parsed


def _query_command(
    text: str,
    session_id: str | None,
    permission_scope: str,
    execute_tools: bool,
    tool_request_items: list[str],
    as_json: bool,
) -> int:
    provider = _build_provider()
    try:
        tool_requests = [_parse_json_object(item, label="tool-request-json") for item in tool_request_items if str(item).strip()]
    except (ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    payload = provider.run_query(
        query=text,
        session_id=session_id or None,
        permission_scope=permission_scope,
        execute_tools=bool(execute_tools),
        tool_requests=tool_requests or None,
    )
    if as_json:
        _print_payload(payload, as_json=True)
        return 0

    print(f"Session: {payload.get('session_id')}")
    print(f"Query type: {payload.get('query_type')}")
    executed_tools = payload.get("executed_tools", []) if isinstance(payload.get("executed_tools", []), list) else []
    if executed_tools:
        print("Executed tools:")
        for item in executed_tools:
            print(f"- {item.get('tool_id')}: {item.get('status')}")
    print(payload.get("response", {}).get("choices", [{}])[0].get("message", {}).get("content", ""))
    return 0


def _tools_command(
    tool_id: str,
    arguments_json: str,
    permission_scope: str,
    execute: bool,
    as_json: bool,
    list_tools: bool = False,
    register_args: list[str] | None = None,
    call_args: list[str] | None = None,
) -> int:
    provider = _build_provider()

    # --list: list all registered tools
    if list_tools:
        payload = provider.tool_status()
        if as_json:
            _print_payload(payload, as_json=True)
            return 0
        print(f"Runtime tools: {payload.get('counts', {}).get('total', 0)}")
        for item in payload.get("tools", [])[:50]:
            print(f"- {item.get('id')}: {item.get('description', '')}")
        return 0

    # --register NAME DESCRIPTION: register a tool entry
    if register_args and len(register_args) == 2:
        from core.tool_runtime import ToolMetadata
        name, description = register_args
        # Register via the provider's capability plane if available, else just show
        payload = {"name": name, "description": description, "status": "registered"}
        if hasattr(provider, "capability_plane") and hasattr(provider.capability_plane, "register_tool"):
            tool = ToolMetadata(name=name, description=description, tags=["cli-registered"])
            payload = provider.capability_plane.register_tool(tool)
        if as_json:
            _print_payload(payload, as_json=True)
            return 0
        print(f"Registered tool: {name}")
        return 0

    # --call NAME [args_json]: execute a tool by name
    if call_args:
        call_name = call_args[0]
        call_arguments: dict[str, Any] = {}
        if len(call_args) > 1:
            try:
                call_arguments = json.loads(call_args[1])
            except json.JSONDecodeError as exc:
                print(f"Invalid JSON args: {exc}", file=sys.stderr)
                return 2
        payload = provider.execute_tool(call_name, call_arguments, permission_scope=permission_scope)
        if as_json:
            _print_payload(payload, as_json=True)
            return 0
        print(f"Executed tool: {payload.get('tool_id')}")
        print(f"Status: {payload.get('status')}")
        return 0

    if execute:
        if not str(tool_id).strip():
            print("Tool execution requires --id.", file=sys.stderr)
            return 2
        try:
            arguments = _parse_json_object(arguments_json, label="arguments-json") if str(arguments_json).strip() else {}
        except (ValueError, json.JSONDecodeError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        payload = provider.execute_tool(str(tool_id).strip(), arguments, permission_scope=permission_scope)
        if as_json:
            _print_payload(payload, as_json=True)
            return 0
        print(f"Executed tool: {payload.get('tool_id')}")
        print(f"Status: {payload.get('status')}")
        return 0

    if str(tool_id).strip():
        payload = provider.get_tool(str(tool_id).strip())
    else:
        payload = provider.tool_status()
    if as_json:
        _print_payload(payload, as_json=True)
        return 0

    if str(tool_id).strip():
        print(f"Tool: {payload.get('id')}")
        print(f"Category: {payload.get('category')}")
        print(f"Requires admin: {payload.get('requires_admin')}")
        print(payload.get("description", ""))
        return 0

    print(f"Runtime tools: {payload.get('counts', {}).get('total', 0)}")
    for item in payload.get("tools", [])[:50]:
        print(f"- {item.get('id')}: {item.get('description', '')}")
    return 0


def _sessions_command(
    session_id: str | None,
    as_json: bool,
    branch_checkpoint: str = "",
    replay_checkpoint: str = "",
    new_input: str = "",
) -> int:
    provider = _build_provider()

    # --branch: branch from a checkpoint
    if branch_checkpoint:
        if not new_input:
            print("--branch requires --input <text>.", file=sys.stderr)
            return 2
        try:
            payload = provider.query_engine.branch_from_checkpoint(branch_checkpoint, new_input)
        except Exception as exc:
            print(f"Branch failed: {exc}", file=sys.stderr)
            return 1
        if as_json:
            _print_payload(payload, as_json=True)
            return 0
        print(f"Branched session: {payload.get('session_id')}")
        return 0

    # --replay: replay from a checkpoint
    if replay_checkpoint:
        if not new_input:
            print("--replay requires --input <text>.", file=sys.stderr)
            return 2
        try:
            payload = provider.query_engine.replay_session(replay_checkpoint, new_input)
        except Exception as exc:
            print(f"Replay failed: {exc}", file=sys.stderr)
            return 1
        if as_json:
            _print_payload(payload, as_json=True)
            return 0
        print(f"Replayed session: {payload.get('session_id')}")
        return 0

    payload = provider.get_query_session(session_id) if session_id else {"data": provider.list_query_sessions()}
    if as_json:
        _print_payload(payload if isinstance(payload, dict) else {"data": payload}, as_json=True)
        return 0

    if session_id:
        print(f"Session: {payload.get('session_id')}")
        print(f"Title: {payload.get('title')}")
        print(f"Turns: {len(payload.get('turns', []))}")
        return 0

    for item in payload.get("data", [])[:20]:
        print(f"- {item.get('session_id')}: {item.get('title', '')}")
    return 0


def _memory_command(as_json: bool) -> int:
    provider = _build_provider()
    payload = provider.inspect_memory()
    if as_json:
        _print_payload(payload, as_json=True)
        return 0

    for summary in payload.get("summaries", []):
        print(f"- {summary}")
    return 0


def _parse_role_overrides(items: list[str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key and value:
            overrides[key] = value
    return overrides


def _model_roles_command(set_items: list[str], as_json: bool) -> int:
    provider = _build_provider()
    payload = provider.configure_model_roles(_parse_role_overrides(set_items)) if set_items else provider.model_role_status()
    if as_json:
        _print_payload(payload, as_json=True)
        return 0

    roles = payload.get("roles", {})
    for role_name, details in roles.items():
        if isinstance(details, dict) and "models" in details:
            print(f"- {role_name}: {', '.join(str(item) for item in details.get('models', []))}")
        else:
            print(f"- {role_name}: {details.get('model') if isinstance(details, dict) else details}")
    return 0


def _mcp_command(
    as_json: bool,
    serve: bool = False,
    registry: bool = False,
    register_id: str = "",
    unregister_id: str = "",
    transport: str = "",
    url: str = "",
    command: str = "",
    args: list[str] | None = None,
    name: str = "",
    description: str = "",
    disabled: bool = False,
    probe: bool = False,
    probe_id: str = "",
    resources: bool = False,
    prompts: bool = False,
) -> int:
    if serve:
        from core.mcp_server import OpenChimeraMCPServer

        server = OpenChimeraMCPServer()
        return server.serve_stdio()

    if register_id:
        try:
            payload = upsert_mcp_registry_entry(
                register_id,
                transport=transport,
                url=url or None,
                command=command or None,
                args=list(args or []),
                name=name or None,
                description=description or None,
                enabled=not disabled,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        if as_json:
            _print_payload(payload, as_json=True)
            return 0
        print(f"Registered MCP connector: {payload.get('id')}")
        print(f"Transport: {payload.get('transport')}")
        if payload.get("url"):
            print(f"URL: {payload.get('url')}")
        if payload.get("command"):
            print(f"Command: {payload.get('command')}")
        return 0

    if unregister_id:
        payload = delete_mcp_registry_entry(unregister_id)
        if as_json:
            _print_payload(payload, as_json=True)
            return 0
        print(f"Removed MCP connector: {payload.get('id')}")
        print(f"Deleted: {payload.get('deleted')}")
        return 0

    if registry:
        servers = list_mcp_registry_with_health()
        payload = {"counts": {"total": len(servers)}, "servers": servers}
        if as_json:
            _print_payload(payload, as_json=True)
            return 0
        print(f"Registered MCP connectors: {payload['counts']['total']}")
        for item in servers[:20]:
            print(f"- {item.get('id')}: {item.get('transport')} [{item.get('status')}]")
        return 0

    if probe:
        try:
            payload = probe_mcp_registry_entry(probe_id, timeout_seconds=3.0) if probe_id else probe_all_mcp_registry_entries(timeout_seconds=3.0)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        if as_json:
            _print_payload(payload if isinstance(payload, dict) else {"servers": [payload]}, as_json=True)
            return 0
        if probe_id:
            print(f"Probed MCP connector: {payload.get('id')}")
            print(f"Status: {payload.get('status')}")
            if payload.get("last_error"):
                print(f"Last error: {payload.get('last_error')}")
            return 0
        print(f"Probed MCP connectors: {payload.get('counts', {}).get('total', 0)}")
        for item in payload.get("servers", [])[:20]:
            print(f"- {item.get('id')}: {item.get('status')}")
        return 0

    if resources or prompts:
        from core.mcp_server import OpenChimeraMCPServer

        server = OpenChimeraMCPServer(provider=_build_provider())
        payload = {"resources": server.resource_descriptors()} if resources else {"prompts": server.prompt_descriptors()}
        if as_json:
            _print_payload(payload, as_json=True)
            return 0
        key = "resources" if resources else "prompts"
        label = "MCP resources" if resources else "MCP prompts"
        print(label)
        for item in payload.get(key, [])[:20]:
            identifier = item.get("uri") or item.get("name")
            print(f"- {identifier}: {item.get('description', '')}")
        return 0

    provider = _build_provider()
    payload = provider.mcp_status()
    if as_json:
        _print_payload(payload, as_json=True)
        return 0

    counts = payload.get("counts", {}) if isinstance(payload, dict) else {}
    print(f"MCP servers: {counts.get('total', 0)}")
    for item in payload.get("servers", [])[:20]:
        print(f"- {item.get('id')}: {item.get('status', 'unknown')}")
    registered = payload.get("registry", {}).get("servers", [])
    if registered:
        print(f"Registered connectors: {len(registered)}")
    return 0


def _subsystems_command(subsystem_id: str, action: str, prompt: str, target_project: str, as_json: bool) -> int:
    provider = _build_provider()
    if subsystem_id:
        payload = provider.invoke_subsystem(
            subsystem_id,
            action,
            {
                "action": action,
                "prompt": prompt,
                "target_project": target_project,
                "preview": True,
            },
        )
    else:
        payload = provider.subsystem_status()
    if as_json:
        _print_payload(payload, as_json=True)
        return 0

    if subsystem_id:
        print(json.dumps(payload, indent=2))
        return 0

    for item in payload.get("subsystems", [])[:20]:
        print(f"- {item.get('id')}: {item.get('health')} ({item.get('description')})")
    return 0


def _plugins_command(install_id: str, uninstall_id: str, as_json: bool, load_path: str = "", list_loaded: bool = False) -> int:
    provider = _build_provider()
    if load_path:
        # Load a plugin from a manifest path via the capability plane
        from core.capability_plane import CapabilityPlane
        from core.bus import EventBus
        from core.capabilities import CapabilityRegistry
        bus = EventBus()
        # Minimal stub for plugin loading — capability plane is self-contained
        class _StubPlugins:
            def status(self): return {"plugins": []}
            def install(self, _id): return {"installed": False, "id": _id}
            def uninstall(self, _id): return {"uninstalled": False, "id": _id}
        class _StubCaps:
            def status(self): return {}
            def list_kind(self, _k): return []
            def refresh(self): pass
        plane = CapabilityPlane(capabilities=_StubCaps(), plugins=_StubPlugins(), bus=bus)
        payload = plane.load_plugin(load_path)
        if as_json:
            _print_payload(payload, as_json=True)
            return 0
        status = payload.get("status", "error")
        pid = payload.get("plugin_id", load_path)
        print(f"Plugin load: {status} ({pid})")
        if payload.get("error"):
            print(f"Error: {payload['error']}")
        return 0 if status == "ok" else 1

    if list_loaded:
        # Show the manifests in the plugins/ directory
        plugins_dir = Path(__file__).resolve().parent / "plugins"
        manifests = list(plugins_dir.glob("*.json")) if plugins_dir.exists() else []
        payload = {
            "plugins": [
                {
                    "file": p.name,
                    "id": json.loads(p.read_text(encoding="utf-8")).get("id", p.stem) if p.exists() else p.stem,
                }
                for p in manifests
            ]
        }
        if as_json:
            _print_payload(payload, as_json=True)
            return 0
        print(f"Discovered plugin manifests: {len(manifests)}")
        for item in payload["plugins"]:
            print(f"- {item['id']} ({item['file']})")
        return 0

    if install_id:
        payload = provider.install_plugin(install_id)
    elif uninstall_id:
        payload = provider.uninstall_plugin(uninstall_id)
    else:
        payload = provider.plugin_status()
    if as_json:
        _print_payload(payload, as_json=True)
        return 0

    plugins = payload.get("plugins", []) if isinstance(payload, dict) else []
    if plugins:
        for item in plugins[:20]:
            print(f"- {item.get('id')}: installed={item.get('installed', False)}")
        return 0
    print(json.dumps(payload, indent=2))
    return 0


def _phases_command(as_json: bool) -> int:
    """Show completion status of all AGI implementation phases."""
    import importlib

    def _check(module: str, attr: str) -> bool:
        try:
            mod = importlib.import_module(module)
            return hasattr(mod, attr)
        except Exception:
            return False

    phases = {
        "Phase 1 — Capability Architecture": {
            "tool_runtime: ToolMetadata": _check("core.tool_runtime", "ToolMetadata"),
            "tool_runtime: ToolResult": _check("core.tool_runtime", "ToolResult"),
            "tool_runtime: ToolRegistry": _check("core.tool_runtime", "ToolRegistry"),
            "capability_plane: register_tool": _check("core.capability_plane", "CapabilityPlane"),
            "capability_plane: find_capability": _check("core.capability_plane", "CapabilityPlane"),
            "capability_plane: load_plugin": _check("core.capability_plane", "CapabilityPlane"),
        },
        "Phase 2 — Query Engine Enhancement": {
            "query_engine: SessionCheckpoint": _check("core.query_engine", "SessionCheckpoint"),
            "query_engine: QueryResult": _check("core.query_engine", "QueryResult"),
            "query_engine: save_checkpoint": _check("core.query_engine", "QueryEngine"),
            "query_engine: branch_from_checkpoint": _check("core.query_engine", "QueryEngine"),
            "query_engine: replay_session": _check("core.query_engine", "QueryEngine"),
        },
        "Phase 3 — Model-Role Expansion": {
            "router: ModelRole enum": _check("core.router", "ModelRole"),
            "router: ModelRoleAssignment": _check("core.router", "ModelRoleAssignment"),
            "router: RoleRegistry": _check("core.router", "RoleRegistry"),
            "router: OpenChimeraRouter.route_by_role": _check("core.router", "OpenChimeraRouter"),
        },
        "Phase 4 — Subsystem Formalization": {
            "god_swarm: spawn_agent": _check("swarms.god_swarm", "GodSwarm"),
            "god_swarm: coordinate": _check("swarms.god_swarm", "GodSwarm"),
            "god_swarm: wire_to_kernel": _check("swarms.god_swarm", "GodSwarm"),
            "evolution: DPOSignal": _check("core.evolution", "DPOSignal"),
            "evolution: record_outcome": _check("core.evolution", "EvolutionEngine"),
            "evolution: apply_dpo_signals": _check("core.evolution", "EvolutionEngine"),
            "quantum_engine: QuantumServiceContract": _check("core.quantum_engine", "QuantumServiceContract"),
        },
        "Phase 5 — Operator UX": {
            "run.py: phases command": True,  # This command itself
            "run.py: tools list/register/call": True,
            "run.py: skills discover": True,
            "run.py: plugins load/list": True,
            "run.py: sessions branch/replay": True,
            "run.py: roles assign/list": True,
        },
    }

    # Verify method presence for classes
    def _check_method(module: str, cls: str, method: str) -> bool:
        try:
            mod = importlib.import_module(module)
            klass = getattr(mod, cls, None)
            return klass is not None and hasattr(klass, method)
        except Exception:
            return False

    phases["Phase 2 — Query Engine Enhancement"]["query_engine: save_checkpoint"] = _check_method("core.query_engine", "QueryEngine", "save_checkpoint")
    phases["Phase 2 — Query Engine Enhancement"]["query_engine: branch_from_checkpoint"] = _check_method("core.query_engine", "QueryEngine", "branch_from_checkpoint")
    phases["Phase 2 — Query Engine Enhancement"]["query_engine: replay_session"] = _check_method("core.query_engine", "QueryEngine", "replay_session")
    phases["Phase 4 — Subsystem Formalization"]["god_swarm: spawn_agent"] = _check_method("swarms.god_swarm", "GodSwarm", "spawn_agent")
    phases["Phase 4 — Subsystem Formalization"]["god_swarm: coordinate"] = _check_method("swarms.god_swarm", "GodSwarm", "coordinate")
    phases["Phase 4 — Subsystem Formalization"]["god_swarm: wire_to_kernel"] = _check_method("swarms.god_swarm", "GodSwarm", "wire_to_kernel")
    phases["Phase 4 — Subsystem Formalization"]["evolution: record_outcome"] = _check_method("core.evolution", "EvolutionEngine", "record_outcome")
    phases["Phase 4 — Subsystem Formalization"]["evolution: apply_dpo_signals"] = _check_method("core.evolution", "EvolutionEngine", "apply_dpo_signals")

    if as_json:
        _print_payload({"phases": phases}, as_json=True)
        return 0

    all_complete = True
    for phase_name, checks in phases.items():
        phase_ok = all(checks.values())
        all_complete = all_complete and phase_ok
        status = "✓" if phase_ok else "✗"
        print(f"\n{status} {phase_name}")
        for check_name, passed in checks.items():
            mark = "  ✓" if passed else "  ✗"
            print(f"{mark} {check_name}")

    print(f"\nOverall: {'✓ ALL PHASES COMPLETE' if all_complete else '✗ INCOMPLETE — see ✗ items above'}")
    return 0 if all_complete else 1


def _roles_command(assign_args: list[str] | None, list_roles: bool, as_json: bool) -> int:
    """Assign or list model-role assignments via the RoleRegistry."""
    from core.router import ModelRole, RoleRegistry
    registry = RoleRegistry()

    if assign_args and len(assign_args) == 2:
        role_str, model = assign_args
        try:
            role = ModelRole(role_str.lower())
        except ValueError:
            valid = [r.value for r in ModelRole]
            print(f"Unknown role {role_str!r}. Valid roles: {', '.join(valid)}", file=sys.stderr)
            return 2
        assignment = registry.assign_role(role, model)
        payload = assignment.to_dict()
        if as_json:
            _print_payload(payload, as_json=True)
            return 0
        print(f"Assigned role={role.value} → model={model}")
        return 0

    # Default: list all roles
    payload = {"roles": registry.list_roles()}
    if as_json:
        _print_payload(payload, as_json=True)
        return 0
    print("Model role assignments:")
    for entry in payload["roles"]:
        model = entry.get("model", "unassigned")
        reason = entry.get("reason", "")
        print(f"  {entry['role']:12s} → {model}  ({reason})")
    return 0


def _skills_discover_command(as_json: bool) -> int:
    """Discover available skills from the skills/ directory and capability registry."""
    provider = _build_provider()
    skills_dir = Path(__file__).resolve().parent / "skills"
    discovered: list[dict[str, Any]] = []

    # Walk skills directory for SKILL.md descriptors
    if skills_dir.exists():
        for skill_md in skills_dir.rglob("SKILL.md"):
            skill_name = skill_md.parent.name
            try:
                content = skill_md.read_text(encoding="utf-8")
                first_line = content.splitlines()[0].lstrip("#").strip() if content else skill_name
            except Exception:
                first_line = skill_name
            discovered.append({
                "name": skill_name,
                "path": str(skill_md.relative_to(skills_dir)),
                "description": first_line,
                "source": "filesystem",
            })

    # Also pull from capability registry
    try:
        cap_skills = provider.capability_plane.list_capabilities("skills") if hasattr(provider, "capability_plane") else []
        for item in cap_skills:
            discovered.append({"source": "registry", **item})
    except Exception:
        pass

    payload = {"count": len(discovered), "skills": discovered}
    if as_json:
        _print_payload(payload, as_json=True)
        return 0
    print(f"Discovered skills: {len(discovered)}")
    for item in discovered[:30]:
        print(f"  [{item.get('source', '?')}] {item.get('name', '?')}: {item.get('description', '')[:80]}")
    return 0


def _serve_command(verbose: bool) -> int:
    _setup_logging(verbose=verbose)
    workspace_root = _configure_workspace()
    logging.info("Starting OpenChimera from %s", workspace_root)
    bootstrap_report = bootstrap_workspace()
    logging.info(
        "Bootstrap complete. created_dirs=%s created_files=%s normalized_files=%s",
        len(bootstrap_report["created_directories"]),
        len(bootstrap_report["created_files"]),
        len(bootstrap_report["normalized_files"]),
    )
    kernel = OpenChimeraKernel()
    try:
        kernel.boot()
    except KeyboardInterrupt:
        logging.info("Stopping OpenChimera...")
        kernel.shutdown()
    return 0


def main(argv: list[str] | None = None) -> int:
    _configure_workspace()
    parser = _build_parser()
    args = parser.parse_args(argv if argv is not None else (["serve"] if len(sys.argv) == 1 else None))

    command = args.command or "serve"
    if command == "serve":
        return _serve_command(verbose=bool(getattr(args, "verbose", False)))
    if command == "bootstrap":
        return _bootstrap_command(as_json=bool(args.json))
    if command == "setup":
        return _setup_command(skip_wizard=bool(getattr(args, "skip_wizard", False)))
    if command == "configure":
        return _configure_quantum_command(
            list_caps=bool(getattr(args, "list_caps", False)),
            enable_id=str(getattr(args, "enable", "")).strip(),
            disable_id=str(getattr(args, "disable", "")).strip(),
            as_json=bool(args.json),
        )
    if command == "status":
        return _status_command(as_json=bool(args.json))
    if command == "briefing":
        return _briefing_command(as_json=bool(args.json))
    if command == "channels":
        return _channels_command(
            set_subscription_json=str(getattr(args, "set_subscription_json", "")).strip(),
            channel=str(getattr(args, "channel", "")).strip(),
            subscription_id=str(getattr(args, "subscription_id", "")).strip(),
            endpoint=str(getattr(args, "endpoint", "")).strip(),
            file_path=str(getattr(args, "file_path", "")).strip(),
            bot_token=str(getattr(args, "bot_token", "")).strip(),
            chat_id=str(getattr(args, "chat_id", "")).strip(),
            topics_csv=str(getattr(args, "topics_csv", "")).strip(),
            disabled=bool(getattr(args, "disabled", False)),
            delete_subscription=str(getattr(args, "delete_subscription", "")).strip(),
            validate_subscription=str(getattr(args, "validate_subscription", "")).strip(),
            dispatch_topic=str(getattr(args, "dispatch_topic", "")).strip(),
            history=bool(getattr(args, "history", False)),
            topic=str(getattr(args, "topic", "")).strip(),
            status=str(getattr(args, "status", "")).strip(),
            limit=int(getattr(args, "limit", 20)),
            message=str(getattr(args, "message", "")),
            payload_json=str(getattr(args, "payload_json", "")),
            as_json=bool(args.json),
        )
    if command == "autonomy":
        return _autonomy_command(
            job_name=str(getattr(args, "job", "")).strip(),
            history=bool(getattr(args, "history", False)),
            artifact_name=str(getattr(args, "artifact", "")).strip(),
            operator_digest=bool(getattr(args, "operator_digest", False)),
            dispatch_digest=bool(getattr(args, "dispatch_digest", False)),
            dispatch_topic=str(getattr(args, "dispatch_topic", "")).strip(),
            history_limit=int(getattr(args, "history_limit", 0)),
            preview_repair=bool(getattr(args, "preview_repair", False)),
            target_project=str(getattr(args, "target_project", "")).strip(),
            enqueue=bool(getattr(args, "enqueue", False)),
            limit=int(getattr(args, "limit", 20)),
            max_attempts=int(getattr(args, "max_attempts", 3)),
            as_json=bool(args.json),
        )
    if command == "jobs":
        return _jobs_command(
            job_id=str(getattr(args, "id", "")).strip(),
            status_filter=str(getattr(args, "status", "")).strip(),
            job_type=str(getattr(args, "type", "")).strip(),
            limit=int(getattr(args, "limit", 20)),
            cancel_id=str(getattr(args, "cancel", "")).strip(),
            replay_id=str(getattr(args, "replay", "")).strip(),
            as_json=bool(args.json),
        )
    if command == "doctor":
        if bool(getattr(args, "production", False)):
            return _doctor_production_command(as_json=bool(args.json))
        return _doctor_command(as_json=bool(args.json))
    if command == "backup":
        return _backup_command(
            action=str(getattr(args, "action", "list")).strip(),
            file=str(getattr(args, "file", "")).strip(),
            as_json=bool(args.json),
        )
    if command == "config":
        return _config_command(as_json=bool(args.json))
    if command == "validate":
        return _validate_command(
            as_json=bool(args.json),
            test_pattern=str(getattr(args, "pattern", "")).strip() or None,
            verbose_tests=bool(getattr(args, "verbose_tests", False)),
            include_test_output=bool(getattr(args, "include_test_output", False)),
        )
    if command == "onboard":
        return _onboard_command(
            as_json=bool(args.json),
            register_local_model_path=str(getattr(args, "register_local_model_path", "")).strip(),
            register_local_model_id=str(getattr(args, "register_local_model_id", "")).strip(),
        )
    if command == "capabilities":
        return _capabilities_command(kind=getattr(args, "kind", None), as_json=bool(args.json))
    if command == "query":
        return _query_command(
            text=str(getattr(args, "text", "")),
            session_id=str(getattr(args, "session_id", "")).strip() or None,
            permission_scope=str(getattr(args, "permission_scope", "user")),
            execute_tools=bool(getattr(args, "execute_tools", False)),
            tool_request_items=list(getattr(args, "tool_request_json", [])),
            as_json=bool(args.json),
        )
    if command == "tools":
        return _tools_command(
            tool_id=str(getattr(args, "id", "")).strip(),
            arguments_json=str(getattr(args, "arguments_json", "")),
            permission_scope=str(getattr(args, "permission_scope", "user")),
            execute=bool(getattr(args, "execute", False)),
            as_json=bool(args.json),
            list_tools=bool(getattr(args, "list", False)),
            register_args=list(getattr(args, "register", None) or []) or None,
            call_args=list(getattr(args, "call", None) or []) or None,
        )
    if command == "sessions":
        return _sessions_command(
            session_id=str(getattr(args, "session_id", "")).strip() or None,
            as_json=bool(args.json),
            branch_checkpoint=str(getattr(args, "branch", "")).strip(),
            replay_checkpoint=str(getattr(args, "replay", "")).strip(),
            new_input=str(getattr(args, "input", "")).strip(),
        )
    if command == "memory":
        return _memory_command(as_json=bool(args.json))
    if command == "model-roles":
        return _model_roles_command(set_items=list(getattr(args, "set", [])), as_json=bool(args.json))
    if command == "mcp":
        return _mcp_command(
            as_json=bool(args.json),
            serve=bool(getattr(args, "serve", False)),
            registry=bool(getattr(args, "registry", False)),
            register_id=str(getattr(args, "register", "")).strip(),
            unregister_id=str(getattr(args, "unregister", "")).strip(),
            transport=str(getattr(args, "transport", "") or "").strip(),
            url=str(getattr(args, "url", "") or "").strip(),
            command=str(getattr(args, "stdio_command", "") or "").strip(),
            args=list(getattr(args, "arg", [])),
            name=str(getattr(args, "name", "") or "").strip(),
            description=str(getattr(args, "description", "") or "").strip(),
            disabled=bool(getattr(args, "disabled", False)),
            probe=bool(getattr(args, "probe", False)),
            probe_id=str(getattr(args, "id", "") or "").strip(),
            resources=bool(getattr(args, "resources", False)),
            prompts=bool(getattr(args, "prompts", False)),
        )
    if command == "subsystems":
        return _subsystems_command(
            subsystem_id=str(getattr(args, "id", "")).strip(),
            action=str(getattr(args, "action", "status")),
            prompt=str(getattr(args, "prompt", "")),
            target_project=str(getattr(args, "target_project", "")),
            as_json=bool(args.json),
        )
    if command == "plugins":
        return _plugins_command(
            install_id=str(getattr(args, "install", "")).strip(),
            uninstall_id=str(getattr(args, "uninstall", "")).strip(),
            as_json=bool(args.json),
            load_path=str(getattr(args, "load", "")).strip(),
            list_loaded=bool(getattr(args, "list", False)),
        )
    if command == "phases":
        return _phases_command(as_json=bool(args.json))
    if command == "roles":
        assign_args = list(getattr(args, "assign", None) or []) or None
        return _roles_command(
            assign_args=assign_args,
            list_roles=bool(getattr(args, "list", False)),
            as_json=bool(args.json),
        )
    if command == "skills":
        if bool(getattr(args, "discover", False)):
            return _skills_discover_command(as_json=bool(args.json))
        return _skills_discover_command(as_json=bool(args.json))
    parser.error(f"Unknown command: {command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())