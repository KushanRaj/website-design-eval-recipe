from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from website_design_eval.evaluator import _resolved_candidate_root_for_framework, _route_for_capture


class FrameworkRouteTests(unittest.TestCase):
    def test_spa_candidate_manifest_route_gets_full_route_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "index.html").write_text("<main>SPA shell</main>", encoding="utf-8")

            route = _route_for_capture(
                root,
                {"path": "/minerals"},
                serve_mode="spa",
                candidate_manifest_mapped=True,
            )

            self.assertEqual(route["status"], "resolved")
            self.assertEqual(route["resolved_path"], "/minerals")
            self.assertEqual(route["method"], "spa_manifest_path")
            self.assertEqual(route["confidence"], 1.0)

    def test_spa_deterministic_fallback_is_resolved_but_penalized(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "index.html").write_text("<main>SPA shell</main>", encoding="utf-8")

            route = _route_for_capture(root, {"path": "/minerals.html"}, serve_mode="spa")

            self.assertEqual(route["status"], "resolved")
            self.assertEqual(route["resolved_path"], "/minerals.html")
            self.assertEqual(route["method"], "spa_fallback")
            self.assertLess(route["confidence"], 1.0)

    def test_spa_route_missing_without_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            route = _route_for_capture(Path(temp), {"path": "/minerals"}, serve_mode="spa")

            self.assertEqual(route["status"], "missing")
            self.assertEqual(route["failure_mode"], "spa_index_missing")

    def test_framework_candidate_root_prefers_dist_build(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "index.html").write_text("<script type='module' src='/src/main.jsx'></script>", encoding="utf-8")
            (root / "dist").mkdir()
            (root / "dist" / "index.html").write_text("<main>built</main>", encoding="utf-8")

            resolved = _resolved_candidate_root_for_framework(root, "react")

            self.assertEqual(resolved, (root / "dist").resolve())


if __name__ == "__main__":
    unittest.main()
