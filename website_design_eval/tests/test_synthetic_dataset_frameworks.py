from __future__ import annotations

import unittest

from scripts.package_synthetic_dataset import _parse_candidate_frameworks, _variant_slug


class SyntheticDatasetFrameworkTests(unittest.TestCase):
    def test_parse_candidate_frameworks_dedupes_in_order(self) -> None:
        self.assertEqual(
            _parse_candidate_frameworks("html,react,react,solid", "html"),
            ["html", "react", "solid"],
        )

    def test_parse_candidate_frameworks_falls_back_to_single_framework(self) -> None:
        self.assertEqual(_parse_candidate_frameworks(None, "react"), ["react"])
        self.assertEqual(_parse_candidate_frameworks("", "solid"), ["solid"])

    def test_parse_candidate_frameworks_rejects_unknown_framework(self) -> None:
        with self.assertRaises(ValueError):
            _parse_candidate_frameworks("html,next", "html")

    def test_variant_slug_only_suffixes_multi_framework_packaging(self) -> None:
        self.assertEqual(_variant_slug("maple-hollow", "react", ["react"]), "maple-hollow")
        self.assertEqual(
            _variant_slug("maple-hollow", "react", ["html", "react"]),
            "maple-hollow-react",
        )


if __name__ == "__main__":
    unittest.main()
