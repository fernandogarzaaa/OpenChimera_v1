"""Tests for core.plugin_manifest — PluginManifest, validate_manifest, load_manifest, from_dict."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core.plugin_manifest import (
    PluginManifest,
    from_dict,
    load_manifest,
    validate_manifest,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MINIMAL_DATA = {"id": "my-plugin", "name": "My Plugin", "version": "1.0.0"}

_FULL_DATA = {
    "id": "full-plugin",
    "name": "Full Plugin",
    "version": "2.1.0",
    "description": "A comprehensive plugin",
    "author": "Alice",
    "url": "https://example.com",
    "tools": ["tool-a", "tool-b"],
    "skills": ["skill-x"],
    "commands": ["cmd-alpha"],
    "mcp_servers": [{"id": "my-mcp", "transport": "http", "url": "http://localhost:9000"}],
    "tags": ["core", "extended"],
    "custom_extra": "extra-value",
}


def _write_manifest(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# validate_manifest
# ---------------------------------------------------------------------------

class TestValidateManifest(unittest.TestCase):
    def test_valid_minimal_manifest_returns_no_errors(self):
        errors = validate_manifest(dict(_MINIMAL_DATA))
        self.assertEqual(errors, [])

    def test_valid_full_manifest_returns_no_errors(self):
        errors = validate_manifest(dict(_FULL_DATA))
        self.assertEqual(errors, [])

    def test_non_dict_returns_error(self):
        errors = validate_manifest([])  # type: ignore[arg-type]
        self.assertGreater(len(errors), 0)

    def test_missing_id_returns_error(self):
        data = {k: v for k, v in _MINIMAL_DATA.items() if k != "id"}
        errors = validate_manifest(data)
        self.assertTrue(any("id" in e for e in errors))

    def test_missing_name_returns_error(self):
        data = {k: v for k, v in _MINIMAL_DATA.items() if k != "name"}
        errors = validate_manifest(data)
        self.assertTrue(any("name" in e for e in errors))

    def test_missing_version_returns_error(self):
        data = {k: v for k, v in _MINIMAL_DATA.items() if k != "version"}
        errors = validate_manifest(data)
        self.assertTrue(any("version" in e for e in errors))

    def test_empty_id_returns_error(self):
        data = {**_MINIMAL_DATA, "id": ""}
        errors = validate_manifest(data)
        self.assertTrue(any("id" in e for e in errors))

    def test_tools_non_list_returns_error(self):
        data = {**_MINIMAL_DATA, "tools": "not-a-list"}
        errors = validate_manifest(data)
        self.assertTrue(any("tools" in e for e in errors))

    def test_skills_non_list_returns_error(self):
        data = {**_MINIMAL_DATA, "skills": "not-a-list"}
        errors = validate_manifest(data)
        self.assertTrue(any("skills" in e for e in errors))

    def test_commands_non_list_returns_error(self):
        data = {**_MINIMAL_DATA, "commands": "not-a-list"}
        errors = validate_manifest(data)
        self.assertTrue(any("commands" in e for e in errors))

    def test_tags_non_list_returns_error(self):
        data = {**_MINIMAL_DATA, "tags": "not-a-list"}
        errors = validate_manifest(data)
        self.assertTrue(any("tags" in e for e in errors))

    def test_mcp_servers_non_list_returns_error(self):
        data = {**_MINIMAL_DATA, "mcp_servers": {"id": "x"}}
        errors = validate_manifest(data)
        self.assertTrue(any("mcp_servers" in e for e in errors))

    def test_multiple_errors_all_reported(self):
        data = {"name": "Only Name"}
        errors = validate_manifest(data)
        self.assertGreater(len(errors), 1)


# ---------------------------------------------------------------------------
# from_dict
# ---------------------------------------------------------------------------

class TestFromDict(unittest.TestCase):
    def test_minimal_manifest_builds_ok(self):
        manifest = from_dict(dict(_MINIMAL_DATA))
        self.assertIsInstance(manifest, PluginManifest)
        self.assertEqual(manifest.id, "my-plugin")
        self.assertEqual(manifest.name, "My Plugin")
        self.assertEqual(manifest.version, "1.0.0")

    def test_full_manifest_all_fields(self):
        manifest = from_dict(dict(_FULL_DATA))
        self.assertEqual(manifest.description, "A comprehensive plugin")
        self.assertEqual(manifest.author, "Alice")
        self.assertEqual(manifest.url, "https://example.com")
        self.assertEqual(manifest.tools, ["tool-a", "tool-b"])
        self.assertEqual(manifest.skills, ["skill-x"])
        self.assertEqual(manifest.commands, ["cmd-alpha"])
        self.assertEqual(len(manifest.mcp_servers), 1)
        self.assertEqual(manifest.tags, ["core", "extended"])

    def test_extra_fields_go_to_metadata(self):
        manifest = from_dict(dict(_FULL_DATA))
        self.assertIn("custom_extra", manifest.metadata)
        self.assertEqual(manifest.metadata["custom_extra"], "extra-value")

    def test_missing_required_field_raises_value_error(self):
        data = {"name": "No ID", "version": "1.0"}
        with self.assertRaises(ValueError):
            from_dict(data)

    def test_invalid_manifest_raises_value_error(self):
        with self.assertRaises(ValueError):
            from_dict({})

    def test_empty_tools_list_is_ok(self):
        manifest = from_dict({**_MINIMAL_DATA, "tools": []})
        self.assertEqual(manifest.tools, [])

    def test_empty_tags_list_is_ok(self):
        manifest = from_dict({**_MINIMAL_DATA, "tags": []})
        self.assertEqual(manifest.tags, [])

    def test_values_are_stripped(self):
        data = {"id": "  spaced-id  ", "name": "  Name  ", "version": "  1.0  "}
        manifest = from_dict(data)
        self.assertEqual(manifest.id, "spaced-id")
        self.assertEqual(manifest.name, "Name")
        self.assertEqual(manifest.version, "1.0")

    def test_none_tool_entries_are_filtered_out(self):
        data = {**_MINIMAL_DATA, "tools": [None, "good-tool", None]}
        manifest = from_dict(data)
        self.assertEqual(manifest.tools, ["good-tool"])

    def test_mcp_servers_non_dict_entries_filtered(self):
        data = {**_MINIMAL_DATA, "mcp_servers": [{"id": "good"}, "bad", None]}
        manifest = from_dict(data)
        self.assertEqual(len(manifest.mcp_servers), 1)


# ---------------------------------------------------------------------------
# PluginManifest.to_dict
# ---------------------------------------------------------------------------

class TestPluginManifestToDict(unittest.TestCase):
    def test_to_dict_has_required_keys(self):
        manifest = from_dict(dict(_MINIMAL_DATA))
        d = manifest.to_dict()
        for key in ("id", "name", "version", "description", "author", "url",
                    "tools", "skills", "commands", "mcp_servers", "tags", "metadata", "kind"):
            self.assertIn(key, d)

    def test_kind_is_plugin(self):
        manifest = from_dict(dict(_MINIMAL_DATA))
        self.assertEqual(manifest.to_dict()["kind"], "plugin")

    def test_to_dict_round_trip(self):
        manifest = from_dict(dict(_FULL_DATA))
        d = manifest.to_dict()
        self.assertEqual(d["id"], _FULL_DATA["id"])
        self.assertEqual(d["tools"], _FULL_DATA["tools"])
        self.assertEqual(d["skills"], _FULL_DATA["skills"])

    def test_to_dict_returns_copy_of_lists(self):
        manifest = from_dict({**_MINIMAL_DATA, "tools": ["t1"]})
        d = manifest.to_dict()
        d["tools"].append("t2")
        self.assertEqual(manifest.tools, ["t1"])

    def test_to_dict_returns_copy_of_metadata(self):
        manifest = from_dict({**_MINIMAL_DATA, "custom": "val"})
        d = manifest.to_dict()
        d["metadata"]["injected"] = True
        self.assertNotIn("injected", manifest.metadata)


# ---------------------------------------------------------------------------
# load_manifest
# ---------------------------------------------------------------------------

class TestLoadManifest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_load_minimal_manifest(self):
        path = _write_manifest(self.tmp, _MINIMAL_DATA)
        manifest = load_manifest(path)
        self.assertEqual(manifest.id, "my-plugin")

    def test_load_full_manifest(self):
        path = _write_manifest(self.tmp, _FULL_DATA)
        manifest = load_manifest(path)
        self.assertEqual(manifest.tools, ["tool-a", "tool-b"])

    def test_load_nonexistent_file_raises_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            load_manifest(self.tmp / "nonexistent.json")

    def test_load_invalid_json_raises_value_error(self):
        path = self.tmp / "bad.json"
        path.write_text("not-json{{{{", encoding="utf-8")
        with self.assertRaises(ValueError):
            load_manifest(path)

    def test_load_non_object_json_raises_value_error(self):
        path = self.tmp / "list.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")
        with self.assertRaises(ValueError):
            load_manifest(path)

    def test_load_missing_required_field_raises_value_error(self):
        data = {"name": "No ID", "version": "1.0"}
        path = _write_manifest(self.tmp, data)
        with self.assertRaises(ValueError):
            load_manifest(path)

    def test_load_accepts_path_as_string(self):
        path = _write_manifest(self.tmp, _MINIMAL_DATA)
        manifest = load_manifest(str(path))
        self.assertIsInstance(manifest, PluginManifest)

    def test_load_stores_extra_fields_in_metadata(self):
        data = {**_MINIMAL_DATA, "custom_field": "custom_value"}
        path = _write_manifest(self.tmp, data)
        manifest = load_manifest(path)
        self.assertEqual(manifest.metadata.get("custom_field"), "custom_value")


if __name__ == "__main__":
    unittest.main()
