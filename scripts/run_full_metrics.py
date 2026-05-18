from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from website_design_eval.scoring import (
    _pick_torch_device,
    cssom_block_style_score,
    dreamsim_distance,
    extract_webcode2m_bbox_tree,
    presentation_diff_tags,
    score_screenshot_pair,
    visual_block_score,
    vlm_judge_score,
    webcoderbench_tags,
    webcoderbench_visual_quality_scores,
    webcode2m_bbox_tree_to_html,
    webcode2m_bbox_tree_to_style_list,
    webcode2m_dom_score,
    webcode2m_text_score,
)
from website_design_eval.block_visual import _score_bbox_geometry


REPO_ROOT = Path(__file__).resolve().parents[1]
REFERENCE_ROOT = REPO_ROOT / "test-site"
REFERENCE_MANIFEST = REFERENCE_ROOT / "screenshot-manifest.json"
DEFAULT_CANDIDATES = [
    REPO_ROOT / "reproductions" / "claude-attempt-01",
    REPO_ROOT / "reproductions" / "claude-attempt-02-bad",
]


def log(message: str) -> None:
    print(f"[metrics] {message}", file=sys.stderr, flush=True)


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def enabled_capture(capture: dict[str, Any]) -> bool:
    return capture.get("enabled", True) is not False


def manifest_output_dir(root: Path, manifest: dict[str, Any]) -> Path:
    return (root / manifest.get("outputDir", "./screenshots")).resolve()


def html_path_for_capture(root: Path, capture: dict[str, Any]) -> Path:
    return (root / capture["path"].lstrip("/")).resolve()


def screenshot_path_for_capture(root: Path, manifest: dict[str, Any], capture_id: str) -> Path:
    return manifest_output_dir(root, manifest) / f"{capture_id}.png"


def capture_viewport(capture: dict[str, Any], manifest: dict[str, Any]) -> tuple[int, int]:
    viewport = capture.get("viewport") or manifest.get("defaults", {}).get("viewport") or {}
    return int(viewport.get("width", 1440)), int(viewport.get("height", 900))


def metric_call(name: str, fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except Exception as exc:
        return {
            "error": {
                "metric": name,
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(limit=8),
            }
        }


def is_error(value: Any) -> bool:
    return isinstance(value, dict) and "error" in value


def node_summary(node: dict[str, Any] | None) -> dict[str, Any]:
    if not node:
        return {
            "node_count": 0,
            "leaf_count": 0,
            "max_depth": 0,
        }

    node_count = 0
    leaf_count = 0
    max_depth = 0
    tag_counts: dict[str, int] = {}

    def walk(item: dict[str, Any], depth: int) -> None:
        nonlocal node_count, leaf_count, max_depth
        node_count += 1
        max_depth = max(max_depth, depth)
        tag = str(item.get("type", "unknown"))
        tag_counts[tag] = tag_counts.get(tag, 0) + 1
        children = item.get("children") or []
        if not children:
            leaf_count += 1
        for child in children:
            walk(child, depth + 1)

    walk(node, 0)
    return {
        "node_count": node_count,
        "leaf_count": leaf_count,
        "max_depth": max_depth,
        "tag_counts": dict(sorted(tag_counts.items(), key=lambda item: (-item[1], item[0]))),
    }


def write_bbox_outputs(
    output_dir: Path,
    site_name: str,
    page: str,
    html_path: Path,
    viewport: tuple[int, int],
) -> dict[str, Any]:
    tree = metric_call(
        "webcode2m_bbox_tree",
        lambda: extract_webcode2m_bbox_tree(html_path, viewport=viewport),
    )
    if is_error(tree):
        return tree

    bbox_dir = output_dir / "webcode2m-bbox-trees" / site_name
    bbox_dir.mkdir(parents=True, exist_ok=True)
    tree_path = bbox_dir / f"{page}.tree.json"
    bbox_html_path = bbox_dir / f"{page}.bbox.html"
    style_list_path = bbox_dir / f"{page}.style-list.json"

    bbox_html = webcode2m_bbox_tree_to_html(tree, size=viewport) if tree else ""
    style_list = webcode2m_bbox_tree_to_style_list(tree) if tree else []

    tree_path.write_text(json.dumps(tree, indent=2, sort_keys=True), encoding="utf-8")
    bbox_html_path.write_text(bbox_html, encoding="utf-8")
    style_list_path.write_text(json.dumps(style_list, indent=2, sort_keys=True), encoding="utf-8")

    return {
        **node_summary(tree),
        "bbox_html_bytes": len(bbox_html.encode("utf-8")),
        "style_list_count": len(style_list),
        "tree_path": str(tree_path),
        "bbox_html_path": str(bbox_html_path),
        "style_list_path": str(style_list_path),
        "viewport": {"width": viewport[0], "height": viewport[1]},
        "source": "WebCode2M bbox tree extraction wrapper",
    }


def mean(values: list[Any]) -> float | None:
    filtered = [float(value) for value in values if isinstance(value, int | float)]
    if not filtered:
        return None
    return round(sum(filtered) / len(filtered), 6)


def get_in(item: Any, path: list[str]) -> Any:
    current = item
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def score_from_dreamsim(distance: Any) -> float | None:
    if not isinstance(distance, int | float):
        return None
    return round(max(0.0, min(1.0, 1.0 - float(distance))), 6)


def run_dreamsim_pair(
    reference_screenshot: Path,
    candidate_screenshot: Path,
    *,
    device: str | None,
    dreamsim_type: str,
    cache_dir: str | None,
) -> dict[str, Any]:
    distance = dreamsim_distance(
        reference_screenshot,
        candidate_screenshot,
        device=device,
        dreamsim_type=dreamsim_type,
        cache_dir=cache_dir,
    )
    return {
        "distance": distance,
        "score": score_from_dreamsim(distance),
        "dreamsim_type": dreamsim_type,
        "device": _pick_torch_device(device),
    }


def flatten_metric_means(pairs: dict[str, Any], path: list[str]) -> float | None:
    values = []
    for pair in pairs.values():
        value = get_in(pair, path)
        if isinstance(value, int | float):
            values.append(value)
    return mean(values)


def candidate_final_summary(candidate_result: dict[str, Any]) -> dict[str, Any]:
    pairs = candidate_result["pairs"]
    html_pages = candidate_result["html_pages"]
    expected_count = candidate_result["coverage"]["reference_enabled_capture_count"]
    matched_count = candidate_result["coverage"]["matched_capture_count"]
    coverage = matched_count / expected_count if expected_count else 0.0

    screenshot_group = mean(
        [
            flatten_metric_means(pairs, ["screenshot_pair", "pixelmatch", "score"]),
            flatten_metric_means(pairs, ["screenshot_pair", "ssim"]),
            flatten_metric_means(pairs, ["screenshot_pair", "clip"]),
            mean(
                [
                    score_from_dreamsim(get_in(pair, ["dreamsim", "distance"]))
                    for pair in pairs.values()
                ]
            ),
        ]
    )

    html_group = mean(
        [
            mean(
                [
                    mean([get_in(page, ["webcode2m_text", "bleu_1"]), get_in(page, ["webcode2m_text", "rouge_1_recall"])])
                    for page in html_pages.values()
                ]
            ),
            mean([get_in(page, ["webcode2m_dom", "f1"]) for page in html_pages.values()]),
        ]
    )

    block_group = mean(
        [
            flatten_metric_means(pairs, ["visual_block", "score"]),
            flatten_metric_means(pairs, ["element_block_pixelmatch", "score"]),
            flatten_metric_means(pairs, ["bbox_geometry", "score"]),
            flatten_metric_means(pairs, ["cssom_block_style", "score"]),
        ]
    )

    vlm_group = flatten_metric_means(pairs, ["vlm_judge", "overall"])

    weighted_groups = {
        "screenshot": {"weight": 0.35, "score": screenshot_group},
        "html": {"weight": 0.15, "score": html_group},
        "block": {"weight": 0.30, "score": block_group},
        "vlm": {"weight": 0.20, "score": vlm_group},
    }
    available = [
        (payload["weight"], payload["score"])
        for payload in weighted_groups.values()
        if isinstance(payload["score"], int | float)
    ]
    if available:
        base = sum(weight * score for weight, score in available) / sum(weight for weight, _score in available)
    else:
        base = 0.0

    return {
        "experimental_final_score": round(float(base * coverage), 6),
        "uncoverage_penalized": True,
        "coverage": round(float(coverage), 6),
        "matched_capture_count": matched_count,
        "reference_enabled_capture_count": expected_count,
        "component_groups": weighted_groups,
        "formula": "coverage * weighted_mean({screenshot:.35, html:.15, block:.30, vlm:.20}, available groups only)",
        "note": "Diagnostic score for comparison only; this is not a settled reward formula.",
    }


def fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) if value else ""
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    return str(value)


def md_escape(value: Any) -> str:
    return fmt(value).replace("|", "\\|").replace("\n", " ")


def md_table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return "_No rows._\n"
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(md_escape(value) for value in row) + " |")
    return "\n".join(lines) + "\n"


def screenshot_size_label(size_payload: dict[str, Any], side: str) -> str:
    image_size = size_payload.get(side) if isinstance(size_payload, dict) else None
    if not isinstance(image_size, dict):
        return ""
    width = image_size.get("width")
    height = image_size.get("height")
    if not isinstance(width, int) or not isinstance(height, int):
        return ""
    return f"{width}x{height}"


def build_report(result: dict[str, Any]) -> str:
    rows_final = []
    rows_screenshot = []
    rows_block = []
    rows_vlm_groups = []
    rows_vlm_dims = []
    rows_html = []
    rows_bbox = []
    rows_diag = []
    rows_websee = []
    rows_missing = []
    seen_bbox_rows: set[tuple[str, str]] = set()
    seen_diag_rows: set[tuple[str, str]] = set()

    for candidate_name, candidate in result["candidates"].items():
        summary = candidate["summary"]
        groups = summary["component_groups"]
        rows_final.append(
            [
                candidate_name,
                summary["matched_capture_count"],
                summary["reference_enabled_capture_count"],
                summary["coverage"],
                groups["screenshot"]["score"],
                groups["html"]["score"],
                groups["block"]["score"],
                groups["vlm"]["score"],
                summary["experimental_final_score"],
            ]
        )

        for capture_id, pair in candidate["pairs"].items():
            screenshot = pair.get("screenshot_pair", {})
            size_match = screenshot.get("size_match", {})
            dreamsim = pair.get("dreamsim", {})
            presentation = pair.get("presentation_diff", {})
            rows_screenshot.append(
                [
                    candidate_name,
                    capture_id,
                    screenshot_size_label(size_match, "reference"),
                    screenshot_size_label(size_match, "candidate"),
                    size_match.get("score"),
                    size_match.get("height_ratio"),
                    get_in(screenshot, ["pixelmatch", "score"]),
                    screenshot.get("ssim"),
                    screenshot.get("clip"),
                    dreamsim.get("distance"),
                    score_from_dreamsim(dreamsim.get("distance")),
                    screenshot.get("mse"),
                    screenshot.get("mae"),
                    get_in(screenshot, ["candidate_render_sanity", "score"]),
                    presentation.get("diff_ratio"),
                    presentation.get("cluster_count"),
                ]
            )

            vb = pair.get("visual_block", {})
            ebp = pair.get("element_block_pixelmatch", {})
            bbox = pair.get("bbox_geometry", {})
            cssom = pair.get("cssom_block_style", {})
            rows_block.append(
                [
                    candidate_name,
                    capture_id,
                    vb.get("score"),
                    vb.get("size"),
                    vb.get("text"),
                    vb.get("position"),
                    vb.get("text_color"),
                    vb.get("masked_clip"),
                    vb.get("matched_pair_count"),
                    ebp.get("score"),
                    ebp.get("matched_pixelmatch"),
                    ebp.get("coverage_score"),
                    bbox.get("score"),
                    bbox.get("matched_iou"),
                    bbox.get("matched_area_similarity"),
                    bbox.get("matched_center_similarity"),
                    cssom.get("score"),
                    cssom.get("matched_cssom_score"),
                    cssom.get("dom_resolution_score"),
                    cssom.get("coverage_score"),
                ]
            )

            vlm = pair.get("vlm_judge", {})
            rows_vlm_groups.append(
                [
                    candidate_name,
                    capture_id,
                    vlm.get("overall"),
                    vlm.get("overall_0_to_10"),
                    get_in(vlm, ["groups", "visual_structure_and_alignment"]),
                    get_in(vlm, ["groups", "color_and_aesthetic_design"]),
                    get_in(vlm, ["groups", "textual_and_content_consistency"]),
                    get_in(vlm, ["groups", "user_interface_and_interactivity"]),
                ]
            )
            dimensions = vlm.get("dimensions", {})
            rows_vlm_dims.append(
                [
                    candidate_name,
                    capture_id,
                    dimensions.get("layout_consistency"),
                    dimensions.get("element_alignment"),
                    dimensions.get("proportional_accuracy"),
                    dimensions.get("visual_harmony"),
                    dimensions.get("color_scheme_aesthetic_match"),
                    dimensions.get("aesthetic_resemblance"),
                    dimensions.get("font_characteristics_consistency"),
                    dimensions.get("textual_content_match"),
                    dimensions.get("numeric_special_character_accuracy"),
                    dimensions.get("user_interface_consistency"),
                ]
            )

        for page, page_metrics in candidate["html_pages"].items():
            text = page_metrics.get("webcode2m_text", {})
            dom = page_metrics.get("webcode2m_dom", {})
            rows_html.append(
                [
                    candidate_name,
                    page,
                    text.get("bleu_1"),
                    text.get("rouge_1_recall"),
                    text.get("reference_tokens"),
                    text.get("candidate_tokens"),
                    dom.get("tree_bleu"),
                    dom.get("tree_rouge_1"),
                    dom.get("f1"),
                    dom.get("matched_unique_subtrees"),
                    dom.get("reference_unique_subtrees"),
                    dom.get("candidate_unique_subtrees"),
                ]
            )

        for site_name, site_payload in [
            ("reference", candidate["reference_bbox_pages"]),
            (candidate_name, candidate["candidate_bbox_pages"]),
        ]:
            for page, bbox in site_payload.items():
                row_key = (site_name, page)
                if row_key in seen_bbox_rows:
                    continue
                seen_bbox_rows.add(row_key)
                rows_bbox.append(
                    [
                        site_name,
                        page,
                        bbox.get("node_count"),
                        bbox.get("leaf_count"),
                        bbox.get("max_depth"),
                        bbox.get("bbox_html_bytes"),
                        bbox.get("style_list_count"),
                        bbox.get("tree_path"),
                    ]
                )

        for site_name, site_payload in [
            ("reference", candidate["reference_diagnostics"]),
            (candidate_name, candidate["candidate_diagnostics"]),
        ]:
            for page, diag in site_payload.items():
                row_key = (site_name, page)
                if row_key in seen_diag_rows:
                    continue
                seen_diag_rows.add(row_key)
                wb = diag.get("webcoderbench_tags", {})
                vq = diag.get("webcoderbench_visual_quality", {})
                metrics = vq.get("metrics", {})
                rows_diag.append(
                    [
                        site_name,
                        page,
                        wb.get("tags"),
                        get_in(wb, ["accessibility_control", "issue_count"]),
                        get_in(wb, ["mobile_overflow", "horizontal_overflow_px"]),
                        get_in(metrics, ["component_style_consistency", "score"]),
                        get_in(metrics, ["icon_style_consistency", "score"]),
                        get_in(metrics, ["layout_consistency", "score"]),
                        get_in(metrics, ["layout_sparsity", "score"]),
                        vq.get("tags"),
                    ]
                )

        for missing in candidate["coverage"]["missing"]:
            rows_missing.append(
                [
                    candidate_name,
                    missing["capture_id"],
                    missing.get("page"),
                    missing.get("state"),
                    missing.get("reason"),
                ]
            )

    for item in result.get("websee_dom_localization", []):
        rows_websee.append(
            [
                item.get("candidate"),
                item.get("capture"),
                item.get("diff_ratio"),
                item.get("large_clusters"),
                item.get("localized_clusters"),
                item.get("top_localized_regions"),
                item.get("signal"),
            ]
        )

    generated_at = result["metadata"]["generated_at"]
    lines = [
        "# Full Metrics Rerun",
        "",
        f"Generated at: `{generated_at}`",
        "",
        "This report exposes sub-scores and the experimental aggregate. The aggregate is only a diagnostic comparator; the raw JSON is the source of truth.",
        "",
        "## Experimental Final Scores",
        "",
        md_table(
            [
                "Candidate",
                "Matched",
                "Expected",
                "Coverage",
                "Screenshot",
                "HTML",
                "Block/CSSOM",
                "VLM",
                "Final",
            ],
            rows_final,
        ),
        "## Screenshot-Level Metrics",
        "",
        md_table(
            [
                "Candidate",
                "Capture",
                "Ref Size",
                "Cand Size",
                "Size Match",
                "Height Ratio",
                "Pixelmatch",
                "SSIM",
                "CLIP",
                "DreamSim Dist",
                "DreamSim Score",
                "MSE",
                "MAE",
                "Render",
                "Diff Ratio",
                "Diff Clusters",
            ],
            rows_screenshot,
        ),
        "## Visual Block, Element Pixelmatch, BBox, CSSOM",
        "",
        md_table(
            [
                "Candidate",
                "Capture",
                "VB Score",
                "Size",
                "Text",
                "Position",
                "Text Color",
                "Masked CLIP",
                "Pairs",
                "Block PM",
                "Matched PM",
                "PM Coverage",
                "BBox Score",
                "BBox IoU",
                "BBox Area",
                "BBox Center",
                "CSSOM Score",
                "CSSOM Matched",
                "DOM Res",
                "CSSOM Coverage",
            ],
            rows_block,
        ),
        "## Web2Code-Style VLM Groups",
        "",
        md_table(
            [
                "Candidate",
                "Capture",
                "Overall",
                "Overall 0-10",
                "Visual Struct",
                "Color/Aesthetic",
                "Text/Content",
                "UI",
            ],
            rows_vlm_groups,
        ),
        "## Web2Code-Style VLM Dimensions",
        "",
        md_table(
            [
                "Candidate",
                "Capture",
                "Layout",
                "Alignment",
                "Proportion",
                "Harmony",
                "Color",
                "Aesthetic",
                "Font",
                "Text",
                "Numeric",
                "UI",
            ],
            rows_vlm_dims,
        ),
        "## HTML Metrics",
        "",
        md_table(
            [
                "Candidate",
                "Page",
                "Text BLEU-1",
                "Text ROUGE-1",
                "Ref Tokens",
                "Cand Tokens",
                "DOM BLEU",
                "DOM ROUGE",
                "DOM F1",
                "Matched Unique",
                "Ref Unique",
                "Cand Unique",
            ],
            rows_html,
        ),
        "## WebCode2M BBox Tree Outputs",
        "",
        md_table(
            [
                "Site",
                "Page",
                "Nodes",
                "Leaves",
                "Max Depth",
                "BBox HTML Bytes",
                "Style Rows",
                "Tree JSON",
            ],
            rows_bbox,
        ),
        "## WebCoderBench-Style Diagnostics",
        "",
        md_table(
            [
                "Site",
                "Page",
                "Tags",
                "A11y Issues",
                "Mobile Overflow",
                "Component",
                "Icon",
                "Layout",
                "Sparsity",
                "Visual Quality Tags",
            ],
            rows_diag,
        ),
    ]
    if rows_websee:
        lines.extend(
            [
                "## WebSee-Style DOM Localization",
                "",
                result.get(
                    "websee_dom_localization_note",
                    "Local fallback maps visual-diff clusters to candidate DOM/CSSOM regions.",
                ),
                "",
                md_table(
                    [
                        "Candidate",
                        "Capture",
                        "Diff Ratio",
                        "Large Clusters",
                        "Localized Clusters",
                        "Top Localized Regions",
                        "Signal",
                    ],
                    rows_websee,
                ),
            ]
        )
    lines.extend(
        [
        "## Missing Captures",
        "",
        md_table(["Candidate", "Capture", "Page", "State", "Reason"], rows_missing),
        "## Runtime Notes",
        "",
        md_table(
            ["Key", "Value"],
            [
                ["VLM model", result["metadata"].get("vlm_model")],
                ["VLM enabled", result["metadata"].get("vlm_enabled")],
                ["DreamSim type", result["metadata"].get("dreamsim_type")],
                ["DreamSim device", result["metadata"].get("dreamsim_device")],
                ["Visual block device", result["metadata"].get("visual_block_device")],
                ["CLIP model", "open_clip ViT-B-32-quickgelu/openai"],
            ],
        ),
        ]
    )
    return "\n".join(lines)


def page_map_from_captures(captures: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    pages: dict[str, dict[str, Any]] = {}
    for capture in captures:
        page = capture.get("page") or capture["id"]
        if page not in pages or capture["id"].endswith(".desktop.full"):
            pages[page] = capture
    return pages


def run_candidate(
    reference_manifest: dict[str, Any],
    reference_captures: list[dict[str, Any]],
    candidate_root: Path,
    output_dir: Path,
    args: argparse.Namespace,
) -> dict[str, Any]:
    candidate_manifest = read_json(candidate_root / "screenshot-manifest.json")
    reference_by_id = {capture["id"]: capture for capture in reference_captures}
    candidate_by_id = {capture["id"]: capture for capture in candidate_manifest["captures"]}
    candidate_name = candidate_root.name
    log(f"{candidate_name}: running pairwise screenshot and block metrics")

    pairs: dict[str, Any] = {}
    missing: list[dict[str, Any]] = []

    for capture_id, reference_capture in reference_by_id.items():
        reference_screenshot = screenshot_path_for_capture(REFERENCE_ROOT, reference_manifest, capture_id)
        candidate_capture = candidate_by_id.get(capture_id, reference_capture)
        candidate_screenshot = screenshot_path_for_capture(candidate_root, candidate_manifest, capture_id)
        if not reference_screenshot.exists() or not candidate_screenshot.exists():
            missing.append(
                {
                    "capture_id": capture_id,
                    "page": reference_capture.get("page"),
                    "state": reference_capture.get("state"),
                    "reason": "missing reference or candidate screenshot",
                    "reference_screenshot": str(reference_screenshot),
                    "candidate_screenshot": str(candidate_screenshot),
                    "candidate_capture_enabled": enabled_capture(candidate_capture),
                    "unsupported_reason": candidate_capture.get("unsupportedReason"),
                }
            )
            continue

        reference_html = html_path_for_capture(REFERENCE_ROOT, reference_capture)
        candidate_html = html_path_for_capture(candidate_root, candidate_capture)
        viewport = capture_viewport(reference_capture, reference_manifest)
        pair: dict[str, Any] = {
            "capture": reference_capture,
            "candidate_capture": candidate_capture,
            "reference_html": str(reference_html),
            "candidate_html": str(candidate_html),
            "reference_screenshot": str(reference_screenshot),
            "candidate_screenshot": str(candidate_screenshot),
        }

        pair["screenshot_pair"] = metric_call(
            "screenshot_pair",
            lambda: score_screenshot_pair(reference_screenshot, candidate_screenshot, include_clip=True),
        )
        pair["dreamsim"] = metric_call(
            "dreamsim",
            lambda: run_dreamsim_pair(
                reference_screenshot,
                candidate_screenshot,
                device=args.dreamsim_device,
                dreamsim_type=args.dreamsim_type,
                cache_dir=args.dreamsim_cache_dir,
            ),
        )
        pair["presentation_diff"] = metric_call(
            "presentation_diff",
            lambda: presentation_diff_tags(reference_screenshot, candidate_screenshot, include_clusters=False),
        )

        pair["visual_block"] = metric_call(
            "visual_block",
            lambda: visual_block_score(
                reference_html,
                candidate_html,
                reference_screenshot,
                candidate_screenshot,
                device=args.visual_block_device,
                include_pairs=True,
                include_block_pixelmatch=True,
            ),
        )
        if not is_error(pair["visual_block"]):
            pair["element_block_pixelmatch"] = pair["visual_block"].get("block_pixelmatch", {})
            pair["bbox_geometry"] = metric_call(
                "bbox_geometry",
                lambda: {
                    **_score_bbox_geometry(
                        pair["visual_block"]["matched_pairs"],
                        coverage_score=float(pair["visual_block"]["size"]),
                    ),
                    "visual_block": {
                        key: pair["visual_block"][key]
                        for key in (
                            "score",
                            "size",
                            "text",
                            "position",
                            "text_color",
                            "masked_clip",
                            "reference_block_count",
                            "candidate_block_count",
                            "matched_pair_count",
                            "unmatched_reference_count",
                            "unmatched_candidate_count",
                        )
                    },
                    "matched_pairs": pair["visual_block"]["matched_pairs"],
                    "unmatched_reference_blocks": pair["visual_block"].get("unmatched_reference_blocks", []),
                    "unmatched_candidate_blocks": pair["visual_block"].get("unmatched_candidate_blocks", []),
                },
            )
        else:
            pair["element_block_pixelmatch"] = pair["visual_block"]
            pair["bbox_geometry"] = pair["visual_block"]
        pair["cssom_block_style"] = metric_call(
            "cssom_block_style",
            lambda: cssom_block_style_score(
                reference_html,
                candidate_html,
                reference_screenshot,
                candidate_screenshot,
                device=args.visual_block_device,
                viewport=viewport,
                visual_block_result=pair["visual_block"] if not is_error(pair["visual_block"]) else None,
            ),
        )
        pairs[capture_id] = pair

    log(f"{candidate_name}: running HTML, bbox-tree, and unary diagnostics")
    reference_pages = page_map_from_captures(reference_captures)
    candidate_pages = {
        page: candidate_by_id.get(capture["id"], capture)
        for page, capture in reference_pages.items()
    }
    html_pages: dict[str, Any] = {}
    reference_bbox_pages: dict[str, Any] = {}
    candidate_bbox_pages: dict[str, Any] = {}
    reference_diagnostics: dict[str, Any] = {}
    candidate_diagnostics: dict[str, Any] = {}

    for page, reference_capture in reference_pages.items():
        candidate_capture = candidate_pages[page]
        reference_html = html_path_for_capture(REFERENCE_ROOT, reference_capture)
        candidate_html = html_path_for_capture(candidate_root, candidate_capture)
        reference_full_screenshot = screenshot_path_for_capture(REFERENCE_ROOT, reference_manifest, reference_capture["id"])
        candidate_full_screenshot = screenshot_path_for_capture(candidate_root, candidate_manifest, candidate_capture["id"])
        viewport = capture_viewport(reference_capture, reference_manifest)

        html_pages[page] = {
            "reference_html": str(reference_html),
            "candidate_html": str(candidate_html),
            "webcode2m_text": metric_call("webcode2m_text", lambda: webcode2m_text_score(reference_html, candidate_html)),
            "webcode2m_dom": metric_call("webcode2m_dom", lambda: webcode2m_dom_score(reference_html, candidate_html)),
        }
        reference_bbox_pages[page] = write_bbox_outputs(output_dir, "reference", page, reference_html, viewport)
        candidate_bbox_pages[page] = write_bbox_outputs(output_dir, candidate_name, page, candidate_html, viewport)

        reference_diagnostics[page] = {
            "webcoderbench_tags": metric_call("webcoderbench_tags", lambda: webcoderbench_tags(reference_html)),
            "webcoderbench_visual_quality": metric_call(
                "webcoderbench_visual_quality",
                lambda: webcoderbench_visual_quality_scores(reference_html, reference_full_screenshot),
            ),
        }
        candidate_diagnostics[page] = {
            "webcoderbench_tags": metric_call("webcoderbench_tags", lambda: webcoderbench_tags(candidate_html)),
            "webcoderbench_visual_quality": metric_call(
                "webcoderbench_visual_quality",
                lambda: webcoderbench_visual_quality_scores(candidate_html, candidate_full_screenshot),
            )
            if candidate_full_screenshot.exists()
            else {"error": {"metric": "webcoderbench_visual_quality", "message": "missing screenshot"}},
        }

    candidate_result = {
        "root": str(candidate_root),
        "manifest": str(candidate_root / "screenshot-manifest.json"),
        "coverage": {
            "reference_enabled_capture_count": len(reference_captures),
            "matched_capture_count": len(pairs),
            "missing_capture_count": len(missing),
            "missing": missing,
        },
        "pairs": pairs,
        "html_pages": html_pages,
        "reference_bbox_pages": reference_bbox_pages,
        "candidate_bbox_pages": candidate_bbox_pages,
        "reference_diagnostics": reference_diagnostics,
        "candidate_diagnostics": candidate_diagnostics,
    }
    return candidate_result


def run_vlm(result: dict[str, Any], args: argparse.Namespace) -> None:
    if args.skip_vlm:
        log("VLM judge skipped by flag")
        for candidate in result["candidates"].values():
            for pair in candidate["pairs"].values():
                pair["vlm_judge"] = {"skipped": True, "reason": "--skip-vlm"}
        return

    if not os.environ.get("OPENAI_API_KEY"):
        log("VLM judge skipped because OPENAI_API_KEY is unavailable")
        for candidate in result["candidates"].values():
            for pair in candidate["pairs"].values():
                pair["vlm_judge"] = {"skipped": True, "reason": "OPENAI_API_KEY unavailable"}
        return

    jobs = []
    for candidate_name, candidate in result["candidates"].items():
        for capture_id, pair in candidate["pairs"].items():
            jobs.append((candidate_name, capture_id, pair["reference_screenshot"], pair["candidate_screenshot"]))

    log(f"running VLM judge on {len(jobs)} screenshot pairs with {args.vlm_model}")
    with ThreadPoolExecutor(max_workers=args.vlm_workers) as executor:
        future_map = {
            executor.submit(
                metric_call,
                "vlm_judge",
                lambda ref=reference_screenshot, cand=candidate_screenshot: vlm_judge_score(
                    ref,
                    cand,
                    model=args.vlm_model,
                ),
            ): (candidate_name, capture_id)
            for candidate_name, capture_id, reference_screenshot, candidate_screenshot in jobs
        }
        for future in as_completed(future_map):
            candidate_name, capture_id = future_map[future]
            result["candidates"][candidate_name]["pairs"][capture_id]["vlm_judge"] = future.result()
            log(f"VLM complete: {candidate_name} / {capture_id}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run all local website-design evaluation metrics.")
    parser.add_argument("--output-dir", default=None, help="Directory for report/raw outputs")
    parser.add_argument("--candidate", action="append", default=None, help="Candidate root. May be repeated.")
    parser.add_argument("--capture", action="append", default=None, help="Reference capture id to run. May be repeated.")
    parser.add_argument("--vlm-model", default="gpt-5.4-mini")
    parser.add_argument("--vlm-workers", type=int, default=3)
    parser.add_argument("--skip-vlm", action="store_true")
    parser.add_argument("--dreamsim-type", default="ensemble")
    parser.add_argument("--dreamsim-device", default=None)
    parser.add_argument("--dreamsim-cache-dir", default=str(REPO_ROOT / ".cache" / "dreamsim"))
    parser.add_argument("--visual-block-device", default="cpu")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv(REPO_ROOT / ".env")

    started = time.time()
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    output_dir = Path(args.output_dir).resolve() if args.output_dir else REPO_ROOT / "metrics-results" / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)

    reference_manifest = read_json(REFERENCE_MANIFEST)
    capture_filter = set(args.capture or [])
    reference_captures = [
        capture
        for capture in reference_manifest["captures"]
        if enabled_capture(capture) and (not capture_filter or capture["id"] in capture_filter)
    ]
    candidate_roots = [Path(path).resolve() for path in args.candidate] if args.candidate else DEFAULT_CANDIDATES

    result: dict[str, Any] = {
        "metadata": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "repo_root": str(REPO_ROOT),
            "reference_root": str(REFERENCE_ROOT),
            "reference_manifest": str(REFERENCE_MANIFEST),
            "vlm_model": args.vlm_model,
            "vlm_enabled": not args.skip_vlm and bool(os.environ.get("OPENAI_API_KEY")),
            "vlm_workers": args.vlm_workers,
            "dreamsim_type": args.dreamsim_type,
            "dreamsim_device": _pick_torch_device(args.dreamsim_device),
            "visual_block_device": args.visual_block_device,
            "output_dir": str(output_dir),
        },
        "candidates": {},
    }

    for candidate_root in candidate_roots:
        candidate = run_candidate(reference_manifest, reference_captures, candidate_root, output_dir, args)
        result["candidates"][candidate_root.name] = candidate

    run_vlm(result, args)

    for candidate in result["candidates"].values():
        candidate["summary"] = candidate_final_summary(candidate)

    result["metadata"]["elapsed_seconds"] = round(time.time() - started, 3)
    raw_path = output_dir / "full-metrics.json"
    report_path = output_dir / "report.md"
    raw_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    report_path.write_text(build_report(result), encoding="utf-8")

    log(f"wrote raw metrics: {raw_path}")
    log(f"wrote report: {report_path}")
    print(json.dumps({"raw": str(raw_path), "report": str(report_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
