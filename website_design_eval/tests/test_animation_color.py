from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from website_design_eval.evaluator import _score_color_target


def _row(
    style: dict[str, str],
    *,
    bbox: dict | None = None,
    border_width: float | None = None,
    crop_path: str | None = None,
) -> dict:
    sample = {"style": style}
    if bbox is not None:
        sample["bbox_px"] = bbox
    if border_width is not None:
        sample["visual"] = {
            "border_widths_px": {
                "top": border_width,
                "right": border_width,
                "bottom": border_width,
                "left": border_width,
            }
        }
    return {
        "sample": sample,
        "crop_path": crop_path,
    }


class AnimationColorScoringTests(unittest.TestCase):
    def test_cssom_color_uses_relative_rgb_delta(self) -> None:
        score = _score_color_target(
            [
                _row({"border-top-color": "rgb(10, 10, 10)"}),
                _row({"border-top-color": "rgb(20, 10, 10)"}),
            ],
            [
                _row({"border-top-color": "rgb(200, 200, 200)"}),
                _row({"border-top-color": "rgb(210, 200, 200)"}),
            ],
        )

        self.assertEqual(score["color_delta"], 1.0)
        self.assertEqual(score["cssom_color"], 1.0)
        self.assertEqual(score["cssom_color_by_property"][1]["method"], "relative_rgb_delta")

    def test_cssom_color_penalizes_missing_relative_delta(self) -> None:
        score = _score_color_target(
            [
                _row({"background-color": "rgb(34, 34, 58)"}),
                _row({"background-color": "rgb(13, 61, 46)"}),
            ],
            [
                _row({"background-color": "rgb(29, 23, 56)"}),
                _row({"background-color": "rgb(29, 23, 56)"}),
            ],
        )

        self.assertEqual(score["color_delta"], 0.0)

    def test_cssom_color_weights_border_by_visual_area(self) -> None:
        bbox = {"width": 100, "height": 100}
        score = _score_color_target(
            [
                _row(
                    {
                        "background-color": "rgb(0, 0, 0)",
                        "border-color": "rgb(0, 0, 0)",
                    },
                    bbox=bbox,
                    border_width=1,
                ),
                _row(
                    {
                        "background-color": "rgb(10, 0, 0)",
                        "border-color": "rgb(10, 0, 0)",
                    },
                    bbox=bbox,
                    border_width=1,
                ),
            ],
            [
                _row(
                    {
                        "background-color": "rgb(0, 0, 0)",
                        "border-color": "rgb(0, 0, 0)",
                    },
                    bbox=bbox,
                    border_width=1,
                ),
                _row(
                    {
                        "background-color": "rgb(0, 0, 0)",
                        "border-color": "rgb(10, 0, 0)",
                    },
                    bbox=bbox,
                    border_width=1,
                ),
            ],
        )

        self.assertLess(score["color_delta"], 0.05)
        self.assertGreater(score["color_delta"], 0.03)

    def test_target_box_delta_pixelmatch_penalizes_border_only_change(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            ref_base = root / "ref-base.png"
            ref_frame = root / "ref-frame.png"
            cand_base = root / "cand-base.png"
            cand_frame = root / "cand-frame.png"
            Image.new("RGB", (10, 10), (0, 0, 0)).save(ref_base)
            Image.new("RGB", (10, 10), (255, 0, 0)).save(ref_frame)
            Image.new("RGB", (10, 10), (0, 0, 0)).save(cand_base)
            image = Image.new("RGB", (10, 10), (0, 0, 0))
            for x in range(10):
                image.putpixel((x, 0), (255, 0, 0))
                image.putpixel((x, 9), (255, 0, 0))
            for y in range(10):
                image.putpixel((0, y), (255, 0, 0))
                image.putpixel((9, y), (255, 0, 0))
            image.save(cand_frame)

            score = _score_color_target(
                [
                    _row({}, crop_path=str(ref_base)),
                    _row({}, crop_path=str(ref_frame)),
                ],
                [
                    _row({}, crop_path=str(cand_base)),
                    _row({}, crop_path=str(cand_frame)),
                ],
            )

        self.assertLess(score["target_box_delta_pixelmatch"], 0.5)
        self.assertGreater(score["target_box_pixelmatch"], score["target_box_delta_pixelmatch"])

    def test_non_color_properties_still_use_exact_match(self) -> None:
        score = _score_color_target(
            [_row({"transform": "matrix(1, 0, 0, 1, 0, 0)"})],
            [_row({"transform": "matrix(1, 0, 0, 1, 1, 0)"})],
        )

        self.assertEqual(score["cssom_color"], 0.0)
        self.assertEqual(score["cssom_color_by_property"][0]["method"], "exact")


if __name__ == "__main__":
    unittest.main()
