"""Tests for the google-genai SDK migration in python/openchimera/providers/manager.py.

Loads manager.py from its file path with stubbed sibling packages and a fake
``google.genai`` module, so the tests need no network and no real SDK install.
They assert behavior: how messages map to the new SDK's contents, how sampling
settings map to GenerateContentConfig, the unchanged return contract, and the
unchanged health-check semantics.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types as stdlib_types
from pathlib import Path
from typing import Any

import pytest

MANAGER_PATH = Path(__file__).resolve().parent.parent / "python" / "openchimera" / "providers" / "manager.py"


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeGenerateContentConfig:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs


class _FakeTypes:
    GenerateContentConfig = _FakeGenerateContentConfig


class _FakeModels:
    def __init__(self, client: "_FakeClient") -> None:
        self._client = client

    async def generate_content(self, **kwargs: Any) -> _FakeResponse:
        self._client.calls.append(kwargs)
        if self._client.error is not None:
            raise self._client.error
        return self._client.response


class _FakeAio:
    def __init__(self, client: "_FakeClient") -> None:
        self.models = _FakeModels(client)
        self.aclose_calls = 0

    async def aclose(self) -> None:
        self.aclose_calls += 1


class _FakeClient:
    instances: list["_FakeClient"] = []
    fail_construct = False

    def __init__(self, api_key: str | None = None) -> None:
        if _FakeClient.fail_construct:
            raise RuntimeError("no client")
        self.api_key = api_key
        self.calls: list[dict[str, Any]] = []
        self.response = _FakeResponse("hello from gemini")
        self.error: Exception | None = None
        self.aio = _FakeAio(self)
        _FakeClient.instances.append(self)


class _FakeGenaiModule(stdlib_types.ModuleType):
    Client = _FakeClient
    types = _FakeTypes()


class _BaseProvider:
    name = "base"
    profile = None

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "",
        default_model: str = "",
        config: Any = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.default_model = default_model or ""
        self.config = config
        self._healthy: bool | None = None
        self._latency_ms: int | None = None
        self._models: list[str] = []


@pytest.fixture()
def manager_module():
    """Load manager.py with stubbed imports and a fake google.genai SDK."""
    saved = dict(sys.modules)
    try:
        fake_genai = _FakeGenaiModule("google.genai")
        google_pkg = stdlib_types.ModuleType("google")
        google_pkg.__path__ = []  # type: ignore[attr-defined]
        google_pkg.genai = fake_genai
        sys.modules["google"] = google_pkg
        sys.modules["google.genai"] = fake_genai

        oc_pkg = stdlib_types.ModuleType("openchimera")
        oc_pkg.__path__ = []  # type: ignore[attr-defined]
        sys.modules["openchimera"] = oc_pkg

        config_mod = stdlib_types.ModuleType("openchimera.config")
        config_mod.ProvidersConfig = type("ProvidersConfig", (), {})
        config_mod.Settings = type("Settings", (), {})
        sys.modules["openchimera.config"] = config_mod

        prov_pkg = stdlib_types.ModuleType("openchimera.providers")
        prov_pkg.__path__ = []  # type: ignore[attr-defined]
        sys.modules["openchimera.providers"] = prov_pkg

        base_mod = stdlib_types.ModuleType("openchimera.providers.base")
        base_mod.BaseProvider = _BaseProvider
        base_mod.get_profile = lambda name: None
        sys.modules["openchimera.providers.base"] = base_mod

        _FakeClient.instances.clear()

        spec = importlib.util.spec_from_file_location("openchimera.providers.manager", MANAGER_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["openchimera.providers.manager"] = module
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.clear()
        sys.modules.update(saved)


def _google(manager_module, api_key: str = "secret", model: str = "gemini-2.5-flash"):
    return manager_module.GoogleProvider(api_key=api_key, default_model=model)


def test_chat_maps_user_and_assistant_messages(manager_module):
    provider = _google(manager_module)
    messages = [
        {"role": "system", "content": "dropped as before"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "there"},
    ]
    result = asyncio.run(provider.chat(messages))

    client = _FakeClient.instances[-1]
    assert client.api_key == "secret"
    call = client.calls[0]
    assert call["model"] == "gemini-2.5-flash"
    assert call["contents"] == ["hi", {"role": "model", "parts": [{"text": "there"}]}]
    assert "config" not in call
    assert result == {
        "text": "hello from gemini",
        "tool_calls": [],
        "provider": "google",
        "model": "gemini-2.5-flash",
    }
    assert provider._healthy is True
    assert isinstance(provider._latency_ms, int)


def test_chat_maps_temperature_and_max_tokens_to_config(manager_module):
    provider = _google(manager_module)
    asyncio.run(provider.chat([{"role": "user", "content": "hi"}], temperature=0.5, max_tokens=100))

    call = _FakeClient.instances[-1].calls[0]
    config = call["config"]
    assert isinstance(config, _FakeGenerateContentConfig)
    assert config.kwargs == {"temperature": 0.5, "max_output_tokens": 100}


def test_chat_uses_explicit_model(manager_module):
    provider = _google(manager_module)
    asyncio.run(provider.chat([{"role": "user", "content": "hi"}], model="gemini-2.0-flash"))

    call = _FakeClient.instances[-1].calls[0]
    assert call["model"] == "gemini-2.0-flash"


def test_chat_error_path_keeps_contract(manager_module):
    provider = _google(manager_module)

    real_init = _FakeClient.__init__

    def failing_init(self, api_key=None):
        real_init(self, api_key=api_key)
        self.error = RuntimeError("boom")

    _FakeClient.__init__ = failing_init  # type: ignore[method-assign]
    try:
        result = asyncio.run(provider.chat([{"role": "user", "content": "hi"}]))
    finally:
        _FakeClient.__init__ = real_init  # type: ignore[method-assign]

    assert result["text"] == "Error: boom"
    assert result["tool_calls"] == []
    assert result["provider"] == "google"
    assert provider._healthy is False
    assert _FakeClient.instances[-1].aio.aclose_calls == 1


def test_chat_constructor_failure_keeps_contract(manager_module):
    provider = _google(manager_module)
    _FakeClient.fail_construct = True
    try:
        result = asyncio.run(provider.chat([{"role": "user", "content": "hi"}]))
    finally:
        _FakeClient.fail_construct = False

    assert result["text"] == "Error: no client"
    assert result["tool_calls"] == []
    assert provider._healthy is False


def test_chat_closes_client_on_success(manager_module):
    provider = _google(manager_module)
    asyncio.run(provider.chat([{"role": "user", "content": "hi"}]))
    assert _FakeClient.instances[-1].aio.aclose_calls == 1


def test_health_check_keeps_semantics(manager_module):
    provider = _google(manager_module)
    ok = asyncio.run(provider.health_check())

    assert ok is True
    assert provider._healthy is True
    call = _FakeClient.instances[-1].calls[0]
    assert call == {"model": "gemini-2.5-flash", "contents": "hello"}
    assert _FakeClient.instances[-1].aio.aclose_calls == 1


def test_health_check_error_path(manager_module):
    provider = _google(manager_module)

    real_init = _FakeClient.__init__

    def failing_init(self, api_key=None):
        real_init(self, api_key=api_key)
        self.error = RuntimeError("down")

    _FakeClient.__init__ = failing_init  # type: ignore[method-assign]
    try:
        ok = asyncio.run(provider.health_check())
    finally:
        _FakeClient.__init__ = real_init  # type: ignore[method-assign]

    assert ok is False
    assert provider._healthy is False
    assert _FakeClient.instances[-1].aio.aclose_calls == 1


def test_chat_records_elapsed_latency_in_ms(manager_module):
    from unittest import mock

    provider = _google(manager_module)
    with mock.patch("time.perf_counter", side_effect=[100.0, 100.25]):
        asyncio.run(provider.chat([{"role": "user", "content": "hi"}]))
    assert provider._latency_ms == 250

    with mock.patch("time.perf_counter", side_effect=[0.0, 0.0019995]):
        asyncio.run(provider.chat([{"role": "user", "content": "hi"}]))
    assert provider._latency_ms == 1
