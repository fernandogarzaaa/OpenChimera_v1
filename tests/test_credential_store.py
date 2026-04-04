"""Tests for core.credential_store — CredentialStore with mocked DatabaseManager."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, call

from core.credential_store import CredentialStore


# ---------------------------------------------------------------------------
# Helper — build a CredentialStore with a fully mocked database
# ---------------------------------------------------------------------------

def _make_store(load_data: dict | None = None) -> tuple[CredentialStore, MagicMock]:
    """Return (store, mock_db) with load_credentials pre-configured."""
    mock_db = MagicMock()
    mock_db.load_credentials.return_value = load_data if load_data is not None else {"providers": {}}
    store = CredentialStore(database=mock_db)
    return store, mock_db


# ---------------------------------------------------------------------------
# _mask_value
# ---------------------------------------------------------------------------

class TestMaskValue(unittest.TestCase):
    def setUp(self) -> None:
        self.store, _ = _make_store()

    def test_empty_string_returns_empty(self) -> None:
        self.assertEqual(self.store._mask_value(""), "")

    def test_one_char_all_stars(self) -> None:
        self.assertEqual(self.store._mask_value("a"), "*")

    def test_two_chars_all_stars(self) -> None:
        self.assertEqual(self.store._mask_value("ab"), "**")

    def test_four_chars_all_stars(self) -> None:
        self.assertEqual(self.store._mask_value("abcd"), "****")

    def test_five_chars_first_two_star_last_two(self) -> None:
        # "abcde" → "ab" + "*" + "de"
        self.assertEqual(self.store._mask_value("abcde"), "ab*de")

    def test_long_value_first_two_stars_last_two(self) -> None:
        # "sk-test123" (10 chars) → "sk" + "******" + "23"
        self.assertEqual(self.store._mask_value("sk-test123"), "sk******23")

    def test_eight_chars(self) -> None:
        # "abcdefgh" (8 chars) → "ab" + "****" + "gh"
        self.assertEqual(self.store._mask_value("abcdefgh"), "ab****gh")

    def test_mask_does_not_reveal_full_value(self) -> None:
        original = "supersecretkey"
        masked = self.store._mask_value(original)
        self.assertNotEqual(masked, original)
        self.assertIn("*", masked)


# ---------------------------------------------------------------------------
# Constructor / initialize
# ---------------------------------------------------------------------------

class TestCredentialStoreConstructor(unittest.TestCase):
    def test_initialize_called_in_constructor(self) -> None:
        mock_db = MagicMock()
        mock_db.load_credentials.return_value = {"providers": {}}
        CredentialStore(database=mock_db)
        mock_db.initialize.assert_called_once()

    def test_database_stored_on_instance(self) -> None:
        mock_db = MagicMock()
        mock_db.load_credentials.return_value = {"providers": {}}
        store = CredentialStore(database=mock_db)
        self.assertIs(store.database, mock_db)


# ---------------------------------------------------------------------------
# load()
# ---------------------------------------------------------------------------

class TestLoad(unittest.TestCase):
    def test_returns_dict_from_database(self) -> None:
        data = {"providers": {"openai": {"api_key": "sk-123"}}}
        store, mock_db = _make_store(data)
        result = store.load()
        self.assertEqual(result, data)
        mock_db.load_credentials.assert_called()

    def test_returns_empty_providers_dict(self) -> None:
        store, _ = _make_store({"providers": {}})
        self.assertEqual(store.load(), {"providers": {}})

    def test_delegates_entirely_to_database(self) -> None:
        data = {"providers": {"x": {"k": "v"}}, "extra": "field"}
        store, mock_db = _make_store(data)
        mock_db.load_credentials.return_value = data
        self.assertEqual(store.load(), data)


# ---------------------------------------------------------------------------
# status()
# ---------------------------------------------------------------------------

class TestStatus(unittest.TestCase):
    def test_returns_masked_provider_values(self) -> None:
        data = {"providers": {"openai": {"api_key": "sk-secret123456"}}}
        store, _ = _make_store(data)
        result = store.status()
        provider = result["providers"]["openai"]
        self.assertTrue(provider["configured"])
        self.assertIn("api_key", provider["keys"])
        masked = provider["masked"]["api_key"]
        self.assertNotEqual(masked, "sk-secret123456")
        self.assertIn("*", masked)

    def test_empty_providers_returns_empty(self) -> None:
        store, _ = _make_store({"providers": {}})
        self.assertEqual(store.status()["providers"], {})

    def test_non_dict_provider_value_is_skipped(self) -> None:
        data = {"providers": {"bad": "not-a-dict"}}
        store, _ = _make_store(data)
        self.assertNotIn("bad", store.status()["providers"])

    def test_none_values_excluded_from_masked(self) -> None:
        data = {"providers": {"openai": {"api_key": None, "org_id": "org-123"}}}
        store, _ = _make_store(data)
        provider = store.status()["providers"]["openai"]
        self.assertNotIn("api_key", provider["masked"])
        self.assertIn("org_id", provider["masked"])

    def test_all_none_values_yields_not_configured(self) -> None:
        data = {"providers": {"openai": {"api_key": None}}}
        store, _ = _make_store(data)
        provider = store.status()["providers"]["openai"]
        self.assertFalse(provider["configured"])

    def test_keys_are_sorted(self) -> None:
        data = {"providers": {"openai": {"z_key": "v1", "a_key": "v2", "m_key": "v3"}}}
        store, _ = _make_store(data)
        keys = store.status()["providers"]["openai"]["keys"]
        self.assertEqual(keys, sorted(keys))

    def test_multiple_providers_all_present(self) -> None:
        data = {"providers": {"openai": {"k": "v"}, "anthropic": {"k": "v"}}}
        store, _ = _make_store(data)
        result = store.status()["providers"]
        self.assertIn("openai", result)
        self.assertIn("anthropic", result)


# ---------------------------------------------------------------------------
# get_provider_credentials()
# ---------------------------------------------------------------------------

class TestGetProviderCredentials(unittest.TestCase):
    def test_returns_credentials_for_known_provider(self) -> None:
        data = {"providers": {"anthropic": {"api_key": "sk-ant", "model": "claude-3"}}}
        store, _ = _make_store(data)
        creds = store.get_provider_credentials("anthropic")
        self.assertEqual(creds, {"api_key": "sk-ant", "model": "claude-3"})

    def test_returns_empty_for_missing_provider(self) -> None:
        store, _ = _make_store({"providers": {}})
        self.assertEqual(store.get_provider_credentials("nonexistent"), {})

    def test_returns_empty_for_non_dict_raw_value(self) -> None:
        data = {"providers": {"bad": "not-a-dict"}}
        store, _ = _make_store(data)
        self.assertEqual(store.get_provider_credentials("bad"), {})

    def test_filters_out_empty_string_values(self) -> None:
        data = {"providers": {"openai": {"api_key": "sk-123", "org": ""}}}
        store, _ = _make_store(data)
        creds = store.get_provider_credentials("openai")
        self.assertIn("api_key", creds)
        self.assertNotIn("org", creds)

    def test_filters_out_none_values(self) -> None:
        data = {"providers": {"openai": {"api_key": None, "other": "val"}}}
        store, _ = _make_store(data)
        creds = store.get_provider_credentials("openai")
        self.assertNotIn("api_key", creds)
        self.assertIn("other", creds)

    def test_values_cast_to_str(self) -> None:
        data = {"providers": {"p": {"key": 42}}}
        store, _ = _make_store(data)
        creds = store.get_provider_credentials("p")
        self.assertEqual(creds["key"], "42")


# ---------------------------------------------------------------------------
# has_provider_credentials()
# ---------------------------------------------------------------------------

class TestHasProviderCredentials(unittest.TestCase):
    def test_returns_true_when_credentials_present(self) -> None:
        data = {"providers": {"openai": {"api_key": "sk-123"}}}
        store, _ = _make_store(data)
        self.assertTrue(store.has_provider_credentials("openai"))

    def test_returns_false_when_no_credentials(self) -> None:
        store, _ = _make_store({"providers": {}})
        self.assertFalse(store.has_provider_credentials("openai"))

    def test_returns_false_when_all_values_empty(self) -> None:
        data = {"providers": {"openai": {"api_key": ""}}}
        store, _ = _make_store(data)
        self.assertFalse(store.has_provider_credentials("openai"))

    def test_candidate_keys_match_returns_true(self) -> None:
        data = {"providers": {"openai": {"api_key": "sk-123", "org": "org-1"}}}
        store, _ = _make_store(data)
        self.assertTrue(store.has_provider_credentials("openai", ["api_key"]))

    def test_candidate_keys_no_match_returns_false(self) -> None:
        data = {"providers": {"openai": {"org": "org-1"}}}
        store, _ = _make_store(data)
        self.assertFalse(store.has_provider_credentials("openai", ["api_key"]))

    def test_candidate_keys_partial_match_returns_true(self) -> None:
        data = {"providers": {"openai": {"api_key": "sk-123"}}}
        store, _ = _make_store(data)
        self.assertTrue(store.has_provider_credentials("openai", ["missing_key", "api_key"]))

    def test_empty_candidate_keys_list_treated_as_no_filter(self) -> None:
        # Empty list is falsy → same as no candidate_keys → True if any creds exist
        data = {"providers": {"openai": {"api_key": "sk-123"}}}
        store, _ = _make_store(data)
        self.assertTrue(store.has_provider_credentials("openai", []))


# ---------------------------------------------------------------------------
# set_provider_credential() / delete_provider_credential()
# ---------------------------------------------------------------------------

class TestSetAndDeleteProviderCredential(unittest.TestCase):
    def test_set_calls_database_set_credential(self) -> None:
        data = {"providers": {"openai": {"api_key": "sk-newval"}}}
        store, mock_db = _make_store(data)
        store.set_provider_credential("openai", "api_key", "sk-newval")
        mock_db.set_credential.assert_called_once_with("openai", "api_key", "sk-newval")

    def test_set_coerces_args_to_str(self) -> None:
        data = {"providers": {"p": {"k": "99"}}}
        store, mock_db = _make_store(data)
        store.set_provider_credential("p", "k", "99")
        # key and value must arrive as str
        args = mock_db.set_credential.call_args[0]
        self.assertIsInstance(args[1], str)
        self.assertIsInstance(args[2], str)

    def test_set_returns_dict(self) -> None:
        data = {"providers": {"openai": {"api_key": "sk-xyz"}}}
        store, _ = _make_store(data)
        result = store.set_provider_credential("openai", "api_key", "sk-xyz")
        self.assertIsInstance(result, dict)

    def test_delete_calls_database_delete_credential(self) -> None:
        store, mock_db = _make_store({"providers": {}})
        store.delete_provider_credential("openai", "api_key")
        mock_db.delete_credential.assert_called_once_with("openai", "api_key")

    def test_delete_returns_dict(self) -> None:
        store, _ = _make_store({"providers": {}})
        result = store.delete_provider_credential("openai", "api_key")
        self.assertIsInstance(result, dict)

    def test_delete_returns_not_configured_when_provider_gone(self) -> None:
        store, _ = _make_store({"providers": {}})
        result = store.delete_provider_credential("openai", "api_key")
        self.assertFalse(result.get("configured", True))


if __name__ == "__main__":
    unittest.main()
