"""OpenChimera v2 CLI."""

import argparse
import asyncio
import sys
from pathlib import Path

import click

from openchimera.config import load_settings
from openchimera.server import start_server


@click.group()
@click.version_option(version="2.0.0", prog_name="openchimera")
def cli() -> None:
    """OpenChimera v2 — Agentic orchestration runtime."""
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
    click.echo(f"🚀 Starting OpenChimera v2 on http://{bind_host}:{bind_port}")
    start_server(host=bind_host, port=bind_port, reload=reload)


@cli.command()
def status() -> None:
    """Show runtime status."""
    settings = load_settings()
    click.echo(f"OpenChimera v2")
    click.echo(f"Config loaded: {settings.config_path}")
    click.echo(f"Server: {settings.server.host}:{settings.server.port}")
    click.echo(f"Providers: {len([p for p in settings.providers.values() if p.enabled])} enabled")
    click.echo(f"Cognitive: AXIOM={settings.cognitive.axiom.enabled} EVE={settings.cognitive.eve.enabled} ADAM={settings.cognitive.adam.enabled}")


@cli.command()
def tui() -> None:
    """Launch the Rust TUI (must be compiled first)."""
    import subprocess
    exe = Path(__file__).resolve().parents[3] / "target" / "release" / "openchimera.exe"
    if not exe.exists():
        exe = exe.with_suffix("")
    if not exe.exists():
        click.echo("TUI binary not found. Run: cargo build --release", err=True)
        sys.exit(1)
    subprocess.run([str(exe)])


@cli.command()
def doctor() -> None:
    """Run diagnostics."""
    settings = load_settings()
    click.echo("🔍 Running diagnostics...")
    issues = []
    if settings.api.auth.enabled and not settings.api.auth.token:
        issues.append("Auth enabled but no API token set")
    providers = settings.providers
    enabled = [k for k, v in providers.items() if v.enabled]
    if not enabled:
        issues.append("No providers enabled")
    for name, prov in providers.items():
        if prov.enabled and name not in ("ollama",) and not prov.api_key:
            issues.append(f"Provider '{name}' enabled but missing API key")
    if issues:
        click.echo("⚠️  Issues found:")
        for i in issues:
            click.echo(f"  - {i}")
    else:
        click.echo("✅ All checks passed")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
