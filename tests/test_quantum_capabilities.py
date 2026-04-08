"""Tests for core.quantum_capabilities — Quantum capability registry.

Covers:
  1. Registry initializes with built-in capabilities
  2. 50% tier capabilities enabled by default
  3. 100% tier capabilities disabled by default
  4. enable() / disable() toggle capabilities
  5. enable() returns False for unknown capability
  6. current_tier() returns human-readable string
  7. enabled_cloud_providers() only lists enabled auth providers
  8. enabled_remote_channels() only lists enabled channels
  9. status() returns structured dict
  10. list_all() returns dicts with enabled field
  11. list_by_category() returns grouped dict
  12. Persistence round-trip via save/load
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.quantum_capabilities import (
    BUILT_IN_CAPABILITIES,
    CATEGORY_CHANNEL,
    CATEGORY_INFERENCE,
    CapabilitySpec,
    QuantumCapabilityRegistry,
)


@pytest.fixture
def registry(tmp_path: Path) -> QuantumCapabilityRegistry:
    """Fresh registry with a temp config path so tests don't pollute real config."""
    return QuantumCapabilityRegistry(capabilities_file=tmp_path / "quantum_capabilities.json")


# 1. Registry has built-in capabilities
def test_registry_has_builtins(registry: QuantumCapabilityRegistry) -> None:
    all_caps = registry.list_all()
    assert len(all_caps) >= len(BUILT_IN_CAPABILITIES)
    ids = [c["capability_id"] for c in all_caps]
    for cap_id in BUILT_IN_CAPABILITIES:
        assert cap_id in ids


# 2. 50% tier is enabled by default
def test_50_pct_enabled_by_default(registry: QuantumCapabilityRegistry) -> None:
    assert registry.is_enabled("quantum_engine_50") is True


# 3. 100% tier is disabled by default
def test_100_pct_disabled_by_default(registry: QuantumCapabilityRegistry) -> None:
    assert registry.is_enabled("quantum_engine_100") is False


# 4. enable() / disable() toggling
def test_enable_disable(registry: QuantumCapabilityRegistry) -> None:
    assert registry.is_enabled("quantum_engine_100") is False
    registry.enable("quantum_engine_100")
    assert registry.is_enabled("quantum_engine_100") is True
    registry.disable("quantum_engine_100")
    assert registry.is_enabled("quantum_engine_100") is False


# 5. enable() returns False for unknown capability
def test_enable_unknown(registry: QuantumCapabilityRegistry) -> None:
    assert registry.enable("nonexistent_capability") is False


# 6. current_tier() reflects enabled state
def test_current_tier(registry: QuantumCapabilityRegistry) -> None:
    assert "50%" in registry.current_tier()
    registry.enable("quantum_engine_100")
    assert "100%" in registry.current_tier()


# 7. enabled_cloud_providers() filters correctly
def test_enabled_cloud_providers(registry: QuantumCapabilityRegistry) -> None:
    # When 100% is off, no cloud providers
    providers = registry.enabled_cloud_providers()
    assert isinstance(providers, list)
    assert len(providers) == 0
    # Enable 100% → should return provider list
    registry.enable("quantum_engine_100")
    providers = registry.enabled_cloud_providers()
    assert len(providers) > 0


# 8. enabled_remote_channels() filters correctly
def test_enabled_remote_channels(registry: QuantumCapabilityRegistry) -> None:
    channels = registry.enabled_remote_channels()
    assert isinstance(channels, list)
    assert len(channels) == 0
    # Enable telegram
    registry.enable("remote_telegram")
    channels = registry.enabled_remote_channels()
    assert any(c.capability_id == "remote_telegram" for c in channels)


# 9. status() returns structured dict
def test_status_structure(registry: QuantumCapabilityRegistry) -> None:
    s = registry.status()
    assert isinstance(s, dict)
    assert "quantum_tier" in s
    assert "capabilities" in s


# 10. list_all() returns dicts with enabled field
def test_list_all(registry: QuantumCapabilityRegistry) -> None:
    all_caps = registry.list_all()
    assert all(isinstance(c, dict) for c in all_caps)
    assert all("enabled" in c for c in all_caps)


# 11. list_by_category() returns grouped dict
def test_list_by_category(registry: QuantumCapabilityRegistry) -> None:
    grouped = registry.list_by_category()
    assert isinstance(grouped, dict)
    assert CATEGORY_INFERENCE in grouped


# 12. Persistence save/load round-trip
def test_persistence_round_trip(tmp_path: Path) -> None:
    f = tmp_path / "quantum_caps.json"
    r1 = QuantumCapabilityRegistry(capabilities_file=f)
    r1.enable("quantum_engine_100")
    r1.enable("remote_discord")

    # Create a new registry from the same file
    r2 = QuantumCapabilityRegistry(capabilities_file=f)
    assert r2.is_enabled("quantum_engine_100") is True
    assert r2.is_enabled("remote_discord") is True