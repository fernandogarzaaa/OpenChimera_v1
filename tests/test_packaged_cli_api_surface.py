from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_PACKAGE_PATH = REPO_ROOT / "python"


def _run_packaged_python(code: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PYTHON_PACKAGE_PATH)
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(tempfile.gettempdir()),
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def test_packaged_cli_capabilities_and_config_commands_emit_json() -> None:
    code = """
from click.testing import CliRunner
from openchimera.cli import cli
for args in (["capabilities", "--json"], ["config", "--json"], ["onboard", "--json"], ["tools", "--json"]):
    result = CliRunner().invoke(cli, list(args))
    assert result.exit_code == 0, result.output
    assert result.output.strip().startswith("{"), result.output
"""
    result = _run_packaged_python(code)
    assert result.returncode == 0, result.stdout + result.stderr


def test_packaged_openai_compatible_models_and_chat_endpoints_exist() -> None:
    code = """
from fastapi.testclient import TestClient
from openchimera.api.routes import app
with TestClient(app) as client:
    models = client.get('/v1/models')
    assert models.status_code == 200, models.text
    assert models.json()['object'] == 'list'
    chat = client.post('/v1/chat/completions', json={'model': 'mock', 'messages': [{'role': 'user', 'content': 'hello'}]})
    assert chat.status_code == 200, chat.text
    payload = chat.json()
    assert payload['object'] == 'chat.completion'
    assert payload['choices'][0]['message']['role'] == 'assistant'
"""
    result = _run_packaged_python(code)
    assert result.returncode == 0, result.stdout + result.stderr


def test_packaged_tui_check_reports_missing_binary_as_json() -> None:
    code = """
from click.testing import CliRunner
from openchimera.cli import cli
result = CliRunner().invoke(cli, ['tui', '--check', '--json'])
assert result.output.strip().startswith('{'), result.output
assert result.exit_code in {0, 1}, result.output
"""
    result = _run_packaged_python(code)
    assert result.returncode == 0, result.stdout + result.stderr


def test_packaged_streaming_openai_compatible_chat_returns_clear_400() -> None:
    code = """
from fastapi.testclient import TestClient
from openchimera.api.routes import app
with TestClient(app) as client:
    response = client.post('/v1/chat/completions', json={'model': 'mock', 'stream': True, 'messages': [{'role': 'user', 'content': 'hello'}]})
    assert response.status_code == 400, response.text
    assert 'streaming' in response.json()['detail']
"""
    result = _run_packaged_python(code)
    assert result.returncode == 0, result.stdout + result.stderr
