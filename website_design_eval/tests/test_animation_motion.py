from __future__ import annotations

import unittest

from website_design_eval.evaluator import _score_motion_target


def _row(x: float, y: float, width: float = 10, height: float = 10) -> dict:
    return {"sample": {"bbox_px": {"x": x, "y": y, "width": width, "height": height}}}


class AnimationMotionScoringTests(unittest.TestCase):
    def test_motion_delta_matches_same_direction_vector(self) -> None:
        score = _score_motion_target(
            [_row(0, 0), _row(100, 0)],
            [_row(10, 10), _row(110, 10)],
        )

        self.assertEqual(score["motion_delta"], 1.0)
        self.assertEqual(score["motion_delta_intervals"][0]["method"], "vector_delta")

    def test_motion_delta_penalizes_wrong_axis_movement(self) -> None:
        score = _score_motion_target(
            [_row(0, 0), _row(100, 0)],
            [_row(0, 0), _row(0, 100)],
        )

        self.assertEqual(score["motion_delta"], 0.0)
        self.assertEqual(score["motion_delta_intervals"][0]["reference_delta_xy"], [100.0, 0.0])
        self.assertEqual(score["motion_delta_intervals"][0]["candidate_delta_xy"], [0.0, 100.0])

    def test_motion_delta_penalizes_candidate_motion_when_reference_stationary(self) -> None:
        score = _score_motion_target(
            [_row(0, 0), _row(0, 0)],
            [_row(0, 0), _row(40, 0)],
        )

        self.assertEqual(score["motion_delta"], 0.0)
        self.assertEqual(
            score["motion_delta_intervals"][0]["reason"],
            "reference_stationary_candidate_moved",
        )

    def test_motion_delta_keeps_both_stationary_as_perfect(self) -> None:
        score = _score_motion_target(
            [_row(0, 0), _row(0, 0)],
            [_row(10, 10), _row(10, 10)],
        )

        self.assertEqual(score["motion_delta"], 1.0)
        self.assertEqual(score["motion_delta_intervals"][0]["reason"], "both_stationary")


if __name__ == "__main__":
    unittest.main()
