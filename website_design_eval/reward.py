from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


PathLike = str | Path


def _number(value: Any, default: float = 0.0) -> float:
    return float(value) if isinstance(value, int | float) else default


def _metric(payload: dict[str, Any], path: list[str], default: float = 0.0) -> float:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return _number(current, default)


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
        return {
            "coverage": coverage,
            "foundation": foundation,
            "content": 0.0,
            "visual_block_core": 0.0,
            "local_layout_style": 0.0,
            "pixel_precision": None,
            "specifics": 0.0,
            "foundation_contribution": coverage * 0.05 * foundation,
            "content_contribution": 0.0,
            "specifics_contribution": 0.0,
            "score": 0.0,
            "status": "unsupported",
            "reason": metrics.get("reason") or capture_payload.get("missing_reason"),
        }

    screenshot_size = _metric(metrics, ["screenshot_size_match", "score"])
    vlm = _metric(metrics, ["vlm_judge", "overall"])
    visual_block_size = _metric(metrics, ["visual_block", "size"])
    foundation = 0.50 * coverage + 0.50 * screenshot_size

    text_bleu = _metric(metrics, ["html_text", "bleu_1"])
    text_rouge = _metric(metrics, ["html_text", "rouge_1_recall"])
    content = (
        0.35 * text_bleu
        + 0.35 * text_rouge
        + 0.15 * vlm
        + 0.15 * visual_block_size
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

    foundation_contribution = coverage * 0.05 * foundation
    content_contribution = coverage * 0.15 * content
    specifics_contribution = coverage * 0.80 * specifics
    score = foundation_contribution + content_contribution + specifics_contribution

    return {
        "coverage": round(coverage, 6),
        "screenshot_size_match": round(screenshot_size, 6),
        "vlm": round(vlm, 6),
        "visual_block_size": round(visual_block_size, 6),
        "foundation": round(foundation, 6),
        "text_bleu": round(text_bleu, 6),
        "text_rouge": round(text_rouge, 6),
        "content": round(content, 6),
        "visual_block_core": round(visual_block_core, 6),
        "local_layout_style": round(local_layout_style, 6),
        "dreamsim_score": round(dreamsim_score, 6),
        "dreamsim_visual": round(dreamsim_visual, 6),
        "raw_pixelmatch": round(raw_pixelmatch, 6) if raw_pixelmatch is not None else None,
        "pixel_precision": round(pixel_precision, 6) if pixel_precision is not None else None,
        "specifics": round(specifics, 6),
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
            row["content"],
            row["specifics"],
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
                    "Pass 2",
                    "Pass 3",
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
