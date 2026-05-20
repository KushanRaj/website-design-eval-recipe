from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


PathLike = str | Path

RAW_COMPONENT_WEIGHTS = {
    "screenshot_size": 0.05,
    "html": 0.10,
    "vlm": 0.20,
    "pixel_match": 0.05,
    "visual_block": 0.0,
    "bbox_geometry": 0.10,
    "cssom_style": 0.10,
    "dreamsim": 0.10,
}
RAW_COMPONENT_TOTAL = sum(RAW_COMPONENT_WEIGHTS.values())
COMPONENT_WEIGHTS = {
    key: value / RAW_COMPONENT_TOTAL for key, value in RAW_COMPONENT_WEIGHTS.items()
}
GATE_THRESHOLDS = {
    "screenshot_size": 0.40,
    "html": 0.40,
    "vlm": 0.40,
}


def _number(value: Any, default: float = 0.0) -> float:
    return float(value) if isinstance(value, int | float) else default


def _metric(payload: dict[str, Any], path: list[str], default: float = 0.0) -> float:
    value = _optional_metric(payload, path)
    return value if value is not None else default


def _optional_metric(payload: dict[str, Any], path: list[str]) -> float | None:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        if current.get("unsupported") or current.get("skipped") or current.get("error"):
            return None
        current = current.get(key)
    return float(current) if isinstance(current, int | float) else None


def _mean_available(values: list[float | None]) -> float | None:
    available = [value for value in values if value is not None]
    if not available:
        return None
    return sum(available) / len(available)


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


def _manifest_item_weight(payload: dict[str, Any], key: str) -> float:
    item = payload.get(key) or {}
    return max(_number(item.get("weight"), 1.0), 0.0)


def _component_contributions(
    components: dict[str, float | None],
    *,
    gate_passed: bool,
) -> tuple[dict[str, float], float]:
    available_components = {
        key
        for key, value in components.items()
        if key in RAW_COMPONENT_WEIGHTS and value is not None
    }
    active_components = set(available_components)
    denominator = sum(RAW_COMPONENT_WEIGHTS[key] for key in active_components)
    if not gate_passed:
        active_components = available_components & set(GATE_THRESHOLDS)
        denominator = RAW_COMPONENT_TOTAL
    if denominator <= 0:
        return {key: 0.0 for key in RAW_COMPONENT_WEIGHTS}, 0.0
    return (
        {
            key: float(components[key]) * RAW_COMPONENT_WEIGHTS[key] / denominator
            if key in active_components
            else 0.0
            for key in RAW_COMPONENT_WEIGHTS
        },
        denominator,
    )


def _gate_failures(components: dict[str, float | None]) -> list[str]:
    return [
        key
        for key, threshold in GATE_THRESHOLDS.items()
        if components.get(key) is not None and float(components[key]) < threshold
    ]


def _rounded_or_none(value: float | None) -> float | None:
    return round(value, 6) if value is not None else None


def _score_capture(capture_payload: dict[str, Any]) -> dict[str, Any]:
    coverage = _number((capture_payload.get("coverage") or {}).get("score"))
    metrics = capture_payload.get("metrics") or {}
    if not isinstance(metrics, dict) or metrics.get("status") == "unsupported":
        reason = metrics.get("reason") if isinstance(metrics, dict) else None
        return {
            "coverage": round(coverage, 6),
            "screenshot_size": 0.0,
            "html": 0.0,
            "vlm": 0.0,
            "pixel_match": 0.0,
            "visual_block": 0.0,
            "bbox_geometry": 0.0,
            "cssom_style": 0.0,
            "dreamsim": 0.0,
            "gate_passed": False,
            "gate_failures": list(GATE_THRESHOLDS),
            "raw_component_score": 0.0,
            "score_before_coverage": 0.0,
            "score": 0.0,
            "status": "unsupported",
            "reason": reason or capture_payload.get("missing_reason"),
        }

    screenshot_size = _optional_metric(metrics, ["screenshot_size_match", "score"])
    html = _mean_available(
        [
            _optional_metric(metrics, ["html_text", "bleu_1"]),
            _optional_metric(metrics, ["html_text", "rouge_1_recall"]),
            _optional_metric(metrics, ["html_tree", "tree_bleu"]),
            _optional_metric(metrics, ["html_tree", "f1"]),
        ]
    )
    vlm = _optional_metric(metrics, ["vlm_judge", "overall"])
    global_pixelmatch = _optional_metric(metrics, ["pixelmatch", "score"])
    block_pixelmatch = _optional_metric(metrics, ["visual_block", "block_pixelmatch", "score"])
    pixel_match = global_pixelmatch
    visual_block = _optional_metric(metrics, ["visual_block", "score"])
    bbox_geometry = _optional_metric(metrics, ["bbox_geometry", "score"])
    cssom_style = _optional_metric(metrics, ["cssom_block_style", "score"])
    dreamsim = _optional_metric(metrics, ["dreamsim", "score"])

    components = {
        "screenshot_size": screenshot_size,
        "html": html,
        "vlm": vlm,
        "pixel_match": pixel_match,
        "visual_block": visual_block,
        "bbox_geometry": bbox_geometry,
        "cssom_style": cssom_style,
        "dreamsim": dreamsim,
    }
    gate_failures = _gate_failures(components)
    gate_passed = not gate_failures
    contributions, component_denominator = _component_contributions(components, gate_passed=gate_passed)
    score_before_coverage = sum(contributions.values())
    score = coverage * score_before_coverage
    unavailable_components = [
        key
        for key in RAW_COMPONENT_WEIGHTS
        if components.get(key) is None
    ]

    return {
        "coverage": round(coverage, 6),
        "screenshot_size": _rounded_or_none(screenshot_size),
        "html": _rounded_or_none(html),
        "vlm": _rounded_or_none(vlm),
        "global_pixelmatch": round(global_pixelmatch, 6) if global_pixelmatch is not None else None,
        "block_pixelmatch": round(block_pixelmatch, 6) if block_pixelmatch is not None else None,
        "pixel_match": _rounded_or_none(pixel_match),
        "visual_block": _rounded_or_none(visual_block),
        "bbox_geometry": _rounded_or_none(bbox_geometry),
        "cssom_style": _rounded_or_none(cssom_style),
        "dreamsim": _rounded_or_none(dreamsim),
        "gate_passed": gate_passed,
        "gate_failures": gate_failures,
        "unavailable_components": unavailable_components,
        "component_denominator": round(component_denominator, 6),
        "raw_component_score": round(
            sum(
                RAW_COMPONENT_WEIGHTS[key] * float(components[key])
                for key in RAW_COMPONENT_WEIGHTS
                if components.get(key) is not None
            ),
            6,
        ),
        "score_before_coverage": round(score_before_coverage, 6),
        "screenshot_size_contribution": round(contributions["screenshot_size"], 6),
        "html_contribution": round(contributions["html"], 6),
        "vlm_contribution": round(contributions["vlm"], 6),
        "pixel_match_contribution": round(contributions["pixel_match"], 6),
        "visual_block_contribution": round(contributions["visual_block"], 6),
        "bbox_geometry_contribution": round(contributions["bbox_geometry"], 6),
        "cssom_style_contribution": round(contributions["cssom_style"], 6),
        "dreamsim_contribution": round(contributions["dreamsim"], 6),
        "score": round(score, 6),
        "status": "scored",
        "reason": None,
    }


def _mean_animation_target_scores(animation_metrics: dict[str, Any], path: list[str]) -> float | None:
    values = []
    for target in animation_metrics.get("targets") or []:
        current: Any = target.get("scores") or {}
        for key in path:
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(key)
        if isinstance(current, int | float):
            values.append(float(current))
    if not values:
        return None
    return sum(values) / len(values)


def _score_animation(animation_payload: dict[str, Any]) -> dict[str, Any]:
    metrics = animation_payload.get("metrics") or {}
    if not isinstance(metrics, dict) or metrics.get("status") != "scored":
        return {
            "coverage": 0.0,
            "screenshot_size": None,
            "html": None,
            "vlm": None,
            "global_pixelmatch": None,
            "block_pixelmatch": None,
            "pixel_match": None,
            "visual_block": None,
            "bbox_geometry": None,
            "cssom_style": None,
            "dreamsim": None,
            "gate_passed": False,
            "gate_failures": [],
            "unavailable_components": list(RAW_COMPONENT_WEIGHTS),
            "component_denominator": 0.0,
            "raw_component_score": 0.0,
            "score_before_coverage": 0.0,
            "screenshot_size_contribution": 0.0,
            "html_contribution": 0.0,
            "vlm_contribution": 0.0,
            "pixel_match_contribution": 0.0,
            "visual_block_contribution": 0.0,
            "bbox_geometry_contribution": 0.0,
            "cssom_style_contribution": 0.0,
            "dreamsim_contribution": 0.0,
            "score": 0.0,
            "status": "unsupported",
            "reason": metrics.get("reason") or animation_payload.get("missing_reason"),
        }

    motion_bbox = _mean_animation_target_scores(metrics, ["motion", "bbox_iou"])
    motion_delta = _mean_animation_target_scores(metrics, ["motion", "motion_delta"])
    bbox_geometry = _mean_available([motion_bbox, motion_delta])
    pixel_match = _mean_animation_target_scores(metrics, ["color", "target_box_pixelmatch"])
    cssom_style = _mean_animation_target_scores(metrics, ["color", "cssom_color"])
    coverage = 1.0 if any(value is not None for value in (bbox_geometry, pixel_match, cssom_style)) else 0.0

    components = {
        "screenshot_size": None,
        "html": None,
        "vlm": None,
        "pixel_match": pixel_match,
        "visual_block": None,
        "bbox_geometry": bbox_geometry,
        "cssom_style": cssom_style,
        "dreamsim": None,
    }
    gate_failures = _gate_failures(components)
    gate_passed = not gate_failures
    contributions, component_denominator = _component_contributions(components, gate_passed=gate_passed)
    score_before_coverage = sum(contributions.values())
    score = coverage * score_before_coverage
    unavailable_components = [
        key
        for key in RAW_COMPONENT_WEIGHTS
        if components.get(key) is None
    ]

    return {
        "coverage": round(coverage, 6),
        "screenshot_size": None,
        "html": None,
        "vlm": None,
        "global_pixelmatch": None,
        "block_pixelmatch": None,
        "pixel_match": _rounded_or_none(pixel_match),
        "visual_block": None,
        "bbox_geometry": _rounded_or_none(bbox_geometry),
        "cssom_style": _rounded_or_none(cssom_style),
        "dreamsim": None,
        "gate_passed": gate_passed,
        "gate_failures": gate_failures,
        "unavailable_components": unavailable_components,
        "component_denominator": round(component_denominator, 6),
        "raw_component_score": round(
            sum(
                RAW_COMPONENT_WEIGHTS[key] * float(components[key])
                for key in RAW_COMPONENT_WEIGHTS
                if components.get(key) is not None
            ),
            6,
        ),
        "score_before_coverage": round(score_before_coverage, 6),
        "screenshot_size_contribution": round(contributions["screenshot_size"], 6),
        "html_contribution": round(contributions["html"], 6),
        "vlm_contribution": round(contributions["vlm"], 6),
        "pixel_match_contribution": round(contributions["pixel_match"], 6),
        "visual_block_contribution": round(contributions["visual_block"], 6),
        "bbox_geometry_contribution": round(contributions["bbox_geometry"], 6),
        "cssom_style_contribution": round(contributions["cssom_style"], 6),
        "dreamsim_contribution": round(contributions["dreamsim"], 6),
        "score": round(score, 6),
        "status": "scored",
        "reason": None,
    }


def _weighted_mean(rows: list[dict[str, Any]], key: str) -> float:
    denominator = sum(row["weight"] for row in rows)
    if denominator <= 0:
        return 0.0
    return sum(_number(row.get(key)) * row["weight"] for row in rows) / denominator


def _weighted_mean_available(rows: list[dict[str, Any]], key: str) -> float | None:
    available = [row for row in rows if row.get(key) is not None]
    denominator = sum(row["weight"] for row in available)
    if denominator <= 0:
        return None
    return sum(float(row[key]) * row["weight"] for row in available) / denominator


def _summary_score(rows: list[dict[str, Any]], key: str) -> float | None:
    return _rounded_or_none(_weighted_mean_available(rows, key))


def compute_reward(metrics: dict[str, Any], *, weight_mode: str = "manifest") -> dict[str, Any]:
    rows = []
    for capture_id, capture_payload in metrics.get("captures", {}).items():
        score = _score_capture(capture_payload)
        weight = _capture_weight(capture_id, capture_payload, weight_mode)
        rows.append({"capture_id": capture_id, "item_type": "capture", "weight": weight, **score})
    for animation_id, animation_payload in metrics.get("animations", {}).items():
        score = _score_animation(animation_payload)
        weight = 1.0 if weight_mode in {"equal", "suggested"} else _manifest_item_weight(animation_payload, "animation")
        rows.append({"capture_id": animation_id, "item_type": "animation", "weight": weight, **score})

    summary = {
        "score": round(_weighted_mean(rows, "score"), 6),
        "score_before_coverage": round(_weighted_mean(rows, "score_before_coverage"), 6),
        "coverage": round(_weighted_mean(rows, "coverage"), 6),
        "screenshot_size": _summary_score(rows, "screenshot_size"),
        "html": _summary_score(rows, "html"),
        "vlm": _summary_score(rows, "vlm"),
        "global_pixelmatch": _summary_score(rows, "global_pixelmatch"),
        "block_pixelmatch": _summary_score(rows, "block_pixelmatch"),
        "pixel_match": _summary_score(rows, "pixel_match"),
        "visual_block": _summary_score(rows, "visual_block"),
        "bbox_geometry": _summary_score(rows, "bbox_geometry"),
        "cssom_style": _summary_score(rows, "cssom_style"),
        "dreamsim": _summary_score(rows, "dreamsim"),
        "screenshot_size_contribution": round(_weighted_mean(rows, "screenshot_size_contribution"), 6),
        "html_contribution": round(_weighted_mean(rows, "html_contribution"), 6),
        "vlm_contribution": round(_weighted_mean(rows, "vlm_contribution"), 6),
        "pixel_match_contribution": round(_weighted_mean(rows, "pixel_match_contribution"), 6),
        "visual_block_contribution": round(_weighted_mean(rows, "visual_block_contribution"), 6),
        "bbox_geometry_contribution": round(_weighted_mean(rows, "bbox_geometry_contribution"), 6),
        "cssom_style_contribution": round(_weighted_mean(rows, "cssom_style_contribution"), 6),
        "dreamsim_contribution": round(_weighted_mean(rows, "dreamsim_contribution"), 6),
        "capture_count": len(rows),
        "scored_capture_count": sum(1 for row in rows if row["status"] == "scored"),
        "static_capture_count": sum(1 for row in rows if row["item_type"] == "capture"),
        "animation_capture_count": sum(1 for row in rows if row["item_type"] == "animation"),
        "scored_animation_capture_count": sum(
            1 for row in rows if row["item_type"] == "animation" and row["status"] == "scored"
        ),
        "gate_pass_count": sum(1 for row in rows if row.get("gate_passed")),
        "weight_mode": weight_mode,
        "gate_thresholds": GATE_THRESHOLDS,
        "raw_component_weights": RAW_COMPONENT_WEIGHTS,
        "normalized_component_weights": {
            key: round(value, 6) for key, value in COMPONENT_WEIGHTS.items()
        },
        "unavailable_component_counts": {
            key: sum(1 for row in rows if key in row.get("unavailable_components", []))
            for key in RAW_COMPONENT_WEIGHTS
        },
    }
    return {
        "metadata": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "source_metrics": metrics.get("metadata", {}),
            "formula": "reward_simple_weighted_v1",
            "formula_text": (
                "coverage * normalized_weighted_sum("
                "screenshot_size=.05, html=.10, vlm=.20, pixel_match=.05, visual_block=.20, "
                "bbox_geometry=.10, cssom_style=.10, dreamsim=.10)"
            ),
            "gate_text": (
                "If screenshot_size, html, or vlm is below its threshold, "
                "pixel_match, bbox_geometry, cssom_style, and dreamsim contribute zero; "
                "visual_block.score is diagnostic-only and has zero reward weight."
            ),
            "unavailable_component_text": (
                "Missing, skipped, errored, or unsupported component scores are removed from that "
                "capture's available denominator when gates pass; numeric zero remains a real zero."
            ),
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
            row.get("item_type", "capture"),
            row.get("capture_id"),
            row.get("weight"),
            row.get("coverage"),
            row.get("screenshot_size"),
            row.get("html"),
            row.get("vlm"),
            row.get("pixel_match"),
            row.get("visual_block"),
            row.get("bbox_geometry"),
            row.get("cssom_style"),
            row.get("dreamsim"),
            row.get("component_denominator"),
            ",".join(row.get("unavailable_components", [])),
            row.get("gate_passed"),
            row.get("score_before_coverage"),
            row.get("score"),
            row.get("status"),
            row.get("reason"),
        ]
        for row in reward["captures"]
    ]
    return "\n".join(
        [
            "# Simple Weighted Reward V1 Report",
            "",
            f"Generated at: `{reward['metadata']['generated_at']}`",
            "",
            "## Formula",
            "",
            "```text",
            "capture_reward = coverage * (",
            "  0.05 * screenshot_size",
            "+ 0.10 * html",
            "+ 0.20 * vlm",
            "+ 0.05 * pixel_match",
            "+ 0.00 * visual_block",
            "+ 0.10 * bbox_geometry",
            "+ 0.10 * cssom_style",
            "+ 0.10 * dreamsim",
            f") / {RAW_COMPONENT_TOTAL:.2f}",
            "",
            "If a component is missing/skipped/errored/unsupported, remove its weight",
            "from that capture denominator when gates pass. Numeric 0 is still a real 0.",
            "",
            "If screenshot_size < 0.40, html < 0.40, or vlm < 0.40,",
            "then pixel_match, bbox_geometry, cssom_style, and dreamsim contribute 0.",
            "visual_block.score is not computed for reward; visual-block matching is only used by bbox/CSSOM.",
            "```",
            "",
            "## Summary",
            "",
            _md_table(
                ["Key", "Value"],
                [
                    ["score", summary["score"]],
                    ["score_before_coverage", summary["score_before_coverage"]],
                    ["coverage", summary["coverage"]],
                    ["screenshot_size", summary["screenshot_size"]],
                    ["html", summary["html"]],
                    ["vlm", summary["vlm"]],
                    ["global_pixelmatch", summary["global_pixelmatch"]],
                    ["block_pixelmatch", summary["block_pixelmatch"]],
                    ["pixel_match", summary["pixel_match"]],
                    ["visual_block", summary["visual_block"]],
                    ["bbox_geometry", summary["bbox_geometry"]],
                    ["cssom_style", summary["cssom_style"]],
                    ["dreamsim", summary["dreamsim"]],
                    ["gate_pass_count", summary["gate_pass_count"]],
                    ["unavailable_component_counts", summary["unavailable_component_counts"]],
                    ["weight_mode", summary["weight_mode"]],
                    ["scored_capture_count", summary["scored_capture_count"]],
                    ["capture_count", summary["capture_count"]],
                ],
            ),
            "",
            "## Captures",
            "",
            _md_table(
                [
                    "Type",
                    "Capture",
                    "Weight",
                    "Coverage",
                    "Size",
                    "HTML",
                    "VLM",
                    "Pixel",
                    "Visual Block",
                    "BBox",
                    "CSSOM",
                    "DreamSim",
                    "Denom",
                    "Unavailable",
                    "Gate",
                    "Before Coverage",
                    "Score",
                    "Status",
                    "Reason",
                ],
                capture_rows,
            ),
            "",
        ]
    )
