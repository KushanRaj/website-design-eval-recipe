from __future__ import annotations

import unittest

from website_design_eval.reward import COMPONENT_WEIGHTS, RAW_COMPONENT_WEIGHTS, compute_reward


def _capture_payload(
    *,
    coverage: float = 1.0,
    screenshot_size: float = 1.0,
    html: float = 1.0,
    vlm: float = 1.0,
    global_pixelmatch: float = 1.0,
    block_pixelmatch: float | None = None,
    visual_block: float | None = 1.0,
    bbox: float | None = 1.0,
    cssom: float | None = 1.0,
    dreamsim: float = 1.0,
) -> dict:
    return {
        "coverage": {"score": coverage},
        "capture": {"weight": 1.0},
        "metrics": {
            "screenshot_size_match": {"score": screenshot_size},
            "html_text": {"bleu_1": html, "rouge_1_recall": html},
            "html_tree": {"tree_bleu": html, "f1": html},
            "vlm_judge": {"overall": vlm},
            "pixelmatch": {"score": global_pixelmatch},
            "visual_block": (
                {
                    "score": visual_block,
                    **({"block_pixelmatch": {"score": block_pixelmatch}} if block_pixelmatch is not None else {}),
                }
                if visual_block is not None
                else {"unsupported": True, "reason": "test_visual_block_unsupported"}
            ),
            "bbox_geometry": {"score": bbox} if bbox is not None else {"unsupported": True, "reason": "test_bbox_unsupported"},
            "cssom_block_style": {"score": cssom} if cssom is not None else {"unsupported": True, "reason": "test_cssom_unsupported"},
            "dreamsim": {"score": dreamsim},
        },
    }


class SimpleWeightedRewardTests(unittest.TestCase):
    def test_perfect_capture_scores_one(self) -> None:
        reward = compute_reward({"captures": {"perfect": _capture_payload()}})

        capture = reward["captures"][0]

        self.assertAlmostEqual(capture["score_before_coverage"], 1.0)
        self.assertAlmostEqual(capture["score"], 1.0)
        self.assertEqual(reward["metadata"]["formula"], "reward_simple_weighted_v1")
        self.assertTrue(capture["gate_passed"])
        self.assertAlmostEqual(RAW_COMPONENT_WEIGHTS["pixel_match"], 0.05)
        self.assertAlmostEqual(RAW_COMPONENT_WEIGHTS["bbox_geometry"], 0.10)
        self.assertAlmostEqual(RAW_COMPONENT_WEIGHTS["cssom_style"], 0.10)

    def test_coverage_is_only_outer_multiplier(self) -> None:
        reward = compute_reward({"captures": {"half-covered": _capture_payload(coverage=0.5)}})

        capture = reward["captures"][0]

        self.assertAlmostEqual(capture["score_before_coverage"], 1.0)
        self.assertAlmostEqual(capture["score"], 0.5)

    def test_gate_failure_blocks_advanced_components(self) -> None:
        reward = compute_reward(
            {
                "captures": {
                    "failed-vlm": _capture_payload(
                        screenshot_size=1.0,
                        html=1.0,
                        vlm=0.39,
                        global_pixelmatch=1.0,
                        visual_block=1.0,
                        bbox=1.0,
                        cssom=1.0,
                        dreamsim=1.0,
                    )
                }
            }
        )

        capture = reward["captures"][0]
        expected = (
            COMPONENT_WEIGHTS["screenshot_size"]
            + COMPONENT_WEIGHTS["html"]
            + COMPONENT_WEIGHTS["vlm"] * 0.39
        )

        self.assertFalse(capture["gate_passed"])
        self.assertEqual(capture["gate_failures"], ["vlm"])
        self.assertAlmostEqual(capture["pixel_match_contribution"], 0.0)
        self.assertAlmostEqual(capture["visual_block_contribution"], 0.0)
        self.assertAlmostEqual(capture["bbox_geometry_contribution"], 0.0)
        self.assertAlmostEqual(capture["cssom_style_contribution"], 0.0)
        self.assertAlmostEqual(capture["dreamsim_contribution"], 0.0)
        self.assertAlmostEqual(capture["score"], expected, places=6)

    def test_global_dreamsim_and_pixelmatch_are_not_visual_block_gated_when_gate_passes(self) -> None:
        reward = compute_reward(
            {
                "captures": {
                    "no-visual-block": _capture_payload(
                        screenshot_size=1.0,
                        html=1.0,
                        vlm=1.0,
                        global_pixelmatch=1.0,
                        visual_block=0.0,
                        bbox=0.0,
                        cssom=0.0,
                        dreamsim=1.0,
                    )
                }
            }
        )

        capture = reward["captures"][0]
        expected = (
            COMPONENT_WEIGHTS["screenshot_size"]
            + COMPONENT_WEIGHTS["html"]
            + COMPONENT_WEIGHTS["vlm"]
            + COMPONENT_WEIGHTS["pixel_match"]
            + COMPONENT_WEIGHTS["dreamsim"]
        )

        self.assertAlmostEqual(capture["dreamsim"], 1.0)
        self.assertAlmostEqual(capture["pixel_match"], 1.0)
        self.assertAlmostEqual(capture["score"], expected, places=6)

    def test_pixel_match_component_averages_global_and_block_pixelmatch(self) -> None:
        reward = compute_reward(
            {
                "captures": {
                    "mixed-pixel": _capture_payload(
                        screenshot_size=1.0,
                        html=1.0,
                        vlm=1.0,
                        global_pixelmatch=1.0,
                        block_pixelmatch=0.5,
                        visual_block=0.0,
                        bbox=0.0,
                        cssom=0.0,
                        dreamsim=0.0,
                    )
                }
            }
        )

        capture = reward["captures"][0]

        self.assertAlmostEqual(capture["pixel_match"], 0.75)
        self.assertAlmostEqual(capture["pixel_match_contribution"], COMPONENT_WEIGHTS["pixel_match"] * 0.75, places=6)

    def test_bbox_and_cssom_components_are_separate(self) -> None:
        reward = compute_reward(
            {
                "captures": {
                    "mixed-layout": _capture_payload(
                        screenshot_size=1.0,
                        html=1.0,
                        vlm=1.0,
                        global_pixelmatch=0.0,
                        visual_block=0.0,
                        bbox=1.0,
                        cssom=0.0,
                        dreamsim=0.0,
                    )
                }
            }
        )

        capture = reward["captures"][0]
        expected = (
            COMPONENT_WEIGHTS["screenshot_size"]
            + COMPONENT_WEIGHTS["html"]
            + COMPONENT_WEIGHTS["vlm"]
            + COMPONENT_WEIGHTS["bbox_geometry"]
        )

        self.assertAlmostEqual(capture["bbox_geometry"], 1.0)
        self.assertAlmostEqual(capture["cssom_style"], 0.0)
        self.assertAlmostEqual(capture["bbox_geometry_contribution"], COMPONENT_WEIGHTS["bbox_geometry"], places=6)
        self.assertAlmostEqual(capture["cssom_style_contribution"], 0.0)
        self.assertAlmostEqual(capture["score"], expected, places=6)

    def test_unsupported_visual_block_components_are_renormalized_not_zeroed(self) -> None:
        reward = compute_reward(
            {
                "captures": {
                    "visual-block-unsupported": _capture_payload(
                        screenshot_size=1.0,
                        html=1.0,
                        vlm=1.0,
                        global_pixelmatch=1.0,
                        visual_block=None,
                        bbox=None,
                        cssom=None,
                        dreamsim=1.0,
                    )
                }
            }
        )

        capture = reward["captures"][0]

        self.assertEqual(capture["unavailable_components"], ["visual_block", "bbox_geometry", "cssom_style"])
        self.assertAlmostEqual(capture["component_denominator"], 0.5)
        self.assertAlmostEqual(capture["score"], 1.0)
        self.assertIsNone(capture["visual_block"])
        self.assertIsNone(capture["bbox_geometry"])
        self.assertIsNone(capture["cssom_style"])

    def test_numeric_zero_visual_block_is_still_a_real_zero(self) -> None:
        reward = compute_reward(
            {
                "captures": {
                    "visual-block-zero": _capture_payload(
                        screenshot_size=1.0,
                        html=1.0,
                        vlm=1.0,
                        global_pixelmatch=1.0,
                        visual_block=0.0,
                        bbox=0.0,
                        cssom=0.0,
                        dreamsim=1.0,
                    )
                }
            }
        )

        capture = reward["captures"][0]
        expected = (
            COMPONENT_WEIGHTS["screenshot_size"]
            + COMPONENT_WEIGHTS["html"]
            + COMPONENT_WEIGHTS["vlm"]
            + COMPONENT_WEIGHTS["pixel_match"]
            + COMPONENT_WEIGHTS["dreamsim"]
        )

        self.assertEqual(capture["unavailable_components"], [])
        self.assertAlmostEqual(capture["component_denominator"], 0.9)
        self.assertAlmostEqual(capture["score"], expected, places=6)


if __name__ == "__main__":
    unittest.main()
