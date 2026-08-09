"""OpenChimera v2 CLI — inspired by OpenClaw and Hermes Agent onboarding."""

from __future__ import annotations

import sys
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
def status() -> None:
    """Show runtime status."""
    settings = load_settings()
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
def doctor() -> None:
    """Run diagnostics — inspired by OpenClaw's doctor command."""
    settings = load_settings()
    console.print(Panel.fit("[bold]🔍 OpenChimera Diagnostics[/bold]", border_style="yellow"))

    issues: list[str] = []
    warnings: list[str] = []

    # Check providers
    providers = settings.providers
    enabled = [k for k, v in providers.items() if v.enabled]
    if not enabled:
        issues.append("No providers enabled. Set at least one API key.")
    else:
        console.print(f"[green]✓[/green] {len(enabled)} provider(s) enabled: {', '.join(enabled)}")

    for name, prov in providers.items():
        if prov.enabled and name not in ("ollama",) and not prov.api_key:
            issues.append(f"Provider '{name}' enabled but missing API key")

    # Check auth
    if settings.api.auth.enabled and not settings.api.auth.token:
        warnings.append("Auth enabled but no API token set")

    # Check optional deps
    try:
        import chromadb
        console.print("[green]✓[/green] ChromaDB available")
    except ImportError:
        warnings.append("ChromaDB not installed — RAG uses memory fallback")

    try:
        import playwright
        console.print("[green]✓[/green] Playwright available")
    except ImportError:
        warnings.append("Playwright not installed — browser tools unavailable")

    # Check cognitive
    from pathlib import Path as pathlibPath
    axiom_dir = pathlibPath(settings.cognitive.axiom.checkpoints_dir)
    if not axiom_dir.exists():
        warnings.append(f"AXIOM checkpoints dir does not exist: {axiom_dir}")
    else:
        console.print(f"[green]✓[/green] AXIOM checkpoints dir exists")

    # Report
    if issues:
        console.print(f"\n[bold red]✗ {len(issues)} issue(s) found:[/bold red]")
        for i in issues:
            console.print(f"  [red]- {i}[/red]")
    if warnings:
        console.print(f"\n[bold yellow]⚠ {len(warnings)} warning(s):[/bold yellow]")
        for w in warnings:
            console.print(f"  [yellow]- {w}[/yellow]")

    if not issues and not warnings:
        console.print("\n[bold green]✅ All checks passed — OpenChimera is ready![/bold green]")
    elif not issues:
        console.print("\n[bold yellow]⚠ Warnings only — functional but not optimal[/bold yellow]")
    else:
        console.print("\n[bold red]✗ Issues found — please fix before using[/bold red]")
        sys.exit(1)


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
