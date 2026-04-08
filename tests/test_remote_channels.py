"""Tests for core.remote_channels — Remote channel manager and transport stubs.

Covers:
  1. ChannelInfo.to_dict() structure
  2. RemoteChannel base class lifecycle (start/stop)
  3. RemoteChannel._dispatch_command with no handler
  4. RemoteChannel._dispatch_command with handler
  5. TelegramChannel init reads credentials
  6. DiscordChannel init reads credentials
  7. SlackChannel init reads credentials
  8. WebhookChannel init reads credentials
  9. RemoteChannelManager.boot_enabled_channels skips disabled
  10. RemoteChannelManager.status() structure
  11. RemoteChannelManager.stop_all clears channels
  12. CHANNEL_CLASSES maps correct IDs
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.remote_channels import (
    CHANNEL_CLASSES,
    ChannelInfo,
    ChannelStatus,
    DiscordChannel,
    RemoteChannel,
    RemoteChannelManager,
    SlackChannel,
    TelegramChannel,
    WebhookChannel,
)


def _mock_creds(data: dict[str, dict[str, str]] | None = None) -> MagicMock:
    """Build a mock CredentialStore returning *data* for get_provider_credentials."""
    store = MagicMock()
    mapping = data or {}
    store.get_provider_credentials.side_effect = lambda pid: mapping.get(pid, {})
    return store


# 1. ChannelInfo.to_dict()
def test_channel_info_to_dict() -> None:
    info = ChannelInfo(channel_id="test", display_name="Test")
    d = info.to_dict()
    assert d["channel_id"] == "test"
    assert d["display_name"] == "Test"
    assert d["status"] == "stopped"
    assert d["messages_received"] == 0
    assert d["messages_sent"] == 0


# 2. RemoteChannel lifecycle — start raises because base _run_loop is abstract
def test_base_channel_run_loop_raises() -> None:
    class StubChannel(RemoteChannel):
        channel_id = "stub"
        display_name = "Stub"

    ch = StubChannel(credential_store=_mock_creds())
    # _run_loop should raise
    with pytest.raises(NotImplementedError):
        ch._run_loop()


# 3. dispatch_command with no handler
def test_dispatch_no_handler() -> None:
    class StubChannel(RemoteChannel):
        channel_id = "stub"
        display_name = "Stub"

    ch = StubChannel(credential_store=_mock_creds())
    result = ch._dispatch_command("hello")
    assert result["ok"] is False
    assert "No command handler" in result["error"]
    assert ch.info.messages_received == 1


# 4. dispatch_command with handler
def test_dispatch_with_handler() -> None:
    class StubChannel(RemoteChannel):
        channel_id = "stub"
        display_name = "Stub"

    ch = StubChannel(credential_store=_mock_creds())
    ch.set_command_handler(lambda text, meta: {"ok": True, "response": f"echo:{text}"})
    result = ch._dispatch_command("hello")
    assert result["ok"] is True
    assert result["response"] == "echo:hello"
    assert ch.info.messages_sent == 1


# 5. TelegramChannel reads creds
def test_telegram_reads_creds() -> None:
    creds = _mock_creds({"telegram": {"bot_token": "tok123", "allowed_user": "alice"}})
    ch = TelegramChannel(credential_store=creds)
    assert ch._bot_token == "tok123"
    assert "alice" in ch._paired_users


# 6. DiscordChannel reads creds
def test_discord_reads_creds() -> None:
    creds = _mock_creds({"discord": {"bot_token": "dtok", "guild_id": "1234"}})
    ch = DiscordChannel(credential_store=creds)
    assert ch._bot_token == "dtok"
    assert ch._guild_id == "1234"


# 7. SlackChannel reads creds
def test_slack_reads_creds() -> None:
    creds = _mock_creds({"slack": {"bot_token": "xoxb-test", "app_token": "xapp-test"}})
    ch = SlackChannel(credential_store=creds)
    assert ch._bot_token == "xoxb-test"
    assert ch._app_token == "xapp-test"


# 8. WebhookChannel reads creds
def test_webhook_reads_creds() -> None:
    creds = _mock_creds({"webhook": {"endpoint_url": "https://example.com/hook", "signing_secret": "s3cret"}})
    ch = WebhookChannel(credential_store=creds)
    assert ch._endpoint == "https://example.com/hook"
    assert ch._signing_secret == "s3cret"


# 9. Manager skips disabled channels
def test_manager_skips_disabled() -> None:
    creds = _mock_creds()
    mgr = RemoteChannelManager(credential_store=creds)
    # All channels are disabled by default in the registry
    with patch("core.remote_channels.get_registry") as mock_reg:
        mock_reg.return_value.is_enabled.return_value = False
        booted = mgr.boot_enabled_channels()
    assert booted == []


# 10. Manager status structure
def test_manager_status_empty() -> None:
    creds = _mock_creds()
    mgr = RemoteChannelManager(credential_store=creds)
    s = mgr.status()
    assert "channels" in s
    assert "active_count" in s
    assert s["active_count"] == 0


# 11. Manager stop_all clears channels
def test_manager_stop_all() -> None:
    creds = _mock_creds()
    mgr = RemoteChannelManager(credential_store=creds)
    mgr.stop_all()
    assert mgr.status()["active_count"] == 0


# 12. CHANNEL_CLASSES has correct IDs
def test_channel_classes_mapping() -> None:
    expected = {"remote_telegram", "remote_discord", "remote_slack", "remote_webhook"}
    assert set(CHANNEL_CLASSES.keys()) == expected
    assert CHANNEL_CLASSES["remote_telegram"] is TelegramChannel
    assert CHANNEL_CLASSES["remote_discord"] is DiscordChannel
    assert CHANNEL_CLASSES["remote_slack"] is SlackChannel
    assert CHANNEL_CLASSES["remote_webhook"] is WebhookChannel
