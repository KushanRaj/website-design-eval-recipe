from __future__ import annotations

import unittest

from website_design_eval.reward import compute_reward


def _capture_payload(
    *,
    coverage: float = 1.0,
    screenshot_size: float = 1.0,
    text: float = 1.0,
    vlm: float = 1.0,
    visual_block_size: float = 1.0,
    details: float = 1.0,
) -> dict:
    return {
        "coverage": {"score": coverage},
        "capture": {"weight": 1.0},
        "metrics": {
            "screenshot_size_match": {"score": screenshot_size},
            "html_text": {"bleu_1": text, "rouge_1_recall": text},
            "vlm_judge": {"overall": vlm},
            "visual_block": {
                "size": visual_block_size,
                "text": details,
                "position": details,
                "text_color": details,
            },
            "bbox_geometry": {"score": details},
            "cssom_block_style": {"score": details},
            "dreamsim": {"score": details},
            "pixelmatch": {"score": details},
        },
    }


class RewardCurriculumTests(unittest.TestCase):
    def test_pass1_failure_blocks_later_contributions(self) -> None:
        metrics = {
            "captures": {
                "failed-foundation": _capture_payload(
                    coverage=0.30,
                    screenshot_size=0.30,
                    text=1.0,
                    vlm=1.0,
                    visual_block_size=1.0,
                    details=1.0,
                )
            }
        }

        reward = compute_reward(metrics)
        capture = reward["captures"][0]

        self.assertFalse(capture["foundation_passed"])
        self.assertTrue(capture["content_passed"])
        self.assertFalse(capture["specifics_eligible"])
        self.assertEqual(capture["content_contribution"], 0.0)
        self.assertEqual(capture["specifics_contribution"], 0.0)
        self.assertAlmostEqual(capture["score"], 0.0045)

    def test_pass2_failure_blocks_pass3_but_keeps_pass1_and_pass2_marks(self) -> None:
        metrics = {
            "captures": {
                "failed-content": _capture_payload(
                    coverage=1.0,
                    screenshot_size=1.0,
                    text=0.0,
                    vlm=0.0,
                    visual_block_size=1.0,
                    details=1.0,
                )
            }
        }

        reward = compute_reward(metrics)
        capture = reward["captures"][0]

        self.assertTrue(capture["foundation_passed"])
        self.assertFalse(capture["content_passed"])
        self.assertFalse(capture["specifics_eligible"])
        self.assertEqual(capture["specifics_contribution"], 0.0)
        self.assertAlmostEqual(capture["foundation_contribution"], 0.05)
        self.assertAlmostEqual(capture["content_contribution"], 0.0225)
        self.assertAlmostEqual(capture["score"], 0.0725)

    def test_passing_first_two_passes_unlocks_specifics(self) -> None:
        metrics = {"captures": {"passing": _capture_payload()}}

        reward = compute_reward(metrics)
        capture = reward["captures"][0]

        self.assertTrue(capture["foundation_passed"])
        self.assertTrue(capture["content_passed"])
        self.assertTrue(capture["specifics_eligible"])
        self.assertAlmostEqual(capture["score"], 1.0)
        self.assertAlmostEqual(capture["specifics_contribution"], 0.8)


if __name__ == "__main__":
    unittest.main()
