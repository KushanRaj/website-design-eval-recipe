from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Generator.io import BundleValidationError, normalize_bundle_path, write_website_bundle
from Generator.models import WebsiteBundle, WebsiteFile


class BundleIoTests(unittest.TestCase):
    def test_rejects_absolute_paths(self) -> None:
        with self.assertRaises(BundleValidationError):
            normalize_bundle_path("/tmp/index.html")

    def test_rejects_parent_traversal(self) -> None:
        with self.assertRaises(BundleValidationError):
            normalize_bundle_path("../index.html")

    def test_rejects_unsupported_file_type(self) -> None:
        with self.assertRaises(BundleValidationError):
            normalize_bundle_path("image.png")

    def test_requires_root_index_html(self) -> None:
        bundle = WebsiteBundle(
            site_id="site-1",
            files=[WebsiteFile(path="nested/index.html", content="<html></html>")],
        )
        with self.assertRaises(BundleValidationError):
            write_website_bundle(bundle, Path(tempfile.mkdtemp()))

    def test_rejects_duplicate_paths(self) -> None:
        bundle = WebsiteBundle(
            site_id="site-1",
            files=[
                WebsiteFile(path="index.html", content="<html></html>"),
                WebsiteFile(path="index.html", content="<html></html>"),
            ],
        )
        with self.assertRaises(BundleValidationError):
            write_website_bundle(bundle, Path(tempfile.mkdtemp()))

    def test_writes_valid_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = WebsiteBundle(
                site_id="site-1",
                files=[
                    WebsiteFile(path="index.html", content="<html></html>"),
                    WebsiteFile(path="styles.css", content="body { margin: 0; }"),
                ],
            )
            written = write_website_bundle(bundle, tmp)
            self.assertEqual(len(written), 2)
            self.assertTrue((Path(tmp) / "index.html").exists())


if __name__ == "__main__":
    unittest.main()
