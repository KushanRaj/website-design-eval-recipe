from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from website_design_eval.manifest_generator import (
    _browser_inventory,
    _normalize_discovered_path,
    _rendered_selector_count,
    _sanitize_manifest_with_inventory,
)


class CandidateManifestSpaHashTests(unittest.TestCase):
    def test_discovered_spa_hash_routes_are_preserved(self) -> None:
        path = _normalize_discovered_path(
            "http://127.0.0.1:8000",
            "http://127.0.0.1:8000/",
            "/#/services",
            preserve_fragment=True,
        )

        self.assertEqual(path, "/#/services")

    def test_sanitizer_keeps_hash_route_and_playwright_text_selector(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "index.html").write_text(
                """
                <main id="app">
                  <a href="/#/services">Services</a>
                  <button class="tab">Personal</button>
                  <button class="tab">Business Banking</button>
                </main>
                """,
                encoding="utf-8",
            )
            inventory = _browser_inventory(root, serve_mode="spa", route_paths=["/"])
            raw = {
                "schemaVersion": 1,
                "site": {"name": "candidate"},
                "defaults": {"viewport": {"width": 1440, "height": 900}},
                "captures": [
                    {
                        "id": "services-business-tab",
                        "page": "services",
                        "state": "business-tab-active",
                        "path": "/#/services",
                        "actions": [
                            {"type": "click", "selector": 'button.tab:has-text("Business Banking")'},
                        ],
                        "screenshot": {"fullPage": False},
                    }
                ],
            }

            sanitized = _sanitize_manifest_with_inventory(root, raw, max_captures=None, inventory=inventory)

            self.assertEqual([capture["id"] for capture in sanitized["captures"]], ["services-business-tab"])
            self.assertEqual(sanitized["captures"][0]["path"], "/#/services")

    def test_rendered_selector_count_tries_css_then_playwright_selector(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "index.html").write_text(
                """
                <button class="tab">Personal</button>
                <button class="tab">Business Banking</button>
                """,
                encoding="utf-8",
            )

            self.assertEqual(_rendered_selector_count(root, "/", "button.tab"), 2)
            self.assertEqual(_rendered_selector_count(root, "/", 'button.tab:has-text("Business Banking")'), 1)


if __name__ == "__main__":
    unittest.main()
