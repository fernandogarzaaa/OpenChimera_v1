"""Tests for the enhanced operator dashboard (core/api_docs.py)."""
from __future__ import annotations

import json
import unittest

from core.api_docs import ROUTE_CATALOG, build_docs_html, build_openapi_document


class TestBuildOpenApiDocument(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = build_openapi_document(
            base_url="http://localhost:8099",
            auth_header="X-Api-Key",
            auth_enabled=True,
        )

    def test_openapi_version(self) -> None:
        self.assertEqual(self.spec["openapi"], "3.1.0")

    def test_info_title_present(self) -> None:
        self.assertIn("title", self.spec["info"])

    def test_paths_not_empty(self) -> None:
        self.assertGreater(len(self.spec["paths"]), 0)

    def test_all_catalog_routes_in_paths(self) -> None:
        for route in ROUTE_CATALOG:
            self.assertIn(route, self.spec["paths"])

    def test_servers_contains_base_url(self) -> None:
        servers = self.spec.get("servers", [])
        self.assertTrue(any("localhost:8099" in s.get("url", "") for s in servers))


class TestBuildDocsHtml(unittest.TestCase):
    def setUp(self) -> None:
        spec = build_openapi_document(
            base_url="http://localhost:8099",
            auth_header="X-Chimera-Key",
            auth_enabled=False,
        )
        self.html = build_docs_html(
            spec=spec,
            auth_header="X-Chimera-Key",
            auth_enabled=False,
        )

    def test_is_string(self) -> None:
        self.assertIsInstance(self.html, str)

    def test_contains_doctype(self) -> None:
        self.assertIn("<!doctype html>", self.html.lower())

    def test_contains_dashboard_heading(self) -> None:
        self.assertIn("OpenChimera", self.html)

    def test_contains_query_playground(self) -> None:
        self.assertIn("Query Playground", self.html)

    def test_contains_system_status_section(self) -> None:
        self.assertIn("System Status", self.html)

    def test_playground_fetch_references_query_run(self) -> None:
        self.assertIn("/v1/query/run", self.html)

    def test_status_panel_references_health(self) -> None:
        self.assertIn("/health", self.html)

    def test_openapi_json_embedded_as_script(self) -> None:
        self.assertIn("openapi-source", self.html)
        self.assertIn("application/json", self.html)

    def test_tag_navigation_links_present(self) -> None:
        # Navigation links derived from tags should appear
        self.assertIn('href="#', self.html)

    def test_table_rows_include_all_routes(self) -> None:
        for route, ops in ROUTE_CATALOG.items():
            for method in ops:
                self.assertIn(route, self.html)
                self.assertIn(method.upper(), self.html)

    def test_auth_header_shown_in_playground(self) -> None:
        self.assertIn("X-Chimera-Key", self.html)

    def test_auth_disabled_shown(self) -> None:
        self.assertIn("false", self.html.lower())

    def test_no_bare_script_injection(self) -> None:
        """Ensure user-controlled strings are HTML-escaped (basic XSS guard)."""
        spec = build_openapi_document(
            base_url='http://localhost"><script>alert(1)</script>',
            auth_header='<img onerror="evil()">',
            auth_enabled=False,
        )
        html = build_docs_html(
            spec=spec,
            auth_header='<img onerror="evil()">',
            auth_enabled=False,
        )
        # The raw injection strings must not appear unescaped
        self.assertNotIn('<img onerror="evil()">', html)
        self.assertNotIn('<script>alert(1)</script>', html)

    def test_hallucination_scan_referenced_in_playground_script(self) -> None:
        """The playground should display the hallucination_scan result."""
        self.assertIn("hallucination_scan", self.html)
