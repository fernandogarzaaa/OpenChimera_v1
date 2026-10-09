"""Standard vendor API-key env vars (as documented in README) enable providers."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_PACKAGE_PATH = REPO_ROOT / "python"
_KEY_VARS = ("OPENAI_API_KEY", "OPENAI_BASE_URL", "GROQ_API_KEY", "ANTHROPIC_API_KEY")


def _run(code: str, extra_env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in _KEY_VARS and not k.startswith("OPENCHIMERA_")}
    env["PYTHONPATH"] = str(PYTHON_PACKAGE_PATH)
    env["OPENCHIMERA_CONFIG"] = (REPO_ROOT / "config" / "default.yaml").as_posix()
    env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(tempfile.gettempdir()),
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )


def test_openai_api_key_env_enables_provider_and_base_url() -> None:
    code = """
from openchimera.config import load_settings
s = load_settings(force_reload=True)
assert s.providers.openai.enabled is True
assert s.providers.openai.api_key == 'sk-test-dummy'
assert s.providers.openai.base_url == 'http://127.0.0.1:9/v1'
assert s.providers.anthropic.enabled is False
"""
    result = _run(code, {"OPENAI_API_KEY": "sk-test-dummy", "OPENAI_BASE_URL": "http://127.0.0.1:9/v1"})
    assert result.returncode == 0, result.stdout + result.stderr


def test_openchimera_prefixed_env_still_wins_over_vendor_env() -> None:
    code = """
from openchimera.config import load_settings
s = load_settings(force_reload=True)
assert s.providers.groq.enabled is False
assert s.providers.groq.default_model == 'pinned'
"""
    result = _run(
        code,
        {
            "GROQ_API_KEY": "gsk-test-dummy",
            "OPENCHIMERA_PROVIDERS__GROQ__ENABLED": "false",
            "OPENCHIMERA_PROVIDERS__GROQ__DEFAULT_MODEL": "pinned",
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_query_without_any_provider_returns_hint_instead_of_raising() -> None:
    code = """
import asyncio
from openchimera.config import load_settings
from openchimera.agent import AgentOrchestrator
from openchimera.providers.manager import ProviderManager
from openchimera.tools.registry import ToolRegistry
s = load_settings(force_reload=True)
orch = AgentOrchestrator(ProviderManager(s), ToolRegistry(s))
out = asyncio.run(orch.query('hi', provider=None, model=None, execute_tools=False))
assert out['provider'] == 'none', out
assert 'onboard' in out['text']
"""
    result = _run(code, {})
    assert result.returncode == 0, result.stdout + result.stderr
