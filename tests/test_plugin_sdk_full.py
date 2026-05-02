"""
Tests for Phase 5: Plugin SDK, Skill Marketplace, Model Provider Registry.
"""
from __future__ import annotations

import unittest

from core.plugin_sdk import (
    PluginState,
    PluginManifest,
    BasePlugin,
    PluginRegistry,
    SkillCategory,
    SkillListing,
    SkillMarketplace,
    ModelProviderType,
    ModelSpec,
    ProviderConfig,
    ModelProviderRegistry,
    plugin_capability,
    plugin_permission,
)


# ---------------------------------------------------------------------------
# Plugin SDK Tests
# ---------------------------------------------------------------------------

class TestPluginManifest(unittest.TestCase):
    def test_default_manifest(self):
        manifest = PluginManifest(id="test-plugin", name="Test Plugin")
        self.assertEqual(manifest.id, "test-plugin")
        self.assertEqual(manifest.version, "0.1.0")
        self.assertEqual(manifest.license, "MIT")
        self.assertEqual(manifest.capabilities, [])

    def test_manifest_to_dict(self):
        manifest = PluginManifest(
            id="my-plugin",
            name="My Plugin",
            version="1.2.3",
            capabilities=["search", "summarize"],
        )
        d = manifest.to_dict()
        self.assertEqual(d["id"], "my-plugin")
        self.assertEqual(d["version"], "1.2.3")
        self.assertIn("search", d["capabilities"])

    def test_manifest_from_dict(self):
        data = {
            "id": "from-dict-plugin",
            "name": "From Dict",
            "version": "0.5.0",
            "description": "A plugin from dict",
            "capabilities": ["do_stuff"],
        }
        manifest = PluginManifest.from_dict(data)
        self.assertEqual(manifest.id, "from-dict-plugin")
        self.assertIn("do_stuff", manifest.capabilities)


class ConcretePlugin(BasePlugin):
    manifest = PluginManifest(
        id="concrete-plugin",
        name="Concrete Plugin",
        version="1.0.0",
        capabilities=["test"],
    )

    def __init__(self):
        super().__init__()
        self.loaded = False
        self.unloaded = False
        self.messages_received = []

    def on_load(self):
        self.loaded = True

    def on_unload(self):
        self.unloaded = True

    def on_message(self, message):
        self.messages_received.append(message)
        return {"reply": f"Echo: {message.get('text', '')}"}


class TestBasePlugin(unittest.TestCase):
    def test_plugin_initial_state(self):
        plugin = ConcretePlugin()
        self.assertEqual(plugin.state, PluginState.UNLOADED)
        self.assertFalse(plugin.loaded)

    def test_register_and_trigger_hook(self):
        plugin = ConcretePlugin()
        events = []
        plugin.register_hook("test_event", lambda p: events.append(p))
        plugin.trigger_hook("test_event", {"data": 42})
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["data"], 42)

    def test_on_message_returns_echo(self):
        plugin = ConcretePlugin()
        response = plugin.on_message({"text": "hello"})
        self.assertEqual(response["reply"], "Echo: hello")

    def test_status_structure(self):
        plugin = ConcretePlugin()
        status = plugin.status()
        self.assertIn("id", status)
        self.assertIn("state", status)
        self.assertIn("version", status)


class TestPluginRegistry(unittest.TestCase):
    def setUp(self):
        self.registry = PluginRegistry()

    def test_register_plugin(self):
        plugin = ConcretePlugin()
        self.registry.register(plugin)
        self.assertEqual(plugin.state, PluginState.ACTIVE)
        self.assertTrue(plugin.loaded)

    def test_unregister_plugin(self):
        plugin = ConcretePlugin()
        self.registry.register(plugin)
        result = self.registry.unregister("concrete-plugin")
        self.assertTrue(result)
        self.assertEqual(plugin.state, PluginState.UNLOADED)

    def test_unregister_unknown_plugin(self):
        result = self.registry.unregister("nonexistent")
        self.assertFalse(result)

    def test_get_plugin(self):
        plugin = ConcretePlugin()
        self.registry.register(plugin)
        retrieved = self.registry.get("concrete-plugin")
        self.assertIs(retrieved, plugin)

    def test_list_plugins(self):
        plugin = ConcretePlugin()
        self.registry.register(plugin)
        plugins = self.registry.list_plugins()
        self.assertEqual(len(plugins), 1)
        self.assertEqual(plugins[0]["id"], "concrete-plugin")

    def test_dispatch_message(self):
        plugin = ConcretePlugin()
        self.registry.register(plugin)
        responses = self.registry.dispatch_message({"text": "test message"})
        self.assertEqual(len(responses), 1)
        self.assertIn("reply", responses[0])

    def test_dispatch_event(self):
        plugin = ConcretePlugin()
        self.registry.register(plugin)
        events = []
        plugin.register_hook("system_event", lambda p: events.append(p))
        self.registry.dispatch_event("system_event", {"type": "startup"})
        self.assertEqual(len(events), 1)

    def test_status_structure(self):
        status = self.registry.status()
        self.assertIn("total", status)
        self.assertIn("active", status)
        self.assertIn("errors", status)

    def test_plugin_capability_decorator(self):
        @plugin_capability("search", "summarize")
        class SearchPlugin(BasePlugin):
            manifest = PluginManifest(id="search-plugin", name="Search")
        plugin = SearchPlugin()
        self.assertIn("search", plugin.manifest.capabilities)


# ---------------------------------------------------------------------------
# Skill Marketplace Tests
# ---------------------------------------------------------------------------

class TestSkillMarketplace(unittest.TestCase):
    def setUp(self):
        self.marketplace = SkillMarketplace()

    def test_default_listings_present(self):
        status = self.marketplace.status()
        self.assertGreater(status["total_listings"], 0)

    def test_search_all_returns_results(self):
        results = self.marketplace.search()
        self.assertGreater(len(results), 0)

    def test_search_by_query(self):
        results = self.marketplace.search(query="code")
        self.assertTrue(all("code" in r["name"].lower() or "code" in r["description"].lower() or
                            any("code" in t for t in r.get("tags", [])) for r in results))

    def test_search_by_category(self):
        results = self.marketplace.search(category=SkillCategory.DEVELOPER)
        self.assertTrue(all(r["category"] == "developer" for r in results))

    def test_install_skill(self):
        result = self.marketplace.install("web-search")
        self.assertEqual(result["status"], "installed")
        self.assertEqual(result["skill_id"], "web-search")

    def test_install_already_installed(self):
        self.marketplace.install("web-search")
        result = self.marketplace.install("web-search")
        self.assertEqual(result["status"], "already_installed")

    def test_install_unknown_skill(self):
        result = self.marketplace.install("nonexistent-skill")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["reason"], "skill_not_found")

    def test_uninstall_skill(self):
        self.marketplace.install("summarizer")
        result = self.marketplace.uninstall("summarizer")
        self.assertEqual(result["status"], "uninstalled")

    def test_uninstall_not_installed(self):
        result = self.marketplace.uninstall("not-installed")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["reason"], "not_installed")

    def test_rate_skill(self):
        result = self.marketplace.rate("code-executor", 5.0)
        self.assertEqual(result["status"], "rated")
        self.assertIn("new_rating", result)

    def test_rate_invalid_rating(self):
        result = self.marketplace.rate("code-executor", 6.0)
        self.assertEqual(result["status"], "error")

    def test_publish_new_skill(self):
        listing = SkillListing(
            id="my-custom-skill",
            name="My Custom Skill",
            description="Does something cool",
            category=SkillCategory.OTHER,
            author="test-author",
        )
        result = self.marketplace.publish(listing)
        self.assertEqual(result["status"], "published")
        # Should now be searchable
        found = self.marketplace.get_listing("my-custom-skill")
        self.assertIsNotNone(found)

    def test_list_installed(self):
        self.marketplace.install("web-search")
        installed = self.marketplace.list_installed()
        self.assertGreater(len(installed), 0)

    def test_status_structure(self):
        status = self.marketplace.status()
        self.assertIn("total_listings", status)
        self.assertIn("installed_count", status)
        self.assertIn("featured_count", status)
        self.assertIn("verified_count", status)

    def test_featured_skills_present(self):
        results = self.marketplace.search()
        featured = [r for r in results if r.get("verified")]
        self.assertGreater(len(featured), 0)


# ---------------------------------------------------------------------------
# Model Provider Registry Tests
# ---------------------------------------------------------------------------

class TestModelProviderRegistry(unittest.TestCase):
    def setUp(self):
        self.registry = ModelProviderRegistry()

    def test_builtin_models_registered(self):
        models = self.registry.list_models()
        self.assertGreater(len(models), 0)

    def test_list_by_provider(self):
        models = self.registry.list_models(provider=ModelProviderType.OPENAI)
        self.assertTrue(all(m["provider"] == "openai" for m in models))

    def test_list_local_models(self):
        models = self.registry.list_models(local_only=True)
        self.assertTrue(all(m["is_local"] for m in models))

    def test_list_vision_models(self):
        models = self.registry.list_models(supports_vision=True)
        self.assertTrue(all(m["supports_vision"] for m in models))

    def test_get_model(self):
        model = self.registry.get_model("gpt-4o")
        self.assertIsNotNone(model)
        self.assertEqual(model.id, "gpt-4o")

    def test_get_unknown_model(self):
        model = self.registry.get_model("nonexistent-model")
        self.assertIsNone(model)

    def test_register_custom_model(self):
        spec = ModelSpec(
            id="custom-model",
            name="My Custom Model",
            provider=ModelProviderType.CUSTOM,
            context_window=8192,
        )
        self.registry.register_model(spec)
        model = self.registry.get_model("custom-model")
        self.assertIsNotNone(model)
        self.assertEqual(model.name, "My Custom Model")

    def test_configure_provider(self):
        config = ProviderConfig(
            provider=ModelProviderType.OPENAI,
            api_key="sk-test",
            default_model="gpt-4o",
        )
        self.registry.configure_provider(config)
        status = self.registry.status()
        self.assertIn("openai", status["configured_providers"])

    def test_select_local_model(self):
        model = self.registry.select_model(prefer_local=True)
        self.assertIsNotNone(model)
        self.assertTrue(model["is_local"])

    def test_select_vision_model(self):
        model = self.registry.select_model(require_vision=True)
        self.assertIsNotNone(model)
        self.assertTrue(model["supports_vision"])

    def test_select_function_calling_model(self):
        model = self.registry.select_model(require_function_calling=True)
        self.assertIsNotNone(model)
        self.assertTrue(model["supports_function_calling"])

    def test_select_with_budget(self):
        model = self.registry.select_model(budget_per_1k=0.5)
        self.assertIsNotNone(model)
        self.assertLessEqual(model["cost_per_1k_input"], 0.5)

    def test_record_and_get_usage(self):
        self.registry.record_usage("gpt-4o", 1000, 500)
        stats = self.registry.get_usage_stats()
        self.assertIn("gpt-4o", stats["per_model"])
        self.assertEqual(stats["per_model"]["gpt-4o"]["input_tokens"], 1000)
        self.assertGreater(stats["total_estimated_cost_usd"], 0)

    def test_model_spec_to_dict(self):
        model = self.registry.get_model("gpt-4o")
        d = model.to_dict()
        self.assertIn("id", d)
        self.assertIn("provider", d)
        self.assertIn("context_window", d)
        self.assertIn("cost_per_1k_input", d)

    def test_status_structure(self):
        status = self.registry.status()
        self.assertIn("total_models", status)
        self.assertIn("local_models", status)
        self.assertIn("configured_providers", status)


if __name__ == "__main__":
    unittest.main()
