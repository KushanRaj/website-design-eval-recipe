from __future__ import annotations

import unittest

from website_design_eval.evaluator import _score_color_target


def _row(style: dict[str, str]) -> dict:
    return {
        "sample": {"style": style},
        "crop_path": None,
    }


class AnimationColorScoringTests(unittest.TestCase):
    def test_cssom_color_uses_rgb_distance(self) -> None:
        score = _score_color_target(
            [_row({"border-top-color": "rgb(211, 154, 36)"})],
            [_row({"border-top-color": "rgb(203, 153, 42)"})],
        )

        self.assertGreater(score["cssom_color"], 0.95)
        self.assertLess(score["cssom_color"], 1.0)
        self.assertEqual(score["cssom_color_by_property"][0]["method"], "rgb_distance")

    def test_non_color_properties_still_use_exact_match(self) -> None:
        score = _score_color_target(
            [_row({"transform": "matrix(1, 0, 0, 1, 0, 0)"})],
            [_row({"transform": "matrix(1, 0, 0, 1, 1, 0)"})],
        )

        self.assertEqual(score["cssom_color"], 0.0)
        self.assertEqual(score["cssom_color_by_property"][0]["method"], "exact")


if __name__ == "__main__":
    unittest.main()
