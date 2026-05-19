from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


PathLike = str | Path
PASS_THRESHOLD = 0.40
PASS_WEIGHTS = {
    "foundation": 0.05,
    "content": 0.15,
    "specifics": 0.80,
}


def _number(value: Any, default: float = 0.0) -> float:
    return float(value) if isinstance(value, int | float) else default


def _metric(payload: dict[str, Any], path: list[str], default: float = 0.0) -> float:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return _number(current, default)


def _optional_metric(payload: dict[str, Any], path: list[str]) -> float | None:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return float(current) if isinstance(current, int | float) else None


def _weighted_available(components: list[tuple[float, float | None]]) -> float:
    available = [(weight, value) for weight, value in components if value is not None]
    denominator = sum(weight for weight, _value in available)
    if denominator <= 0:
        return 0.0
    return sum(weight * value for weight, value in available) / denominator


def _suggested_capture_weight(capture_id: str) -> float:
    if capture_id == "home.desktop.work-dropdown":
        return 0.25
    if capture_id in {"home.desktop.work-section", "contact.desktop.email-focused"}:
        return 0.50
    return 1.0


def _capture_weight(capture_id: str, capture_payload: dict[str, Any], mode: str) -> float:
    if mode == "equal":
        return 1.0
    if mode == "suggested":
        return _suggested_capture_weight(capture_id)
    if mode == "manifest":
        capture = capture_payload.get("capture") or {}
        return max(_number(capture.get("weight"), 1.0), 0.0)
    raise ValueError(f"Unknown weight mode: {mode}")


def _score_capture(capture_payload: dict[str, Any]) -> dict[str, Any]:
    coverage = _number((capture_payload.get("coverage") or {}).get("score"))
    metrics = capture_payload.get("metrics") or {}
    if not isinstance(metrics, dict) or metrics.get("status") == "unsupported":
        foundation = 0.25 * coverage
        foundation_passed = foundation >= PASS_THRESHOLD
        return {
            "coverage": coverage,
            "foundation": foundation,
            "foundation_passed": foundation_passed,
            "content": 0.0,
            "content_passed": False,
            "visual_block_core": 0.0,
            "local_layout_style": 0.0,
            "pixel_precision": None,
            "specifics": 0.0,
            "specifics_eligible": False,
            "foundation_contribution": coverage * PASS_WEIGHTS["foundation"] * foundation,
            "content_contribution": 0.0,
            "specifics_contribution": 0.0,
            "score": round(coverage * PASS_WEIGHTS["foundation"] * foundation, 6),
            "status": "unsupported",
            "reason": metrics.get("reason") or capture_payload.get("missing_reason"),
        }

    screenshot_size = _metric(metrics, ["screenshot_size_match", "score"])
    vlm = _optional_metric(metrics, ["vlm_judge", "overall"])
    visual_block_size_metric = _optional_metric(metrics, ["visual_block", "size"])
    visual_block_size = visual_block_size_metric or 0.0
    foundation = 0.50 * coverage + 0.50 * screenshot_size

    text_bleu = _optional_metric(metrics, ["html_text", "bleu_1"])
    text_rouge = _optional_metric(metrics, ["html_text", "rouge_1_recall"])
    content = _weighted_available(
        [
            (0.35, text_bleu),
            (0.35, text_rouge),
            (0.15, vlm),
            (0.15, visual_block_size_metric),
        ]
    )

    visual_block_text = _metric(metrics, ["visual_block", "text"])
    visual_block_position = _metric(metrics, ["visual_block", "position"])
    visual_block_text_color = _metric(metrics, ["visual_block", "text_color"])
    visual_block_quality = (
        0.40 * visual_block_text
        + 0.35 * visual_block_position
        + 0.25 * visual_block_text_color
    )
    visual_block_core = visual_block_size * visual_block_quality

    bbox = _metric(metrics, ["bbox_geometry", "score"])
    cssom = _metric(metrics, ["cssom_block_style", "score"])
    local_layout_style = visual_block_size * (0.60 * cssom + 0.40 * bbox)
    dreamsim_score = _metric(metrics, ["dreamsim", "score"])
    dreamsim_visual = visual_block_size * dreamsim_score

    raw_pixelmatch = None
    pixel_precision = None
    if isinstance(metrics.get("pixelmatch"), dict) and isinstance(metrics["pixelmatch"].get("score"), int | float):
        raw_pixelmatch = float(metrics["pixelmatch"]["score"])
        pixel_precision = visual_block_size * raw_pixelmatch
        specifics = (
            0.35 * visual_block_core
            + 0.30 * local_layout_style
            + 0.20 * pixel_precision
            + 0.15 * dreamsim_visual
        )
        specifics_mode = "with_pixel_precision"
    else:
        specifics = (0.35 * visual_block_core + 0.30 * local_layout_style + 0.15 * dreamsim_visual) / 0.80
        specifics_mode = "without_pixel_precision"

    foundation_passed = foundation >= PASS_THRESHOLD
    content_passed = content >= PASS_THRESHOLD
    specifics_eligible = foundation_passed and content_passed

    foundation_contribution = coverage * PASS_WEIGHTS["foundation"] * foundation
    content_contribution = (
        coverage * PASS_WEIGHTS["content"] * content
        if foundation_passed
        else 0.0
    )
    specifics_contribution = (
        coverage * PASS_WEIGHTS["specifics"] * specifics
        if specifics_eligible
        else 0.0
    )
    score = foundation_contribution + content_contribution + specifics_contribution

    return {
        "coverage": round(coverage, 6),
        "screenshot_size_match": round(screenshot_size, 6),
        "vlm": round(vlm, 6) if vlm is not None else None,
        "visual_block_size": round(visual_block_size, 6),
        "foundation": round(foundation, 6),
        "foundation_passed": foundation_passed,
        "text_bleu": round(text_bleu, 6) if text_bleu is not None else None,
        "text_rouge": round(text_rouge, 6) if text_rouge is not None else None,
        "content": round(content, 6),
        "content_passed": content_passed,
        "visual_block_core": round(visual_block_core, 6),
        "local_layout_style": round(local_layout_style, 6),
        "dreamsim_score": round(dreamsim_score, 6),
        "dreamsim_visual": round(dreamsim_visual, 6),
        "raw_pixelmatch": round(raw_pixelmatch, 6) if raw_pixelmatch is not None else None,
        "pixel_precision": round(pixel_precision, 6) if pixel_precision is not None else None,
        "specifics": round(specifics, 6),
        "specifics_eligible": specifics_eligible,
        "specifics_mode": specifics_mode,
        "foundation_contribution": round(foundation_contribution, 6),
        "content_contribution": round(content_contribution, 6),
        "specifics_contribution": round(specifics_contribution, 6),
        "score": round(score, 6),
        "status": "scored",
        "reason": None,
    }


def _weighted_mean(rows: list[dict[str, Any]], key: str) -> float:
    denominator = sum(row["weight"] for row in rows)
    if denominator <= 0:
        return 0.0
    return sum(_number(row.get(key)) * row["weight"] for row in rows) / denominator


def compute_reward(metrics: dict[str, Any], *, weight_mode: str = "manifest") -> dict[str, Any]:
    rows = []
    for capture_id, capture_payload in metrics.get("captures", {}).items():
        score = _score_capture(capture_payload)
        weight = _capture_weight(capture_id, capture_payload, weight_mode)
        rows.append({"capture_id": capture_id, "weight": weight, **score})

    summary = {
        "score": round(_weighted_mean(rows, "score"), 6),
        "foundation": round(_weighted_mean(rows, "foundation"), 6),
        "content": round(_weighted_mean(rows, "content"), 6),
        "specifics": round(_weighted_mean(rows, "specifics"), 6),
        "foundation_contribution": round(_weighted_mean(rows, "foundation_contribution"), 6),
        "content_contribution": round(_weighted_mean(rows, "content_contribution"), 6),
        "specifics_contribution": round(_weighted_mean(rows, "specifics_contribution"), 6),
        "capture_count": len(rows),
        "scored_capture_count": sum(1 for row in rows if row["status"] == "scored"),
        "foundation_pass_count": sum(1 for row in rows if row.get("foundation_passed")),
        "content_pass_count": sum(1 for row in rows if row.get("content_passed")),
        "specifics_eligible_count": sum(1 for row in rows if row.get("specifics_eligible")),
        "pass_threshold": PASS_THRESHOLD,
        "weight_mode": weight_mode,
        "pixel_precision_included": any(row.get("pixel_precision") is not None for row in rows),
    }
    return {
        "metadata": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "source_metrics": metrics.get("metadata", {}),
            "formula": "reward_curriculum_v0",
        },
        "summary": summary,
        "captures": rows,
    }


def compute_reward_from_file(path: PathLike, *, weight_mode: str = "manifest") -> dict[str, Any]:
    metrics = json.loads(Path(path).read_text(encoding="utf-8"))
    return compute_reward(metrics, weight_mode=weight_mode)


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _md_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_fmt(value) for value in row) + " |")
    return "\n".join(lines)


def build_reward_markdown(reward: dict[str, Any]) -> str:
    summary = reward["summary"]
    capture_rows = [
        [
            row["capture_id"],
            row["weight"],
            row["coverage"],
            row["foundation"],
            row.get("foundation_passed"),
            row["content"],
            row.get("content_passed"),
            row["specifics"],
            row.get("specifics_eligible"),
            row.get("raw_pixelmatch"),
            row.get("pixel_precision"),
            row.get("dreamsim_visual"),
            row["score"],
            row["status"],
            row.get("reason"),
        ]
        for row in reward["captures"]
    ]
    return "\n".join(
        [
            "# Reward Curriculum V0 Report",
            "",
            f"Generated at: `{reward['metadata']['generated_at']}`",
            "",
            "## Summary",
            "",
            _md_table(
                ["Key", "Value"],
                [
                    ["score", summary["score"]],
                    ["foundation", summary["foundation"]],
                    ["content", summary["content"]],
                    ["specifics", summary["specifics"]],
                    ["foundation_contribution", summary["foundation_contribution"]],
                    ["content_contribution", summary["content_contribution"]],
                    ["specifics_contribution", summary["specifics_contribution"]],
                    ["pass_threshold", summary["pass_threshold"]],
                    ["foundation_pass_count", summary["foundation_pass_count"]],
                    ["content_pass_count", summary["content_pass_count"]],
                    ["specifics_eligible_count", summary["specifics_eligible_count"]],
                    ["weight_mode", summary["weight_mode"]],
                    ["pixel_precision_included", summary["pixel_precision_included"]],
                ],
            ),
            "",
            "## Captures",
            "",
            _md_table(
                [
                    "Capture",
                    "Weight",
                    "Coverage",
                    "Pass 1",
                    "P1 Pass",
                    "Pass 2",
                    "P2 Pass",
                    "Pass 3",
                    "P3 Eligible",
                    "Pixelmatch",
                    "Pixel Precision",
                    "DreamSim Visual",
                    "Score",
                    "Status",
                    "Reason",
                ],
                capture_rows,
            ),
            "",
        ]
    )
