"""OpenChimera v2 CLI — inspired by OpenClaw and Hermes Agent onboarding."""

from __future__ import annotations

import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from openchimera.config import load_settings
from openchimera.server import start_server

console = Console()


@click.group()
@click.version_option(version="2.0.0", prog_name="openchimera")
def cli() -> None:
    """OpenChimera v2 — Agentic orchestration runtime.

    One-liner install: iwr -useb https://raw.githubusercontent.com/fernandogarzaaa/OpenChimera_v1/main/install.ps1 | iex
    """
    pass


@cli.command()
@click.option("--host", default=None, help="Bind host")
@click.option("--port", type=int, default=None, help="Bind port")
@click.option("--reload", is_flag=True, help="Enable auto-reload")
def serve(host: str | None, port: int | None, reload: bool) -> None:
    """Start the OpenChimera API server."""
    settings = load_settings()
    bind_host = host or settings.server.host
    bind_port = port or settings.server.port
    console.print(f"[bold green]🚀 Starting OpenChimera v2 on http://{bind_host}:{bind_port}[/bold green]")
    start_server(host=bind_host, port=bind_port, reload=reload)


@cli.command()
@click.option("--json", "as_json", is_flag=True, help="Emit JSON output.")
def bootstrap(as_json: bool) -> None:
    """Create missing local state directories and report what exists."""
    workspace = Path.cwd()
    dirs = [workspace / "config", workspace / "data"]
    created: list[str] = []
    for directory in dirs:
        if not directory.exists():
            directory.mkdir(parents=True, exist_ok=True)
            created.append(str(directory))
    payload = {
        "status": "ok",
        "workspace": str(workspace),
        "config_dir": str(workspace / "config"),
        "data_dir": str(workspace / "data"),
        "created_directories": created,
    }
    if as_json:
        print(json.dumps(payload, indent=2))
        return
    console.print("[bold green]Bootstrap complete[/bold green]")
    console.print(f"Workspace: {workspace}")
    if created:
        for item in created:
            console.print(f"  Created: {item}")
    else:
        console.print("  Local state already present")


@cli.command()
@click.option("--json", "as_json", is_flag=True, help="Emit JSON output.")
def status(as_json: bool) -> None:
    """Show runtime status."""
    settings = load_settings()
    if as_json:
        enabled = [k for k, v in settings.providers.items() if v.enabled]
        payload = {
            "status": "ok",
            "version": "2.0.0",
            "config_path": str(settings.config_path),
            "server": {"host": settings.server.host, "port": settings.server.port},
            "providers_enabled": enabled,
            "cognitive": {
                "axiom": settings.cognitive.axiom.enabled,
                "eve": settings.cognitive.eve.enabled,
                "adam": settings.cognitive.adam.enabled,
            },
            "computer_use": settings.computer_use.enabled,
            "rag": settings.rag.enabled,
            "mcp": settings.mcp.enabled,
        }
        print(json.dumps(payload, indent=2))
        return
    table = Table(title="OpenChimera v2 Status", show_header=True, header_style="bold cyan")
    table.add_column("Key", style="dim")
    table.add_column("Value")

    table.add_row("Version", "2.0.0")
    table.add_row("Config", str(settings.config_path))
    table.add_row("Server", f"{settings.server.host}:{settings.server.port}")

    enabled = [k for k, v in settings.providers.items() if v.enabled]
    table.add_row("Providers", f"{len(enabled)} enabled ({', '.join(enabled) or 'none'})")
    table.add_row("Cognitive", f"AXIOM={settings.cognitive.axiom.enabled} EVE={settings.cognitive.eve.enabled} ADAM={settings.cognitive.adam.enabled}")
    table.add_row("Computer Use", str(settings.computer_use.enabled))
    table.add_row("RAG", str(settings.rag.enabled))
    table.add_row("MCP", str(settings.mcp.enabled))

    console.print(table)


@cli.command()
def onboard() -> None:
    """Interactive setup wizard — configure providers, API keys, and preferences."""
    console.print(Panel.fit("[bold blue]🐉 OpenChimera v2 Onboarding[/bold blue]", border_style="blue"))

    settings = load_settings(force_reload=True)
    config_dir = Path("config")
    config_dir.mkdir(exist_ok=True)

    # Check providers
    console.print("\n[bold]Step 1: Configure AI Providers[/bold]")
    providers_to_check = [
        ("openai", "OPENAI_API_KEY", "OpenAI (GPT-4o, o1, o3-mini)"),
        ("anthropic", "ANTHROPIC_API_KEY", "Anthropic (Claude 3.5 Sonnet, Opus)"),
        ("google", "GOOGLE_API_KEY", "Google (Gemini 1.5 Flash, Pro)"),
        ("groq", "GROQ_API_KEY", "Groq (fast Llama/Mistral inference)"),
        ("deepseek", "DEEPSEEK_API_KEY", "DeepSeek (chat + reasoning)"),
        ("mistral", "MISTRAL_API_KEY", "Mistral AI"),
        ("ollama", "", "Ollama (local LLMs — no API key needed)"),
    ]

    enabled_any = False
    for prov_name, env_var, description in providers_to_check:
        key = ""
        if env_var:
            import os
            key = os.getenv(env_var, "")
        if key:
            console.print(f"  [green]✓[/green] {description}: API key found")
            setattr(settings.providers, prov_name, settings.providers[prov_name].model_copy(update={"enabled": True, "api_key": key}))
            enabled_any = True
        else:
            console.print(f"  [yellow]○[/yellow] {description}: No API key set (set {env_var} env var)")

    if not enabled_any:
        console.print("\n[bold yellow]⚠ No providers configured.[/bold yellow]")
        console.print("Set API keys as environment variables or edit config/local.yaml")
        console.print("Example: $env:OPENAI_API_KEY = 'sk-...'  # PowerShell")
        console.print("Example: export OPENAI_API_KEY=sk-...     # Bash")

    # Check optional features
    console.print("\n[bold]Step 2: Optional Features[/bold]")
    try:
        import chromadb
        console.print("  [green]✓[/green] ChromaDB (RAG vector store)")
    except ImportError:
        console.print("  [yellow]○[/yellow] ChromaDB not installed — RAG will use memory fallback")

    try:
        import playwright
        console.print("  [green]✓[/green] Playwright (browser automation)")
    except ImportError:
        console.print("  [yellow]○[/yellow] Playwright not installed — browser tools unavailable")

    try:
        import mcp
        console.print("  [green]✓[/green] MCP SDK (Model Context Protocol)")
    except ImportError:
        console.print("  [yellow]○[/yellow] MCP SDK not installed")

    # Cognitive stack
    console.print("\n[bold]Step 3: Cognitive Stack[/bold]")
    cog = settings.cognitive
    console.print(f"  AXIOM: {'[green]✓[/green]' if cog.axiom.enabled else '[red]✗[/red]'} (checkpoints: {cog.axiom.checkpoints_dir})")
    console.print(f"  EVE: {'[green]✓[/green]' if cog.eve.enabled else '[red]✗[/red]'} (personas: {', '.join(cog.eve.personas)})")
    console.print(f"  ADAM: {'[green]✓[/green]' if cog.adam.enabled else '[red]✗[/red]'} (genome: {cog.adam.genome_path})")

    console.print("\n[bold green]✓ Onboarding complete![/bold green]")
    console.print("\nNext steps:")
    console.print("  openchimera serve       # Start the API server")
    console.print("  openchimera tui         # Launch the Rust TUI")
    console.print("  openchimera doctor      # Run diagnostics")
    console.print("  openchimera status      # Check configuration")


@cli.command()
def tui() -> None:
    """Launch the Rust TUI (must be compiled first)."""
    import subprocess
    exe = Path(__file__).resolve().parents[3] / "target" / "release" / "openchimera.exe"
    if not exe.exists():
        exe = exe.with_suffix("")
    if not exe.exists():
        console.print("[bold red]TUI binary not found.[/bold red] Run: cargo build --release", style="red")
        console.print("Or install with: iwr -useb .../install.ps1 | iex")
        sys.exit(1)
    subprocess.run([str(exe)])


@cli.command()
@click.option("--production", is_flag=True, help="Include production-readiness checks.")
@click.option("--json", "as_json", is_flag=True, help="Emit a JSON report (always exits 0).")
def doctor(production: bool, as_json: bool) -> None:
    """Run diagnostics — inspired by OpenClaw's doctor command."""
    settings = load_settings()
    if not as_json:
        console.print(Panel.fit("[bold]🔍 OpenChimera Diagnostics[/bold]", border_style="yellow"))

    issues: list[str] = []
    warnings: list[str] = []

    # Check providers
    providers = settings.providers
    enabled = [k for k, v in providers.items() if v.enabled]
    if not enabled:
        issues.append("No providers enabled. Set at least one API key.")

    for name, prov in providers.items():
        if prov.enabled and name not in ("ollama",) and not prov.api_key:
            issues.append(f"Provider '{name}' enabled but missing API key")

    # Check auth
    if settings.api.auth.enabled and not settings.api.auth.token:
        warnings.append("Auth enabled but no API token set")

    # Check optional deps
    chromadb_available = True
    try:
        import chromadb  # noqa: F401
    except ImportError:
        chromadb_available = False
        warnings.append("ChromaDB not installed — RAG uses memory fallback")

    playwright_available = True
    try:
        import playwright  # noqa: F401
    except ImportError:
        playwright_available = False
        warnings.append("Playwright not installed — browser tools unavailable")

    # Check cognitive
    from pathlib import Path as pathlibPath
    axiom_dir = pathlibPath(settings.cognitive.axiom.checkpoints_dir)
    if not axiom_dir.exists():
        warnings.append(f"AXIOM checkpoints dir does not exist: {axiom_dir}")

    production_checks: dict[str, bool] = {}
    production_warnings: list[str] = []
    if production:
        config_dir = Path("config")
        data_dir = Path("data")
        binds_localhost = settings.server.host in ("127.0.0.1", "localhost", "::1")
        production_checks = {
            "config_dir_exists": config_dir.exists(),
            "data_dir_exists": data_dir.exists(),
            "server_binds_localhost": binds_localhost,
            "auth_or_local_bind": bool(settings.api.auth.enabled) or binds_localhost,
            "chromadb_available": chromadb_available,
            "playwright_available": playwright_available,
        }
        if not production_checks["config_dir_exists"]:
            production_warnings.append("config/ directory is missing. Run 'openchimera bootstrap'.")
        if not production_checks["data_dir_exists"]:
            production_warnings.append("data/ directory is missing. Run 'openchimera bootstrap'.")
        if not production_checks["server_binds_localhost"]:
            production_warnings.append("Server binds beyond localhost. Enable API auth before exposing the runtime.")
        if not production_checks["auth_or_local_bind"]:
            production_warnings.append("Runtime is exposed without API auth. Set OPENCHIMERA_API_TOKEN.")
        if not enabled:
            production_warnings.append("No providers enabled. Set at least one API key for production use.")

    if as_json:
        payload = {
            "status": "ok" if not issues and not production_warnings else "warning",
            "version": "2.0.0",
            "issues": issues,
            "warnings": warnings,
            "production": {
                "requested": production,
                "checks": production_checks,
                "warnings": production_warnings,
            } if production else {"requested": False, "checks": {}, "warnings": []},
        }
        print(json.dumps(payload, indent=2))
        return

    if enabled:
        console.print(f"[green]✓[/green] {len(enabled)} provider(s) enabled: {', '.join(enabled)}")
    if chromadb_available:
        console.print("[green]✓[/green] ChromaDB available")
    if playwright_available:
        console.print("[green]✓[/green] Playwright available")
    if axiom_dir.exists():
        console.print("[green]✓[/green] AXIOM checkpoints dir exists")

    # Report
    if issues:
        console.print(f"\n[bold red]✗ {len(issues)} issue(s) found:[/bold red]")
        for i in issues:
            console.print(f"  [red]- {i}[/red]")
    if warnings:
        console.print(f"\n[bold yellow]⚠ {len(warnings)} warning(s):[/bold yellow]")
        for w in warnings:
            console.print(f"  [yellow]- {w}[/yellow]")
    if production:
        console.print("\n[bold]Production checks:[/bold]")
        for check_name, check_value in production_checks.items():
            console.print(f"  {check_name}: {'ok' if check_value else 'missing'}")
        if production_warnings:
            console.print("[bold yellow]Production warnings:[/bold yellow]")
            for w in production_warnings:
                console.print(f"  [yellow]- {w}[/yellow]")

    if not issues and not warnings and not production_warnings:
        console.print("\n[bold green]✅ All checks passed — OpenChimera is ready![/bold green]")
    elif not issues and not production_warnings:
        console.print("\n[bold yellow]⚠ Warnings only — functional but not optimal[/bold yellow]")
    else:
        console.print("\n[bold red]✗ Issues found — please fix before using[/bold red]")
        sys.exit(1)


@cli.group()
def backup() -> None:
    """Create, list, or restore local state backups."""
    pass


def _backup_root() -> Path:
    root = Path.cwd() / "data" / "backups"
    root.mkdir(parents=True, exist_ok=True)
    return root


@backup.command("create")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON output.")
def backup_create(as_json: bool) -> None:
    """Create a timestamped backup of local config state."""
    root = _backup_root()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    archive_name = f"openchimera-{stamp}.zip"
    archive_path = root / archive_name
    manifest = {
        "created_at": stamp,
        "version": "2.0.0",
        "workspace": str(Path.cwd()),
    }
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("manifest.json", json.dumps(manifest, indent=2))
        config_dir = Path.cwd() / "config"
        if config_dir.exists():
            for item in sorted(config_dir.glob("*.yaml")):
                bundle.write(item, arcname=f"config/{item.name}")
    payload = {
        "status": "ok",
        "backup": {
            "file": archive_name,
            "path": str(archive_path),
            "created_at": stamp,
            "size_bytes": archive_path.stat().st_size,
        },
    }
    if as_json:
        print(json.dumps(payload, indent=2))
        return
    console.print(f"[bold green]Created backup: {archive_path}[/bold green]")


@backup.command("list")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON output.")
def backup_list(as_json: bool) -> None:
    """List existing local state backups."""
    root = _backup_root()
    backups = []
    for path in sorted(root.glob("openchimera-*.zip")):
        backups.append(
            {
                "file": path.name,
                "path": str(path),
                "size_bytes": path.stat().st_size,
            }
        )
    if as_json:
        print(json.dumps({"status": "ok", "count": len(backups), "backups": backups}, indent=2))
        return
    console.print(f"Backups: {len(backups)}")
    for item in backups:
        console.print(f"- {item['file']} ({item['size_bytes']} bytes)")


@backup.command("restore")
@click.argument("file", required=False)
@click.option("--json", "as_json", is_flag=True, help="Emit JSON output.")
def backup_restore(file: str | None, as_json: bool) -> None:
    """Restore local state from a backup archive."""
    if not file:
        console.print("[bold red]Backup restore requires a backup file path or file name.[/bold red]")
        sys.exit(2)
    candidate = Path(file)
    if not candidate.is_absolute():
        candidate = _backup_root() / candidate
    if not candidate.exists():
        console.print(f"[bold red]Backup archive not found: {candidate}[/bold red]")
        sys.exit(1)
    with zipfile.ZipFile(candidate, "r") as bundle:
        bundle.extractall(Path.cwd())
    payload = {"status": "ok", "restored_from": str(candidate)}
    if as_json:
        print(json.dumps(payload, indent=2))
        return
    console.print(f"[bold green]Restored local state from: {candidate}[/bold green]")


@cli.command()
@click.argument("text", required=True)
@click.option("--provider", default=None, help="Provider to use")
@click.option("--model", default=None, help="Model to use")
@click.option("--tools", is_flag=True, help="Enable tool execution")
def ask(text: str, provider: str | None, model: str | None, tools: bool) -> None:
    """Send a one-off query to the agent (no server required)."""
    import asyncio
    from openchimera.providers.manager import ProviderManager
    from openchimera.tools.registry import ToolRegistry
    from openchimera.agent import AgentOrchestrator

    async def _ask() -> None:
        settings = load_settings()
        pm = ProviderManager(settings)
        tr = ToolRegistry(settings)
        orch = AgentOrchestrator(pm, tr)
        result = await orch.query(text, provider=provider, model=model, execute_tools=tools)
        console.print(f"[bold cyan]{result.get('provider', '?')} / {result.get('model', '?')}:[/bold cyan]")
        console.print(result.get("text", "No response"))
        if result.get("tools"):
            console.print(f"[dim]Tools executed: {', '.join(result['tools'])}[/dim]")

    asyncio.run(_ask())


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
