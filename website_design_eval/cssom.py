from __future__ import annotations

import math
import os
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from PIL import Image

PathLike = str | os.PathLike[str]


STYLE_GROUPS: dict[str, list[str]] = {
    "typography": [
        "font-family",
        "font-size",
        "font-weight",
        "line-height",
        "letter-spacing",
        "text-align",
        "text-transform",
    ],
    "color": [
        "color",
        "background-color",
        "border-top-color",
        "border-right-color",
        "border-bottom-color",
        "border-left-color",
    ],
    "spacing": [
        "padding-top",
        "padding-right",
        "padding-bottom",
        "padding-left",
        "margin-top",
        "margin-right",
        "margin-bottom",
        "margin-left",
        "row-gap",
        "column-gap",
    ],
    "shape": [
        "border-top-width",
        "border-right-width",
        "border-bottom-width",
        "border-left-width",
        "border-top-left-radius",
        "border-top-right-radius",
        "border-bottom-right-radius",
        "border-bottom-left-radius",
        "border-top-style",
        "border-right-style",
        "border-bottom-style",
        "border-left-style",
    ],
    "effects": [
        "opacity",
        "box-shadow",
        "filter",
        "transform",
    ],
}

CONTROL_SELECTORS = ",".join(
    [
        "a[href]",
        "button",
        "input",
        "select",
        "textarea",
        "summary",
        "[role]",
        "[tabindex]",
    ]
)


def _round(value: Any, digits: int = 6) -> float:
    return round(float(value), digits)


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def _bbox_area(bbox: list[float]) -> float:
    return max(float(bbox[2]), 0.0) * max(float(bbox[3]), 0.0)


def _bbox_center(bbox: list[float]) -> tuple[float, float]:
    return float(bbox[0]) + float(bbox[2]) / 2, float(bbox[1]) + float(bbox[3]) / 2


def _bbox_iou(reference_bbox: list[float], candidate_bbox: list[float]) -> float:
    ref_left, ref_top, ref_width, ref_height = reference_bbox
    cand_left, cand_top, cand_width, cand_height = candidate_bbox
    ref_right = ref_left + ref_width
    ref_bottom = ref_top + ref_height
    cand_right = cand_left + cand_width
    cand_bottom = cand_top + cand_height

    intersection_width = max(0.0, min(ref_right, cand_right) - max(ref_left, cand_left))
    intersection_height = max(0.0, min(ref_bottom, cand_bottom) - max(ref_top, cand_top))
    intersection_area = intersection_width * intersection_height
    union_area = ref_width * ref_height + cand_width * cand_height - intersection_area
    if union_area <= 0:
        return 0.0
    return intersection_area / union_area


def _bbox_area_similarity(reference_bbox: list[float], candidate_bbox: list[float]) -> float:
    reference_area = _bbox_area(reference_bbox)
    candidate_area = _bbox_area(candidate_bbox)
    if reference_area <= 0 or candidate_area <= 0:
        return 0.0
    return min(reference_area, candidate_area) / max(reference_area, candidate_area)


def _bbox_center_similarity(reference_bbox: list[float], candidate_bbox: list[float]) -> float:
    reference_center = _bbox_center(reference_bbox)
    candidate_center = _bbox_center(candidate_bbox)
    return max(0.0, 1.0 - max(abs(reference_center[0] - candidate_center[0]), abs(reference_center[1] - candidate_center[1])))


def _bbox_similarity(reference_bbox: list[float], candidate_bbox: list[float]) -> dict[str, float]:
    iou = _bbox_iou(reference_bbox, candidate_bbox)
    area_similarity = _bbox_area_similarity(reference_bbox, candidate_bbox)
    center_similarity = _bbox_center_similarity(reference_bbox, candidate_bbox)
    return {
        "iou": _round(iou),
        "area_similarity": _round(area_similarity),
        "center_similarity": _round(center_similarity),
        "score": _round((iou + area_similarity + center_similarity) / 3),
    }


def _parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    if value.strip().lower() in {"normal", "auto", "none", "medium", "thin", "thick"}:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", value)
    if not match:
        return None
    return float(match.group(0))


def _numeric_similarity(reference: str | None, candidate: str | None, *, floor: float = 1.0) -> float | None:
    ref_value = _parse_float(reference)
    cand_value = _parse_float(candidate)
    if ref_value is None or cand_value is None:
        return None
    denominator = max(abs(ref_value), abs(cand_value), floor)
    return max(0.0, 1.0 - abs(ref_value - cand_value) / denominator)


def _parse_rgb(value: str | None) -> tuple[float, float, float, float] | None:
    if not value:
        return None
    match = re.search(r"rgba?\(\s*([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\s*\)", value)
    if not match:
        return None
    alpha = float(match.group(4)) if match.group(4) is not None else 1.0
    return float(match.group(1)), float(match.group(2)), float(match.group(3)), alpha


def _color_similarity(reference: str | None, candidate: str | None) -> float | None:
    ref_rgb = _parse_rgb(reference)
    cand_rgb = _parse_rgb(candidate)
    if ref_rgb is None or cand_rgb is None:
        return None
    rgb_distance = math.sqrt(sum((ref_rgb[index] - cand_rgb[index]) ** 2 for index in range(3)))
    alpha_distance = abs(ref_rgb[3] - cand_rgb[3])
    rgb_score = max(0.0, 1.0 - rgb_distance / math.sqrt(3 * 255 * 255))
    alpha_score = max(0.0, 1.0 - alpha_distance)
    return 0.9 * rgb_score + 0.1 * alpha_score


def _categorical_similarity(reference: str | None, candidate: str | None) -> float | None:
    if reference is None or candidate is None:
        return None
    ref_norm = reference.strip().lower()
    cand_norm = candidate.strip().lower()
    if not ref_norm and not cand_norm:
        return None
    if ref_norm == cand_norm:
        return 1.0
    return SequenceMatcher(None, ref_norm, cand_norm).ratio()


def _property_similarity(property_name: str, reference: str | None, candidate: str | None) -> float | None:
    if "color" in property_name:
        color_score = _color_similarity(reference, candidate)
        if color_score is not None:
            return color_score
    if property_name == "opacity":
        return _numeric_similarity(reference, candidate, floor=1.0)
    if property_name in {"font-family", "text-align", "text-transform"} or property_name.endswith("-style"):
        return _categorical_similarity(reference, candidate)
    numeric_score = _numeric_similarity(reference, candidate, floor=1.0)
    if numeric_score is not None:
        return numeric_score
    return _categorical_similarity(reference, candidate)


def _score_style_group(
    reference_style: dict[str, str],
    candidate_style: dict[str, str],
    properties: list[str],
) -> dict[str, Any]:
    property_scores = {}
    for property_name in properties:
        score = _property_similarity(
            property_name,
            reference_style.get(property_name),
            candidate_style.get(property_name),
        )
        if score is not None:
            property_scores[property_name] = _round(score)

    if not property_scores:
        return {"score": None, "property_scores": property_scores}

    return {
        "score": _round(sum(property_scores.values()) / len(property_scores)),
        "property_scores": property_scores,
    }


def _resolve_viewport(
    screenshot_path: PathLike | None,
    viewport: tuple[int, int] | None,
) -> tuple[dict[str, int], tuple[int, int] | None]:
    screenshot_size = None
    if screenshot_path is not None:
        with Image.open(screenshot_path) as image:
            screenshot_size = image.size

    if viewport is not None:
        return {"width": int(viewport[0]), "height": int(viewport[1])}, screenshot_size
    if screenshot_path is None:
        return {"width": 1440, "height": 900}, None

    if screenshot_size is None:
        return {"width": 1440, "height": 900}, None
    viewport_height = min(screenshot_size[1], 900)
    return {"width": screenshot_size[0], "height": viewport_height}, screenshot_size


def _html_url(html_path: PathLike) -> str:
    path = Path(html_path)
    if path.exists():
        return path.resolve().as_uri()
    raise FileNotFoundError(f"CSSOM snapshot requires an HTML file path: {html_path}")


def extract_cssom_snapshot(
    html_path: PathLike,
    *,
    screenshot_path: PathLike | None = None,
    viewport: tuple[int, int] | None = None,
    wait_until: str = "networkidle",
    after_load_wait_ms: int = 100,
) -> dict[str, Any]:
    """Extract rendered DOM boxes and computed styles with Playwright.

    This is a browser-rendered CSSOM snapshot, not a source-code parser. The
    output is intentionally broad enough to support multiple scorers.
    """

    from playwright.sync_api import sync_playwright

    viewport_size, screenshot_size = _resolve_viewport(screenshot_path, viewport)
    if screenshot_size is None:
        normalize_width = viewport_size["width"]
        normalize_height = viewport_size["height"]
    else:
        normalize_width, normalize_height = screenshot_size

    script = """
({ normalizeWidth, normalizeHeight, controlSelectors, styleGroups }) => {
  const styleProps = Array.from(new Set(Object.values(styleGroups).flat()));
  const controlMatches = (el) => {
    try {
      return el.matches(controlSelectors);
    } catch {
      return false;
    }
  };
  const cleanText = (value) => (value || '').replace(/\\s+/g, ' ').trim();
  const inferredRole = (el) => {
    const explicit = el.getAttribute('role');
    if (explicit) return explicit;
    const tag = el.tagName.toLowerCase();
    if (tag === 'a' && el.hasAttribute('href')) return 'link';
    if (tag === 'button') return 'button';
    if (tag === 'select') return 'combobox';
    if (tag === 'textarea') return 'textbox';
    if (tag === 'input') {
      const type = (el.getAttribute('type') || 'text').toLowerCase();
      if (type === 'checkbox') return 'checkbox';
      if (type === 'radio') return 'radio';
      if (type === 'range') return 'slider';
      if (type === 'submit' || type === 'button' || type === 'reset') return 'button';
      return 'textbox';
    }
    return '';
  };
  const accessibleName = (el) => {
    const aria = el.getAttribute('aria-label');
    if (aria) return cleanText(aria);
    const labelledBy = el.getAttribute('aria-labelledby');
    if (labelledBy) {
      const text = labelledBy
        .split(/\\s+/)
        .map((id) => document.getElementById(id)?.innerText || '')
        .join(' ');
      if (cleanText(text)) return cleanText(text);
    }
    if (el.id) {
      const label = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (label && cleanText(label.innerText)) return cleanText(label.innerText);
    }
    const closestLabel = el.closest('label');
    if (closestLabel && cleanText(closestLabel.innerText)) return cleanText(closestLabel.innerText);
    const alt = el.getAttribute('alt');
    if (alt) return cleanText(alt);
    const title = el.getAttribute('title');
    if (title) return cleanText(title);
    const value = el.getAttribute('value');
    if (value && ['input', 'button'].includes(el.tagName.toLowerCase())) return cleanText(value);
    return cleanText(el.innerText || el.textContent || '');
  };
  const elements = [];
  const controls = [];
  for (const [index, el] of Array.from(document.querySelectorAll('*')).entries()) {
    const cs = window.getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    const rect = el.getBoundingClientRect();
    const width = rect.width;
    const height = rect.height;
    if (width <= 0 || height <= 0) continue;
    const left = rect.left + window.scrollX;
    const top = rect.top + window.scrollY;
    const style = {};
    for (const prop of styleProps) {
      style[prop] = cs.getPropertyValue(prop);
    }
    const tag = el.tagName.toLowerCase();
    const role = inferredRole(el);
    const text = cleanText(el.innerText || el.textContent || '');
    const name = accessibleName(el);
    const isControl = controlMatches(el);
    const payload = {
      node_id: `node-${index}`,
      tag,
      role,
      type: tag === 'input' ? (el.getAttribute('type') || 'text').toLowerCase() : '',
      text,
      accessible_name: name,
      is_control: isControl,
      states: {
        disabled: Boolean(el.disabled || el.getAttribute('aria-disabled') === 'true'),
        checked: Boolean(el.checked || el.getAttribute('aria-checked') === 'true'),
        selected: Boolean(el.selected || el.getAttribute('aria-selected') === 'true'),
        expanded: el.getAttribute('aria-expanded') || '',
        focused: el === document.activeElement,
      },
      bbox_px: {
        x: left,
        y: top,
        width,
        height,
      },
      bbox: [
        left / normalizeWidth,
        top / normalizeHeight,
        width / normalizeWidth,
        height / normalizeHeight,
      ],
      style,
    };
    elements.push(payload);
    if (isControl) controls.push(payload);
  }
    return {
    url: window.location.href,
    viewport: {
      width: window.innerWidth,
      height: window.innerHeight,
      devicePixelRatio: window.devicePixelRatio,
    },
    document: {
      width: Math.max(document.documentElement.scrollWidth, document.body?.scrollWidth || 0, window.innerWidth),
      height: Math.max(document.documentElement.scrollHeight, document.body?.scrollHeight || 0, window.innerHeight),
    },
    normalize_size: {
      width: normalizeWidth,
      height: normalizeHeight,
    },
    screenshot: {
      width: normalizeWidth,
      height: normalizeHeight,
    },
    scroll: {
      x: window.scrollX,
      y: window.scrollY,
    },
    coordinate_space: {
      bbox_px: 'document_px',
      bbox: 'normalized_document_to_screenshot',
      note: 'bbox_px is document-space pixels; bbox is normalized by screenshot width/height for full-page visual-block matching.',
    },
    elements,
    controls,
  };
}
"""

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport=viewport_size, device_scale_factor=1)
        try:
            page.goto(_html_url(html_path), wait_until=wait_until)
            if after_load_wait_ms:
                page.wait_for_timeout(after_load_wait_ms)
            snapshot = page.evaluate(
                script,
                {
                    "normalizeWidth": normalize_width,
                    "normalizeHeight": normalize_height,
                    "controlSelectors": CONTROL_SELECTORS,
                    "styleGroups": STYLE_GROUPS,
                },
            )
        finally:
            browser.close()

    snapshot["source"] = str(html_path)
    snapshot["element_count"] = len(snapshot["elements"])
    snapshot["control_count"] = len(snapshot["controls"])
    return snapshot


def _block_resolution_score(block: dict[str, Any], element: dict[str, Any]) -> dict[str, float]:
    block_text = _normalize_text(block.get("text"))
    element_text = _normalize_text(element.get("text")) or _normalize_text(element.get("accessible_name"))
    text_similarity = SequenceMatcher(None, block_text, element_text).ratio() if block_text and element_text else 0.0
    bbox = _bbox_similarity(block["bbox"], element["bbox"])
    # WebCode2M's OCR-free block detector renders temporary HTML with
    # `set_content`, so its bboxes are useful for visual-block scoring but not
    # always reliable provenance for the styled page. Text and DOM order carry
    # the within-page block-to-node resolution here.
    score = 0.75 * text_similarity + 0.10 * bbox["center_similarity"] + 0.10 * bbox["area_similarity"] + 0.05 * bbox["iou"]
    return {
        "score": _round(score),
        "text": _round(text_similarity),
        "center": bbox["center_similarity"],
        "area": bbox["area_similarity"],
        "iou": bbox["iou"],
    }


def _node_index(node: dict[str, Any]) -> int:
    return int(str(node["node_id"]).replace("node-", ""))


def _resolve_block_items_to_elements(
    block_items: list[tuple[int, dict[str, Any]]],
    elements: list[dict[str, Any]],
    *,
    min_score: float,
) -> dict[int, tuple[dict[str, Any] | None, dict[str, float] | None]]:
    text_elements = [
        element
        for element in elements
        if element.get("text") or element.get("accessible_name")
    ]
    used_nodes: set[str] = set()
    cursor = 0
    resolved: dict[int, tuple[dict[str, Any] | None, dict[str, float] | None]] = {}

    for key, block in block_items:
        ordered_candidates = [
            element
            for element in text_elements
            if element["node_id"] not in used_nodes and _node_index(element) >= cursor
        ]
        fallback_candidates = [
            element
            for element in text_elements
            if element["node_id"] not in used_nodes
        ]

        best_element = None
        best_score = None
        for candidate_pool in (ordered_candidates, fallback_candidates):
            for element in candidate_pool:
                score = _block_resolution_score(block, element)
                if best_score is None or score["score"] > best_score["score"]:
                    best_element = element
                    best_score = score
            if best_element is not None and best_score is not None and best_score["score"] >= min_score:
                break

        if best_element is None or best_score is None or best_score["score"] < min_score:
            resolved[key] = (None, best_score)
            continue

        resolved[key] = (best_element, best_score)
        used_nodes.add(best_element["node_id"])
        cursor = _node_index(best_element) + 1

    return resolved


def _node_summary(node: dict[str, Any] | None) -> dict[str, Any] | None:
    if node is None:
        return None
    return {
        "node_id": node["node_id"],
        "tag": node["tag"],
        "role": node["role"],
        "type": node["type"],
        "text": node["text"],
        "accessible_name": node["accessible_name"],
        "bbox": [_round(value) for value in node["bbox"]],
        "bbox_px": {key: _round(value) for key, value in node["bbox_px"].items()},
        "states": node["states"],
    }


def _score_cssom_pair(reference_node: dict[str, Any], candidate_node: dict[str, Any]) -> dict[str, Any]:
    group_scores = {
        group: _score_style_group(reference_node["style"], candidate_node["style"], properties)
        for group, properties in STYLE_GROUPS.items()
    }
    layout = _bbox_similarity(reference_node["bbox"], candidate_node["bbox"])
    group_scores["layout"] = {"score": layout["score"], "property_scores": layout}

    available_scores = [
        payload["score"]
        for payload in group_scores.values()
        if payload["score"] is not None
    ]
    score = sum(available_scores) / len(available_scores) if available_scores else 0.0

    return {
        "score": _round(score),
        "groups": group_scores,
    }


def _snapshot_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "element_count": snapshot.get("element_count"),
        "control_count": snapshot.get("control_count"),
        "document": snapshot.get("document"),
        "viewport": snapshot.get("viewport"),
        "screenshot": snapshot.get("screenshot"),
        "normalize_size": snapshot.get("normalize_size"),
        "scroll": snapshot.get("scroll"),
        "coordinate_space": snapshot.get("coordinate_space"),
    }


def cssom_block_style_score_from_snapshots(
    reference_snapshot: dict[str, Any],
    candidate_snapshot: dict[str, Any],
    visual_block_result: dict[str, Any],
    *,
    include_pairs: bool = False,
    min_resolution_score: float = 0.35,
) -> dict[str, Any]:
    """Score computed CSS styles from manifest-state CSSOM snapshots.

    This function expects snapshots already extracted from the same browser
    state as the screenshot. It does not open or render raw HTML files.
    """

    visual_block = visual_block_result
    if "matched_pairs" not in visual_block:
        raise ValueError("visual_block_result must include matched_pairs")

    weighted_score = 0.0
    weighted_resolved_area = 0.0
    matched_area = 0.0
    resolved_pairs = []
    unresolved_pairs = []
    group_weighted_scores = {group: 0.0 for group in [*STYLE_GROUPS.keys(), "layout"]}
    group_weighted_areas = {group: 0.0 for group in [*STYLE_GROUPS.keys(), "layout"]}

    reference_resolutions = _resolve_block_items_to_elements(
        [
            (index, pair["reference"])
            for index, pair in sorted(
                enumerate(visual_block["matched_pairs"]),
                key=lambda item: item[1]["reference_index"],
            )
        ],
        reference_snapshot["elements"],
        min_score=min_resolution_score,
    )
    candidate_resolutions = _resolve_block_items_to_elements(
        [
            (index, pair["candidate"])
            for index, pair in sorted(
                enumerate(visual_block["matched_pairs"]),
                key=lambda item: item[1]["candidate_index"],
            )
        ],
        candidate_snapshot["elements"],
        min_score=min_resolution_score,
    )

    for index, pair in enumerate(visual_block["matched_pairs"]):
        weight = max(float(pair["reference"]["area"]), 0.0)
        matched_area += weight
        reference_node, reference_resolution = reference_resolutions[index]
        candidate_node, candidate_resolution = candidate_resolutions[index]

        if reference_node is None or candidate_node is None:
            unresolved_pairs.append(
                {
                    "reference_index": pair["reference_index"],
                    "candidate_index": pair["candidate_index"],
                    "reference_resolution": reference_resolution,
                    "candidate_resolution": candidate_resolution,
                    "reference": pair["reference"],
                    "candidate": pair["candidate"],
                }
            )
            continue

        cssom_pair = _score_cssom_pair(reference_node, candidate_node)
        weighted_score += float(cssom_pair["score"]) * weight
        weighted_resolved_area += weight

        for group, payload in cssom_pair["groups"].items():
            if payload["score"] is None:
                continue
            group_weighted_scores[group] += float(payload["score"]) * weight
            group_weighted_areas[group] += weight

        resolved_pairs.append(
            {
                "reference_index": pair["reference_index"],
                "candidate_index": pair["candidate_index"],
                "score": cssom_pair["score"],
                "groups": cssom_pair["groups"],
                "reference_resolution": reference_resolution,
                "candidate_resolution": candidate_resolution,
                "reference_node": _node_summary(reference_node),
                "candidate_node": _node_summary(candidate_node),
                "reference": pair["reference"],
                "candidate": pair["candidate"],
            }
        )

    matched_cssom_score = weighted_score / weighted_resolved_area if weighted_resolved_area > 0 else 0.0
    resolution_score = weighted_resolved_area / matched_area if matched_area > 0 else 0.0
    coverage_score = float(visual_block["size"])
    coverage_adjusted_score = matched_cssom_score * resolution_score * coverage_score
    if (
        _round(matched_cssom_score) == 1.0
        and _round(coverage_score) == 1.0
        and _round(float(visual_block.get("score", 0.0))) == 1.0
    ):
        coverage_adjusted_score = 1.0
    group_scores = {
        group: _round(group_weighted_scores[group] / group_weighted_areas[group])
        if group_weighted_areas[group] > 0
        else 0.0
        for group in group_weighted_scores
    }

    payload = {
        "score": _round(coverage_adjusted_score),
        "coverage_adjusted_score": _round(coverage_adjusted_score),
        "matched_cssom_score": _round(matched_cssom_score),
        "dom_resolution_score": _round(resolution_score),
        "visual_block_coverage_score": _round(coverage_score),
        "resolution_score": _round(resolution_score),
        "coverage_score": _round(coverage_score),
        "pair_count": len(visual_block["matched_pairs"]),
        "resolved_pair_count": len(resolved_pairs),
        "unresolved_pair_count": len(unresolved_pairs),
        "weighted_reference_area": _round(weighted_resolved_area),
        "group_scores": group_scores,
        "reference_snapshot": _snapshot_summary(reference_snapshot),
        "candidate_snapshot": _snapshot_summary(candidate_snapshot),
        "visual_block": {
            key: visual_block[key]
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
    }
    if include_pairs:
        payload["resolved_pairs"] = resolved_pairs
        payload["unresolved_pairs"] = unresolved_pairs
    return payload


def cssom_block_style_score(
    reference_html: PathLike,
    candidate_html: PathLike,
    reference_screenshot: PathLike,
    candidate_screenshot: PathLike,
    *,
    tmp_dir: PathLike | None = None,
    device: str = "cpu",
    debug: bool = False,
    include_pairs: bool = False,
    viewport: tuple[int, int] | None = None,
    min_resolution_score: float = 0.35,
    visual_block_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Legacy adapter that extracts CSSOM snapshots from HTML file paths.

    Core evaluator paths should prefer cssom_block_style_score_from_snapshots()
    so CSSOM scoring uses the already-captured manifest-state browser artifacts.
    This wrapper is kept for CLI/research parity.
    """

    from .block_visual import visual_block_score

    if visual_block_result is None:
        visual_block = visual_block_score(
            reference_html,
            candidate_html,
            reference_screenshot,
            candidate_screenshot,
            tmp_dir=tmp_dir,
            device=device,
            debug=debug,
            include_pairs=True,
        )
    else:
        visual_block = visual_block_result
        if "matched_pairs" not in visual_block:
            raise ValueError("visual_block_result must include matched_pairs")

    reference_snapshot = extract_cssom_snapshot(
        reference_html,
        screenshot_path=reference_screenshot,
        viewport=viewport,
    )
    candidate_snapshot = extract_cssom_snapshot(
        candidate_html,
        screenshot_path=candidate_screenshot,
        viewport=viewport,
    )
    return cssom_block_style_score_from_snapshots(
        reference_snapshot,
        candidate_snapshot,
        visual_block,
        include_pairs=include_pairs,
        min_resolution_score=min_resolution_score,
    )
