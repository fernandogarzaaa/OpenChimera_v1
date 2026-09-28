from click.testing import CliRunner
from fastapi.testclient import TestClient
from openchimera.api.routes import app

from openchimera.cli import cli


def test_cli_capabilities_and_config_commands_emit_json():
    runner = CliRunner()
    for args in (["capabilities", "--json"], ["config", "--json"], ["onboard", "--json"], ["tools", "--json"]):
        result = runner.invoke(cli, list(args))
        assert result.exit_code == 0, result.output
        assert result.output.strip().startswith("{")


def test_openai_compatible_models_and_chat_endpoints_exist():
    with TestClient(app) as client:
        models = client.get("/v1/models")
        assert models.status_code == 200
        assert models.json()["object"] == "list"
        chat = client.post(
            "/v1/chat/completions",
            json={"model": "mock", "messages": [{"role": "user", "content": "hello"}]},
        )
        assert chat.status_code == 200
        payload = chat.json()
        assert payload["object"] == "chat.completion"
        assert payload["choices"][0]["message"]["role"] == "assistant"


def test_tui_check_reports_missing_binary_as_json():
    runner = CliRunner()
    result = runner.invoke(cli, ["tui", "--check", "--json"])
    assert result.output.strip().startswith("{")
    # In source checkouts without a compiled TUI the command intentionally exits 1.
    assert result.exit_code in {0, 1}


def test_streaming_openai_compatible_chat_returns_clear_400():
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"model": "mock", "stream": True, "messages": [{"role": "user", "content": "hello"}]},
        )
        assert response.status_code == 400
        assert "streaming" in response.json()["detail"]
