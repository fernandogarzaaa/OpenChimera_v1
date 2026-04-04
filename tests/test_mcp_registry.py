"""Tests for core.mcp_registry — MCP server registry CRUD and health probe."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.mcp_registry import (
    delete_mcp_registry_entry,
    get_mcp_registry_path,
    get_mcp_health_state_path,
    list_mcp_registry,
    list_mcp_registry_with_health,
    load_mcp_registry,
    load_mcp_health_state,
    upsert_mcp_registry_entry,
    probe_all_mcp_registry_entries,
    probe_mcp_registry_entry,
    _probe_entry,
    _probe_stdio_entry,
)


class TestMcpRegistryPaths(unittest.TestCase):
    def test_registry_path_under_data(self) -> None:
        path = get_mcp_registry_path()
        self.assertEqual(path.name, "mcp_registry.json")

    def test_health_state_path_under_data(self) -> None:
        path = get_mcp_health_state_path()
        self.assertEqual(path.name, "mcp_health_state.json")

    def test_custom_root_overrides_path(self) -> None:
        custom = Path("/tmp/test_root")
        path = get_mcp_registry_path(custom)
        self.assertEqual(path.parent.parent, custom)


class TestLoadMcpRegistry(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        (self.root / "data").mkdir()

    def tearDown(self) -> None:
        self._td.cleanup()

    def _write_registry(self, data: dict) -> None:
        (self.root / "data" / "mcp_registry.json").write_text(json.dumps(data), encoding="utf-8")

    def test_empty_registry_file(self) -> None:
        self._write_registry({"servers": {}})
        result = load_mcp_registry(self.root)
        self.assertEqual(result["servers"], {})

    def test_missing_registry_file_returns_empty(self) -> None:
        result = load_mcp_registry(self.root)
        self.assertEqual(result["servers"], {})

    def test_single_server_normalized(self) -> None:
        self._write_registry({"servers": {
            "my-server": {"transport": "http", "url": "http://localhost:9000"}
        }})
        result = load_mcp_registry(self.root)
        self.assertIn("my-server", result["servers"])
        entry = result["servers"]["my-server"]
        self.assertEqual(entry["id"], "my-server")

    def test_invalid_json_returns_empty(self) -> None:
        (self.root / "data" / "mcp_registry.json").write_text("NOT JSON", encoding="utf-8")
        result = load_mcp_registry(self.root)
        self.assertEqual(result["servers"], {})

    def test_skips_blank_server_ids(self) -> None:
        self._write_registry({"servers": {
            "": {"transport": "http"},
            "  ": {"transport": "stdio"},
            "valid-server": {"transport": "http"},
        }})
        result = load_mcp_registry(self.root)
        self.assertNotIn("", result["servers"])
        self.assertIn("valid-server", result["servers"])


class TestListMcpRegistry(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        (self.root / "data").mkdir()

    def tearDown(self) -> None:
        self._td.cleanup()

    def _write_registry(self, data: dict) -> None:
        (self.root / "data" / "mcp_registry.json").write_text(json.dumps(data), encoding="utf-8")

    def test_list_returns_sorted_by_id(self) -> None:
        self._write_registry({"servers": {
            "zeta": {"transport": "http"},
            "alpha": {"transport": "stdio"},
        }})
        result = list_mcp_registry(self.root)
        ids = [item["id"] for item in result]
        self.assertEqual(ids, sorted(ids))

    def test_list_empty_registry(self) -> None:
        self._write_registry({"servers": {}})
        result = list_mcp_registry(self.root)
        self.assertEqual(result, [])


class TestLoadMcpHealthState(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        (self.root / "data").mkdir()

    def tearDown(self) -> None:
        self._td.cleanup()

    def test_missing_health_file_returns_defaults(self) -> None:
        result = load_mcp_health_state(self.root)
        self.assertEqual(result["servers"], {})
        self.assertEqual(result["version"], 1)

    def test_health_state_loaded(self) -> None:
        data = {"version": 2, "servers": {"s1": {"status": "healthy"}}}
        (self.root / "data" / "mcp_health_state.json").write_text(json.dumps(data), encoding="utf-8")
        result = load_mcp_health_state(self.root)
        self.assertEqual(result["version"], 2)
        self.assertIn("s1", result["servers"])

    def test_invalid_json_health_file_returns_defaults(self) -> None:
        (self.root / "data" / "mcp_health_state.json").write_text("bad json", encoding="utf-8")
        result = load_mcp_health_state(self.root)
        self.assertEqual(result["servers"], {})


class TestListMcpRegistryWithHealth(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        (self.root / "data").mkdir()

    def tearDown(self) -> None:
        self._td.cleanup()

    def test_merges_health_fields_into_registry(self) -> None:
        (self.root / "data" / "mcp_registry.json").write_text(
            json.dumps({"servers": {"s1": {"transport": "http", "url": "http://localhost:9000"}}}),
            encoding="utf-8",
        )
        (self.root / "data" / "mcp_health_state.json").write_text(
            json.dumps({"version": 1, "servers": {"s1": {"status": "healthy", "checked_at": 1234}}}),
            encoding="utf-8",
        )
        result = list_mcp_registry_with_health(self.root)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["status"], "healthy")
        self.assertEqual(result[0]["checked_at"], 1234)

    def test_missing_health_still_returns_server(self) -> None:
        (self.root / "data" / "mcp_registry.json").write_text(
            json.dumps({"servers": {"s2": {"transport": "stdio"}}}),
            encoding="utf-8",
        )
        result = list_mcp_registry_with_health(self.root)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "s2")


class TestUpsertMcpRegistryEntry(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        (self.root / "data").mkdir()

    def tearDown(self) -> None:
        self._td.cleanup()

    def test_upsert_creates_entry(self) -> None:
        result = upsert_mcp_registry_entry(
            "new-server",
            transport="http",
            url="http://localhost:9090",
            root=self.root,
        )
        self.assertEqual(result["id"], "new-server")
        self.assertTrue((self.root / "data" / "mcp_registry.json").exists())

    def test_upsert_updates_existing_entry(self) -> None:
        upsert_mcp_registry_entry("s1", transport="http", url="http://old", root=self.root)
        upsert_mcp_registry_entry("s1", transport="http", url="http://new", root=self.root)
        entries = list_mcp_registry(self.root)
        entry = next(e for e in entries if e["id"] == "s1")
        self.assertEqual(entry.get("url"), "http://new")

    def test_upsert_stdio_transport(self) -> None:
        result = upsert_mcp_registry_entry(
            "stdio-server",
            transport="stdio",
            command="python",
            args=["-m", "my_mcp_server"],
            root=self.root,
        )
        self.assertEqual(result["transport"], "stdio")


class TestDeleteMcpRegistryEntry(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        (self.root / "data").mkdir()

    def tearDown(self) -> None:
        self._td.cleanup()

    def test_delete_removes_entry(self) -> None:
        upsert_mcp_registry_entry("to-delete", transport="stdio", command="python", root=self.root)
        result = delete_mcp_registry_entry("to-delete", root=self.root)
        self.assertEqual(result.get("id"), "to-delete")
        entries = list_mcp_registry(self.root)
        ids = [e["id"] for e in entries]
        self.assertNotIn("to-delete", ids)

    def test_delete_nonexistent_returns_not_found(self) -> None:
        result = delete_mcp_registry_entry("ghost", root=self.root)
        self.assertFalse(result.get("deleted", True))


class TestUpsertValidation(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        (self.root / "data").mkdir()

    def tearDown(self) -> None:
        self._td.cleanup()

    def test_upsert_raises_for_empty_server_id(self) -> None:
        with self.assertRaises(ValueError):
            upsert_mcp_registry_entry("", transport="http", url="http://localhost", root=self.root)

    def test_upsert_raises_for_unknown_transport(self) -> None:
        with self.assertRaises(ValueError):
            upsert_mcp_registry_entry("s", transport="grpc", url="grpc://localhost", root=self.root)

    def test_upsert_raises_for_http_without_url(self) -> None:
        with self.assertRaises(ValueError):
            upsert_mcp_registry_entry("s", transport="http", root=self.root)

    def test_upsert_raises_for_stdio_without_command(self) -> None:
        with self.assertRaises(ValueError):
            upsert_mcp_registry_entry("s", transport="stdio", root=self.root)

    def test_upsert_with_description_sets_field(self) -> None:
        result = upsert_mcp_registry_entry(
            "described-server",
            transport="http",
            url="http://localhost:8080",
            description="A helpful MCP server",
            root=self.root,
        )
        self.assertEqual(result["description"], "A helpful MCP server")


class TestProbeEntries(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        (self.root / "data").mkdir()

    def tearDown(self) -> None:
        self._td.cleanup()

    def test_probe_all_empty_registry_returns_zero_counts(self) -> None:
        result = probe_all_mcp_registry_entries(root=self.root)
        self.assertEqual(result["counts"]["total"], 0)
        self.assertEqual(result["counts"]["healthy"], 0)
        self.assertIn("servers", result)

    def test_probe_entry_disabled_returns_disabled_status(self) -> None:
        entry = {"id": "disabled-server", "enabled": False, "transport": "http", "url": "http://localhost:9999"}
        result = _probe_entry(entry, timeout_seconds=1.0)
        self.assertEqual(result["status"], "disabled")
        self.assertEqual(result["id"], "disabled-server")

    def test_probe_entry_unknown_transport_returns_degraded(self) -> None:
        entry = {"id": "unknown-srv", "enabled": True, "transport": "grpc"}
        result = _probe_entry(entry, timeout_seconds=1.0)
        self.assertEqual(result["status"], "degraded")
        self.assertIn("Unsupported transport", result["last_error"])

    def test_probe_stdio_with_python_command_resolves(self) -> None:
        import shutil
        python_path = shutil.which("python")
        if python_path is None:
            self.skipTest("python not on PATH")
        entry = {"id": "python-server", "enabled": True, "transport": "stdio", "command": "python"}
        result = _probe_stdio_entry(entry)
        self.assertEqual(result["status"], "healthy")
        self.assertIn("resolved_command", result)

    def test_probe_stdio_with_missing_command_returns_degraded(self) -> None:
        entry = {"id": "missing-cmd", "enabled": True, "transport": "stdio", "command": "no-such-command-xyz-123"}
        result = _probe_stdio_entry(entry)
        self.assertEqual(result["status"], "degraded")
        self.assertIn("last_error", result)

    def test_probe_all_with_disabled_server_counts_disabled(self) -> None:
        upsert_mcp_registry_entry(
            "disabled-entry",
            transport="http",
            url="http://localhost:19999",
            enabled=False,
            root=self.root,
        )
        result = probe_all_mcp_registry_entries(root=self.root)
        self.assertEqual(result["counts"]["total"], 1)
        self.assertEqual(result["counts"]["disabled"], 1)

    def test_probe_mcp_registry_entry_raises_for_unknown_id(self) -> None:
        with self.assertRaises(ValueError):
            probe_mcp_registry_entry("nonexistent-id", root=self.root)

    def test_probe_mcp_registry_entry_disabled_returns_disabled(self) -> None:
        upsert_mcp_registry_entry(
            "my-disabled",
            transport="http",
            url="http://localhost:19999",
            enabled=False,
            root=self.root,
        )
        result = probe_mcp_registry_entry("my-disabled", root=self.root)
        self.assertEqual(result["status"], "disabled")


class TestEdgeCaseBranches(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        (self.root / "data").mkdir()

    def tearDown(self) -> None:
        self._td.cleanup()

    def test_load_mcp_registry_skips_non_dict_server_values(self) -> None:
        (self.root / "data" / "mcp_registry.json").write_text(
            json.dumps({"servers": {"valid": {"transport": "http"}, "invalid": "string-not-dict"}}),
            encoding="utf-8",
        )
        result = load_mcp_registry(self.root)
        self.assertIn("valid", result["servers"])
        self.assertNotIn("invalid", result["servers"])

    def test_load_mcp_health_state_non_dict_servers_returns_empty(self) -> None:
        (self.root / "data" / "mcp_health_state.json").write_text(
            json.dumps({"version": 1, "servers": ["not", "a", "dict"]}),
            encoding="utf-8",
        )
        result = load_mcp_health_state(self.root)
        self.assertEqual(result["servers"], {})


if __name__ == "__main__":
    unittest.main()
