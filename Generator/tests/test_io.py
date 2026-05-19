from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Generator.io import SitePathError, list_site_files, normalize_bundle_path


class SitePathValidationTests(unittest.TestCase):
    def test_rejects_absolute_paths(self) -> None:
        with self.assertRaises(SitePathError):
            normalize_bundle_path("/tmp/index.html")

    def test_rejects_parent_traversal(self) -> None:
        with self.assertRaises(SitePathError):
            normalize_bundle_path("../index.html")

    def test_rejects_unsupported_file_type(self) -> None:
        with self.assertRaises(SitePathError):
            normalize_bundle_path("image.png")

    def test_accepts_nested_html(self) -> None:
        self.assertEqual(normalize_bundle_path("nested/page.html"), "nested/page.html")

    def test_accepts_root_index(self) -> None:
        self.assertEqual(normalize_bundle_path("index.html"), "index.html")


class ListSiteFilesTests(unittest.TestCase):
    def test_returns_relative_paths_sorted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.html").write_text("<html></html>")
            (root / "styles.css").write_text("body{}")
            (root / "sub").mkdir()
            (root / "sub" / "page.html").write_text("<html></html>")
            self.assertEqual(
                list_site_files(root),
                ["index.html", "styles.css", "sub/page.html"],
            )

    def test_missing_dir_returns_empty(self) -> None:
        self.assertEqual(list_site_files("/nonexistent/site/path"), [])


if __name__ == "__main__":
    unittest.main()
