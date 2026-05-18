from __future__ import annotations

import math
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

from .cssom import extract_cssom_snapshot

PathLike = str | os.PathLike[str]

DEFAULT_DESKTOP_VIEWPORT = (1440, 900)
DEFAULT_MOBILE_VIEWPORT = (390, 844)
DEFAULT_CARD_KEYWORDS = ("card",)

FORM_CONTROL_TAGS = {"input", "select", "textarea"}
BUTTON_TYPES = {"button", "submit", "reset", "image"}
IGNORED_INPUT_TYPES = {"hidden"}
NAMED_CONTROL_ROLES = {
    "button",
    "checkbox",
    "combobox",
    "link",
    "listbox",
    "menuitem",
    "menuitemcheckbox",
    "menuitemradio",
    "option",
    "radio",
    "searchbox",
    "slider",
    "spinbutton",
    "switch",
    "tab",
    "textbox",
}


def _round(value: Any, digits: int = 6) -> float:
    return round(float(value), digits)


def _html_url(html_path: PathLike) -> str:
    path = Path(html_path)
    if path.exists():
        return path.resolve().as_uri()
    raise FileNotFoundError(f"Expected an HTML file path: {html_path}")


def _run_page_script(
    html_path: PathLike,
    script: str,
    arg: dict[str, Any],
    *,
    viewport: tuple[int, int],
    wait_until: str = "networkidle",
    after_load_wait_ms: int = 100,
) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": viewport[0], "height": viewport[1]}, device_scale_factor=1)
        try:
            page.goto(_html_url(html_path), wait_until=wait_until)
            if after_load_wait_ms:
                page.wait_for_timeout(after_load_wait_ms)
            return page.evaluate(script, arg)
        finally:
            browser.close()


def mobile_overflow_tags(
    html_path: PathLike,
    *,
    viewport: tuple[int, int] = DEFAULT_MOBILE_VIEWPORT,
    threshold_px: int = 0,
    include_elements: bool = False,
) -> dict[str, Any]:
    """Return WebCoderBench-style mobile overflow diagnostics as tags."""

    script = """
({ thresholdPx }) => {
  const cleanText = (value) => (value || '').replace(/\\s+/g, ' ').trim().slice(0, 120);
  const root = document.documentElement;
  const body = document.body;
  const viewportWidth = root.clientWidth;
  const scrollWidth = Math.max(root.scrollWidth, body ? body.scrollWidth : 0, window.innerWidth);
  const overflowPx = Math.max(0, scrollWidth - viewportWidth);
  const offenders = [];

  for (const [index, el] of Array.from(document.querySelectorAll('*')).entries()) {
    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') continue;
    const rect = el.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) continue;
    if (rect.right > viewportWidth + thresholdPx || rect.left < -thresholdPx) {
      offenders.push({
        node_id: `node-${index}`,
        tag: el.tagName.toLowerCase(),
        role: el.getAttribute('role') || '',
        id: el.id || '',
        class_name: el.className && typeof el.className === 'string' ? el.className : '',
        text: cleanText(el.innerText || el.textContent || ''),
        bbox_px: {
          x: rect.left + window.scrollX,
          y: rect.top + window.scrollY,
          width: rect.width,
          height: rect.height,
          right: rect.right + window.scrollX,
        },
      });
    }
  }

  return {
    viewport: { width: window.innerWidth, height: window.innerHeight },
    document: { width: scrollWidth, height: Math.max(root.scrollHeight, body ? body.scrollHeight : 0, window.innerHeight) },
    horizontal_overflow_px: overflowPx,
    offenders,
  };
}
"""
    result = _run_page_script(html_path, script, {"thresholdPx": threshold_px}, viewport=viewport)
    tags = []
    if result["horizontal_overflow_px"] > threshold_px:
        tags.append("mobile_horizontal_overflow")
    if result["offenders"]:
        tags.append("element_horizontal_overflow")

    payload = {
        "tags": tags,
        "horizontal_overflow_px": result["horizontal_overflow_px"],
        "offending_element_count": len(result["offenders"]),
        "viewport": result["viewport"],
        "document": result["document"],
        "threshold_px": threshold_px,
        "source": "WebCoderBench mobile compatibility inspired diagnostic",
    }
    if include_elements:
        payload["offending_elements"] = result["offenders"]
    return payload


def _control_needs_name(control: dict[str, Any]) -> bool:
    tag = control["tag"]
    role = control.get("role", "")
    control_type = control.get("type", "")
    if tag == "input" and control_type in IGNORED_INPUT_TYPES:
        return False
    if tag in {"a", "button", "select", "textarea"}:
        return True
    if tag == "input":
        return True
    return role in NAMED_CONTROL_ROLES


def _control_is_form_field(control: dict[str, Any]) -> bool:
    tag = control["tag"]
    control_type = control.get("type", "")
    if tag not in FORM_CONTROL_TAGS:
        return False
    if tag == "input" and (control_type in IGNORED_INPUT_TYPES or control_type in BUTTON_TYPES):
        return False
    return True


def accessibility_control_tags(
    html_path: PathLike,
    *,
    viewport: tuple[int, int] = DEFAULT_DESKTOP_VIEWPORT,
    include_elements: bool = False,
) -> dict[str, Any]:
    """Return accessibility/control inventory tags from rendered CSSOM."""

    snapshot = extract_cssom_snapshot(html_path, viewport=viewport)
    issues = []
    for control in snapshot["controls"]:
        name = (control.get("accessible_name") or "").strip()
        if _control_needs_name(control) and not name:
            issue_tags = ["missing_accessible_name"]
            if control["tag"] == "button" or control.get("role") == "button":
                issue_tags.append("missing_button_name")
            if control["tag"] == "a" or control.get("role") == "link":
                issue_tags.append("missing_link_name")
            if _control_is_form_field(control):
                issue_tags.append("missing_form_label")
            issues.append(
                {
                    "tags": issue_tags,
                    "node_id": control["node_id"],
                    "tag": control["tag"],
                    "role": control["role"],
                    "type": control["type"],
                    "text": control["text"],
                    "accessible_name": control["accessible_name"],
                    "bbox": control["bbox"],
                    "bbox_px": control["bbox_px"],
                }
            )

    tags = sorted({tag for issue in issues for tag in issue["tags"]})
    payload = {
        "tags": tags,
        "issue_count": len(issues),
        "control_count": snapshot["control_count"],
        "element_count": snapshot["element_count"],
        "viewport": snapshot["viewport"],
        "document": snapshot["document"],
        "source": "WebCoderBench/Lighthouse accessibility inspired diagnostic",
    }
    if include_elements:
        payload["issues"] = issues
    return payload


def webcoderbench_tags(
    html_path: PathLike,
    *,
    desktop_viewport: tuple[int, int] = DEFAULT_DESKTOP_VIEWPORT,
    mobile_viewport: tuple[int, int] = DEFAULT_MOBILE_VIEWPORT,
    include_elements: bool = False,
) -> dict[str, Any]:
    """Return a small WebCoderBench-inspired diagnostic tag bundle."""

    accessibility = accessibility_control_tags(
        html_path,
        viewport=desktop_viewport,
        include_elements=include_elements,
    )
    mobile = mobile_overflow_tags(
        html_path,
        viewport=mobile_viewport,
        include_elements=include_elements,
    )
    tags = sorted({*accessibility["tags"], *mobile["tags"]})
    return {
        "tags": tags,
        "accessibility_control": accessibility,
        "mobile_overflow": mobile,
        "source": "WebCoderBench inspired diagnostic tag bundle",
    }


def _webcoderbench_log_score(inconsistent_num: int, total_num: int) -> float:
    if total_num <= 0:
        return 100.0
    score = (1.0 - math.log2(1.0 + (inconsistent_num / (total_num + 1.0)))) * 100.0
    return _round(max(0.0, min(100.0, score)))


def _majority(values: list[Any]) -> Any:
    if not values:
        return None
    return Counter(values).most_common(1)[0][0]


def webcoderbench_component_style_score(
    html_path: PathLike,
    *,
    viewport: tuple[int, int] = DEFAULT_DESKTOP_VIEWPORT,
    card_keywords: tuple[str, ...] = DEFAULT_CARD_KEYWORDS,
    include_components: bool = False,
) -> dict[str, Any]:
    """Paper-faithful local fallback for WebCoderBench component style consistency.

    The paper describes extracting "card"-related components, grouping parallel
    components, flagging structural/styling inconsistency, then applying a
    logarithmic penalty. The public artifacts found so far do not expose the
    official evaluator, so this keeps the paper formula and reports the local
    extraction assumptions.
    """

    script = """
({ keywords }) => {
  const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim();
  const isVisible = (el) => {
    const cs = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return cs.display !== 'none' && cs.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
  };
  const cssPath = (el) => {
    const parts = [];
    let node = el;
    while (node && node.nodeType === Node.ELEMENT_NODE && node !== document.documentElement) {
      const parent = node.parentElement;
      if (!parent) break;
      const siblings = Array.from(parent.children).filter((child) => child.tagName === node.tagName);
      const index = siblings.indexOf(node) + 1;
      parts.unshift(`${node.tagName.toLowerCase()}:nth-of-type(${index})`);
      node = parent;
    }
    return parts.join('>');
  };
  const attrText = (el) => clean([
    el.id,
    el.className && typeof el.className === 'string' ? el.className : '',
    el.getAttribute('role') || '',
    el.getAttribute('aria-label') || '',
    ...Array.from(el.attributes)
      .filter((attr) => attr.name.startsWith('data-'))
      .map((attr) => attr.value || ''),
  ].join(' ')).toLowerCase();
  const slotFor = (el) => {
    const tag = el.tagName.toLowerCase();
    const attrs = attrText(el);
    if (/^h[1-6]$/.test(tag) || /title|heading|header|name/.test(attrs)) return 'title';
    if (tag === 'svg' || tag === 'img' || tag === 'i' || /icon|avatar|media|image/.test(attrs)) return 'icon';
    if (clean(el.innerText || el.textContent || '').length > 0) return 'body';
    return 'other';
  };
  const styleSignature = (el) => {
    const cs = window.getComputedStyle(el);
    return [
      cs.display,
      cs.flexDirection,
      cs.gridTemplateColumns,
      cs.alignItems,
      cs.justifyContent,
      cs.gap,
      cs.paddingTop,
      cs.paddingRight,
      cs.paddingBottom,
      cs.paddingLeft,
      cs.borderRadius,
    ].join('|');
  };
  const structuralSignature = (el) => {
    const children = Array.from(el.children).filter(isVisible);
    const direct = children.map((child) => `${child.tagName.toLowerCase()}:${slotFor(child)}:${child.children.length}`).join('>');
    const slots = children.map(slotFor).sort().join(',');
    return `${children.length}|${direct}|${slots}`;
  };

  const keywordList = keywords.map((keyword) => String(keyword).toLowerCase()).filter(Boolean);
  const components = [];
  for (const [index, el] of Array.from(document.querySelectorAll('*')).entries()) {
    if (!isVisible(el)) continue;
    const attrs = attrText(el);
    const matchedKeyword = keywordList.find((keyword) => attrs.includes(keyword));
    if (!matchedKeyword) continue;
    const rect = el.getBoundingClientRect();
    const children = Array.from(el.children).filter(isVisible);
    const slots = children.map(slotFor);
    components.push({
      node_id: `node-${index}`,
      tag: el.tagName.toLowerCase(),
      keyword: matchedKeyword,
      id: el.id || '',
      class_name: el.className && typeof el.className === 'string' ? el.className : '',
      text: clean(el.innerText || el.textContent || '').slice(0, 160),
      parent_path: el.parentElement ? cssPath(el.parentElement) : '',
      path: cssPath(el),
      child_count: children.length,
      child_tags: children.map((child) => child.tagName.toLowerCase()),
      slot_counts: {
        title: slots.filter((slot) => slot === 'title').length,
        icon: slots.filter((slot) => slot === 'icon').length,
        body: slots.filter((slot) => slot === 'body').length,
      },
      structural_signature: structuralSignature(el),
      style_signature: styleSignature(el),
      bbox_px: {
        x: rect.left + window.scrollX,
        y: rect.top + window.scrollY,
        width: rect.width,
        height: rect.height,
      },
    });
  }
  return components;
}
"""
    components = _run_page_script(
        html_path,
        script,
        {"keywords": list(card_keywords)},
        viewport=viewport,
    )
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for component in components:
        grouped[f"{component['keyword']}::{component['parent_path']}"].append(component)

    inconsistent_components = []
    evaluated_components = []
    group_summaries = []
    for group_key, group_components in grouped.items():
        if len(group_components) < 2:
            group_summaries.append(
                {
                    "group": group_key,
                    "component_count": len(group_components),
                    "evaluated": False,
                    "reason": "singleton_group",
                }
            )
            continue

        majority_structure = _majority([component["structural_signature"] for component in group_components])
        majority_style = _majority([component["style_signature"] for component in group_components])
        group_issues = []
        for component in group_components:
            issues = []
            if component["child_count"] < 2:
                issues.append("fewer_than_two_children")
            if component["structural_signature"] != majority_structure:
                issues.append("mismatched_hierarchy_or_tags")
            if component["style_signature"] != majority_style:
                issues.append("mismatched_card_style")
            if issues:
                group_issues.append({"node_id": component["node_id"], "issues": issues})
                inconsistent_components.append({**component, "issues": issues, "group": group_key})
            evaluated_components.append(component)

        group_summaries.append(
            {
                "group": group_key,
                "component_count": len(group_components),
                "evaluated": True,
                "inconsistent_count": len(group_issues),
                "majority_structure": majority_structure,
                "majority_style": majority_style,
                "issues": group_issues,
            }
        )

    total_num = len(evaluated_components)
    inconsistent_num = len(inconsistent_components)
    tags = ["component_style_inconsistency"] if inconsistent_num else []
    payload = {
        "score": _webcoderbench_log_score(inconsistent_num, total_num),
        "tags": tags,
        "inconsistent_num": inconsistent_num,
        "total_num": total_num,
        "candidate_component_count": len(components),
        "evaluated_group_count": sum(1 for group in group_summaries if group["evaluated"]),
        "applicable": total_num > 0,
        "formula": "score = (1 - log2(1 + (inconsistent_num / (total_num + 1)))) * 100",
        "source": "WebCoderBench Component Style Consistency paper-faithful local fallback",
        "card_keywords": list(card_keywords),
        "groups": group_summaries,
    }
    if include_components:
        payload["components"] = components
        payload["inconsistent_components"] = inconsistent_components
    return payload


def webcoderbench_icon_style_score(
    html_path: PathLike,
    *,
    viewport: tuple[int, int] = DEFAULT_DESKTOP_VIEWPORT,
    include_icons: bool = False,
    size_tolerance_px: float = 2.0,
) -> dict[str, Any]:
    """Paper-faithful local fallback for WebCoderBench icon style consistency."""

    script = """
() => {
  const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim();
  const isVisible = (el) => {
    const cs = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return cs.display !== 'none' && cs.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
  };
  const cssPath = (el) => {
    const parts = [];
    let node = el;
    while (node && node.nodeType === Node.ELEMENT_NODE && node !== document.documentElement) {
      const parent = node.parentElement;
      if (!parent) break;
      const siblings = Array.from(parent.children).filter((child) => child.tagName === node.tagName);
      const index = siblings.indexOf(node) + 1;
      parts.unshift(`${node.tagName.toLowerCase()}:nth-of-type(${index})`);
      node = parent;
    }
    return parts.join('>');
  };
  const iconSet = (svg) => {
    const text = clean([
      svg.getAttribute('class') || '',
      svg.parentElement?.getAttribute('class') || '',
      svg.getAttribute('data-icon') || '',
      svg.getAttribute('aria-label') || '',
    ].join(' ')).toLowerCase();
    const known = ['lucide', 'heroicon', 'heroicons', 'fa-', 'fontawesome', 'mdi', 'bootstrap-icons', 'bi-', 'material'];
    return known.find((name) => text.includes(name)) || 'inline-svg';
  };
  const strokeWidth = (svg) => {
    const own = svg.getAttribute('stroke-width') || window.getComputedStyle(svg).strokeWidth;
    if (own && own !== 'none') return own;
    const child = svg.querySelector('[stroke-width]');
    return child ? child.getAttribute('stroke-width') : '';
  };
  const shapeSignature = (svg) => {
    const counts = {};
    for (const tag of ['path', 'circle', 'rect', 'line', 'polyline', 'polygon', 'ellipse']) {
      counts[tag] = svg.querySelectorAll(tag).length;
    }
    return `${svg.getAttribute('viewBox') || ''}|${Object.entries(counts).map(([key, value]) => `${key}:${value}`).join(',')}`;
  };
  const icons = [];
  for (const [index, svg] of Array.from(document.querySelectorAll('svg')).entries()) {
    if (!isVisible(svg)) continue;
    const rect = svg.getBoundingClientRect();
    const container = svg.closest('button,a,[class*="icon"],[class*="Icon"],[class*="btn"],[class*="button"]') || svg.parentElement;
    const containerStyle = container ? window.getComputedStyle(container) : window.getComputedStyle(svg);
    icons.push({
      node_id: `svg-${index}`,
      icon_set: iconSet(svg),
      group: container?.parentElement ? cssPath(container.parentElement) : '',
      container_path: container ? cssPath(container) : '',
      class_name: svg.getAttribute('class') || '',
      size: { width: rect.width, height: rect.height },
      stroke_width: strokeWidth(svg),
      shape_signature: shapeSignature(svg),
      background_shape: containerStyle.borderRadius || '0px',
      background_color: containerStyle.backgroundColor || '',
      background_padding: [
        containerStyle.paddingTop,
        containerStyle.paddingRight,
        containerStyle.paddingBottom,
        containerStyle.paddingLeft,
      ].join(' '),
      bbox_px: {
        x: rect.left + window.scrollX,
        y: rect.top + window.scrollY,
        width: rect.width,
        height: rect.height,
      },
    });
  }
  return icons;
}
"""
    icons = _run_page_script(html_path, script, {}, viewport=viewport)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for icon in icons:
        grouped[icon["group"] or "ungrouped"].append(icon)

    failed_dimensions: set[str] = set()
    group_summaries = []
    for group_key, group_icons in grouped.items():
        if len(group_icons) < 2:
            group_summaries.append(
                {
                    "group": group_key,
                    "icon_count": len(group_icons),
                    "evaluated": False,
                    "reason": "singleton_group",
                }
            )
            continue

        failures = []
        if len({icon["icon_set"] for icon in group_icons}) > 1:
            failures.append("icon_set_consistency")

        widths = [float(icon["size"]["width"]) for icon in group_icons]
        heights = [float(icon["size"]["height"]) for icon in group_icons]
        if (max(widths) - min(widths) > size_tolerance_px) or (max(heights) - min(heights) > size_tolerance_px):
            failures.append("size_uniformity")

        stroke_values = {str(icon["stroke_width"]).strip() for icon in group_icons if str(icon["stroke_width"]).strip()}
        if len(stroke_values) > 1:
            failures.append("stroke_width_uniformity")

        if len({icon["shape_signature"] for icon in group_icons}) > 1:
            failures.append("underlying_shape_consistency")
        if len({icon["background_shape"] for icon in group_icons}) > 1:
            failures.append("background_shape_consistency")
        if len({icon["background_color"] for icon in group_icons}) > 1:
            failures.append("background_color_consistency")
        if len({icon["background_padding"] for icon in group_icons}) > 1:
            failures.append("background_padding_uniformity")

        failed_dimensions.update(failures)
        group_summaries.append(
            {
                "group": group_key,
                "icon_count": len(group_icons),
                "evaluated": True,
                "failed_dimensions": failures,
            }
        )

    failed_dimension_num = len(failed_dimensions)
    score = max(0.0, 100.0 - 25.0 * failed_dimension_num)
    payload = {
        "score": _round(score),
        "tags": ["icon_style_inconsistency"] if failed_dimension_num else [],
        "failed_dimension_num": failed_dimension_num,
        "failed_dimensions": sorted(failed_dimensions),
        "icon_count": len(icons),
        "evaluated_group_count": sum(1 for group in group_summaries if group["evaluated"]),
        "applicable": len(icons) > 1,
        "formula": "score = max(0, 100 - 25 * failed_dimension_num)",
        "source": "WebCoderBench Icon Style Consistency paper-faithful local fallback",
        "groups": group_summaries,
    }
    if include_icons:
        payload["icons"] = icons
    return payload


def _load_grayscale(path_or_image: PathLike | Image.Image) -> np.ndarray:
    if isinstance(path_or_image, Image.Image):
        image = path_or_image.convert("L")
    else:
        image = Image.open(path_or_image).convert("L")
    return np.asarray(image)


def _alignment_groups(rects: list[dict[str, float]], key: str, tolerance_px: float) -> list[list[dict[str, float]]]:
    ordered = sorted(rects, key=lambda rect: rect[key])
    groups: list[list[dict[str, float]]] = []
    for rect in ordered:
        if not groups:
            groups.append([rect])
            continue
        median = float(np.median([item[key] for item in groups[-1]]))
        if abs(rect[key] - median) <= tolerance_px:
            groups[-1].append(rect)
        else:
            groups.append([rect])
    return groups


def _alignment_error_count(groups: list[list[dict[str, float]]], key: str, tolerance_px: float) -> int:
    errors = 0
    for group in groups:
        if len(group) < 2:
            continue
        median = float(np.median([item[key] for item in group]))
        errors += sum(1 for item in group if abs(item[key] - median) > tolerance_px)
    return errors


def webcoderbench_layout_consistency_score(
    screenshot: PathLike | Image.Image,
    *,
    canny_threshold1: int = 50,
    canny_threshold2: int = 150,
    min_area_ratio: float = 0.00015,
    max_area_ratio: float = 0.75,
    alignment_tolerance_px: float | None = None,
    include_elements: bool = False,
) -> dict[str, Any]:
    """Paper-faithful local fallback for WebCoderBench layout consistency."""

    gray = _load_grayscale(screenshot)
    height, width = gray.shape[:2]
    total_area = float(width * height)
    tolerance = alignment_tolerance_px or max(6.0, min(width, height) * 0.006)

    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    edges = cv2.Canny(blurred, canny_threshold1, canny_threshold2)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    morphed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)
    morphed = cv2.dilate(morphed, kernel, iterations=1)
    contours, _hierarchy = cv2.findContours(morphed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    rects = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = float(w * h)
        if w < 16 or h < 8:
            continue
        area_ratio = area / total_area if total_area else 0.0
        if area_ratio < min_area_ratio or area_ratio > max_area_ratio:
            continue
        # WebCoderBench mentions banner-region masks. This local fallback keeps
        # page-wide regions only when they are tall enough to behave like content.
        if w > width * 0.92 and h < height * 0.06:
            continue
        rects.append(
            {
                "id": float(len(rects)),
                "x": float(x),
                "y": float(y),
                "width": float(w),
                "height": float(h),
                "left": float(x),
                "right": float(x + w),
                "top": float(y),
                "bottom": float(y + h),
                "center_x": float(x + w / 2.0),
                "center_y": float(y + h / 2.0),
                "area": area,
                "area_ratio": area_ratio,
            }
        )

    total_elements = len(rects)
    if total_elements == 0:
        payload = {
            "score": 0.0,
            "tags": ["no_layout_elements_detected"],
            "total_errors": 0,
            "total_elements": 0,
            "alignment_tolerance_px": _round(tolerance),
            "source": "WebCoderBench Layout Consistency paper-faithful local fallback",
            "formula": "score = (1 - log2(1 + (total_errors / (total_elements + 1)))) * 100",
            "applicable": False,
        }
        if include_elements:
            payload["elements"] = []
        return payload

    row_groups = _alignment_groups(rects, "center_y", tolerance * 1.5)
    left_groups = _alignment_groups(rects, "left", tolerance)
    right_groups = _alignment_groups(rects, "right", tolerance)
    center_x_groups = _alignment_groups(rects, "center_x", tolerance)
    top_groups = _alignment_groups(rects, "top", tolerance)
    bottom_groups = _alignment_groups(rects, "bottom", tolerance)
    center_y_groups = _alignment_groups(rects, "center_y", tolerance)

    def has_alignment_peer(rect: dict[str, float], groups: list[list[dict[str, float]]]) -> bool:
        return any(len(group) > 1 and any(item is rect for item in group) for group in groups)

    error_breakdown = {
        "elements_without_vertical_alignment": sum(
            1
            for rect in rects
            if not (
                has_alignment_peer(rect, left_groups)
                or has_alignment_peer(rect, right_groups)
                or has_alignment_peer(rect, center_x_groups)
            )
        ),
        "elements_without_horizontal_alignment": sum(
            1
            for rect in rects
            if not (
                has_alignment_peer(rect, top_groups)
                or has_alignment_peer(rect, bottom_groups)
                or has_alignment_peer(rect, center_y_groups)
            )
        ),
        "row_bottom_alignment": _alignment_error_count(row_groups, "bottom", tolerance),
    }
    total_errors = int(sum(error_breakdown.values()))
    score = _webcoderbench_log_score(total_errors, total_elements)
    payload = {
        "score": score,
        "tags": ["layout_alignment_inconsistency"] if total_errors else [],
        "total_errors": total_errors,
        "total_elements": total_elements,
        "error_breakdown": error_breakdown,
        "row_group_count": len([group for group in row_groups if len(group) > 1]),
        "vertical_alignment_group_count": len(
            [group for group in [*left_groups, *right_groups, *center_x_groups] if len(group) > 1]
        ),
        "alignment_tolerance_px": _round(tolerance),
        "canny_thresholds": [canny_threshold1, canny_threshold2],
        "formula": "score = (1 - log2(1 + (total_errors / (total_elements + 1)))) * 100",
        "source": "WebCoderBench Layout Consistency paper-faithful local fallback",
        "applicable": True,
    }
    if include_elements:
        payload["elements"] = [
            {
                **{key: _round(value) for key, value in rect.items() if key != "area_ratio"},
                "area_ratio": _round(rect["area_ratio"]),
            }
            for rect in sorted(rects, key=lambda item: (item["y"], item["x"]))
        ]
    return payload


def _largest_rectangle_in_mask(mask: np.ndarray) -> tuple[int, tuple[int, int, int, int]]:
    rows, cols = mask.shape
    heights = np.zeros(cols, dtype=np.int32)
    best_area = 0
    best_rect = (0, 0, 0, 0)

    for row in range(rows):
        heights = np.where(mask[row], heights + 1, 0)
        stack: list[int] = []
        for col in range(cols + 1):
            current_height = int(heights[col]) if col < cols else 0
            while stack and current_height < int(heights[stack[-1]]):
                top_index = stack.pop()
                rect_height = int(heights[top_index])
                left = stack[-1] + 1 if stack else 0
                rect_width = col - left
                area = rect_height * rect_width
                if area > best_area:
                    best_area = area
                    best_rect = (left, row - rect_height + 1, rect_width, rect_height)
            stack.append(col)
    return best_area, best_rect


def webcoderbench_layout_sparsity_score(
    screenshot: PathLike | Image.Image,
    *,
    tolerance: int = 80,
    max_dimension: int | None = 1200,
    include_mask_summary: bool = False,
) -> dict[str, Any]:
    """Paper-faithful local fallback for WebCoderBench layout sparsity."""

    gray = _load_grayscale(screenshot)
    original_height, original_width = gray.shape[:2]
    scale = 1.0
    if max_dimension and max(original_width, original_height) > max_dimension:
        scale = max_dimension / float(max(original_width, original_height))
        gray = cv2.resize(gray, (int(original_width * scale), int(original_height * scale)), interpolation=cv2.INTER_AREA)

    height, width = gray.shape[:2]
    buckets = np.floor((gray.astype(np.float32) + tolerance / 2.0) / tolerance).astype(np.int16)
    best_area = 0
    best_rect = (0, 0, 0, 0)
    bucket_summaries = []
    for bucket in np.unique(buckets):
        mask = buckets == bucket
        area, rect = _largest_rectangle_in_mask(mask)
        bucket_summaries.append({"bucket": int(bucket), "largest_area": int(area)})
        if area > best_area:
            best_area = int(area)
            best_rect = rect

    image_area = float(width * height)
    sparsity_rate = (best_area / image_area * 100.0) if image_area else 100.0
    score = min(math.sqrt(max(0.0, 100.0 - sparsity_rate)) * 10.0, 100.0)
    left, top, rect_width, rect_height = best_rect
    scale_back = 1.0 / scale if scale else 1.0
    payload = {
        "score": _round(score),
        "tags": ["large_blank_region"] if sparsity_rate >= 25.0 else [],
        "sparsity_rate": _round(sparsity_rate),
        "largest_blank_rectangle": {
            "x": int(round(left * scale_back)),
            "y": int(round(top * scale_back)),
            "width": int(round(rect_width * scale_back)),
            "height": int(round(rect_height * scale_back)),
            "area": int(round(best_area * scale_back * scale_back)),
        },
        "tolerance": tolerance,
        "processed_size": {"width": width, "height": height},
        "original_size": {"width": original_width, "height": original_height},
        "formula": "score = min(sqrt(100 - sparsity_rate) * 10, 100)",
        "source": "WebCoderBench Layout Sparsity paper-faithful local fallback",
        "applicable": True,
    }
    if include_mask_summary:
        payload["bucket_summaries"] = bucket_summaries
    return payload


def webcoderbench_visual_quality_scores(
    html_path: PathLike,
    screenshot: PathLike | Image.Image,
    *,
    viewport: tuple[int, int] = DEFAULT_DESKTOP_VIEWPORT,
    include_details: bool = False,
) -> dict[str, Any]:
    """Return the implemented local WebCoderBench visual-quality metric surfaces."""

    component = webcoderbench_component_style_score(
        html_path,
        viewport=viewport,
        include_components=include_details,
    )
    icon = webcoderbench_icon_style_score(
        html_path,
        viewport=viewport,
        include_icons=include_details,
    )
    layout = webcoderbench_layout_consistency_score(
        screenshot,
        include_elements=include_details,
    )
    sparsity = webcoderbench_layout_sparsity_score(
        screenshot,
        include_mask_summary=include_details,
    )
    tags = sorted({*component["tags"], *icon["tags"], *layout["tags"], *sparsity["tags"]})
    return {
        "tags": tags,
        "metrics": {
            "component_style_consistency": component,
            "icon_style_consistency": icon,
            "layout_consistency": layout,
            "layout_sparsity": sparsity,
        },
        "source": "WebCoderBench visual-quality paper-faithful local fallback bundle",
        "official_evaluator": "not_found_in_public_artifacts_checked",
    }


def _load_rgb_array(path_or_image: PathLike | Image.Image) -> np.ndarray:
    if isinstance(path_or_image, Image.Image):
        image = path_or_image.convert("RGB")
    else:
        image = Image.open(path_or_image).convert("RGB")
    return np.asarray(image)


def _image_size(path_or_image: PathLike | Image.Image) -> tuple[int, int]:
    if isinstance(path_or_image, Image.Image):
        return path_or_image.size
    with Image.open(path_or_image) as image:
        return image.size


def _pixelmatch_color_delta(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    diff = a.astype(np.float32) - b.astype(np.float32)
    y = diff[:, :, 0] * 0.29889531 + diff[:, :, 1] * 0.58662247 + diff[:, :, 2] * 0.11448223
    i = diff[:, :, 0] * 0.59597799 - diff[:, :, 1] * 0.27417610 - diff[:, :, 2] * 0.32180189
    q = diff[:, :, 0] * 0.21147017 - diff[:, :, 1] * 0.52261711 + diff[:, :, 2] * 0.31114694
    return 0.5053 * y * y + 0.299 * i * i + 0.1957 * q * q


def presentation_diff_tags(
    reference: PathLike | Image.Image,
    candidate: PathLike | Image.Image,
    *,
    threshold: float = 0.1,
    min_cluster_area: int = 64,
    resize_candidate: bool = True,
    include_clusters: bool = True,
) -> dict[str, Any]:
    """Return WebSee-style visual-difference cluster tags.

    This is the detection half of the WebSee idea. It does not yet localize
    clusters back to DOM elements.
    """

    ref = _load_rgb_array(reference)
    cand_image = Image.open(candidate).convert("RGB") if not isinstance(candidate, Image.Image) else candidate.convert("RGB")
    if resize_candidate and cand_image.size != (ref.shape[1], ref.shape[0]):
        cand_image = cand_image.resize((ref.shape[1], ref.shape[0]), Image.Resampling.LANCZOS)
    cand = np.asarray(cand_image)
    if ref.shape != cand.shape:
        raise ValueError(f"Image sizes differ: reference={ref.shape}, candidate={cand.shape}")

    max_delta = 35215.0 * threshold * threshold
    diff_mask = _pixelmatch_color_delta(ref, cand) > max_delta
    diff_pixels = int(diff_mask.sum())
    total_pixels = int(diff_mask.size)
    diff_ratio = diff_pixels / total_pixels if total_pixels else 1.0

    component_count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
        diff_mask.astype(np.uint8),
        connectivity=8,
    )
    clusters = []
    for component_index in range(1, component_count):
        left, top, width, height, area = stats[component_index]
        if int(area) < min_cluster_area:
            continue
        clusters.append(
            {
                "bbox_px": [int(left), int(top), int(width), int(height)],
                "area": int(area),
                "area_ratio": _round(int(area) / total_pixels if total_pixels else 0.0),
            }
        )
    clusters.sort(key=lambda cluster: cluster["area"], reverse=True)

    tags = []
    if diff_pixels > 0:
        tags.append("visual_diff")
    if clusters:
        tags.append("visual_diff_cluster")
    if diff_ratio >= 0.05:
        tags.append("large_visual_diff")

    payload = {
        "tags": tags,
        "diff_pixels": diff_pixels,
        "total_pixels": total_pixels,
        "diff_ratio": _round(diff_ratio),
        "cluster_count": len(clusters),
        "threshold": threshold,
        "min_cluster_area": min_cluster_area,
        "resized_candidate": bool(resize_candidate),
        "source": "WebSee inspired visual difference detection diagnostic",
    }
    if include_clusters:
        payload["clusters"] = clusters
    return payload


def _bbox_overlap(a: list[float], b: list[float]) -> dict[str, float]:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1 = max(ax, bx)
    y1 = max(ay, by)
    x2 = min(ax + aw, bx + bw)
    y2 = min(ay + ah, by + bh)
    overlap = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    a_area = max(0.0, aw) * max(0.0, ah)
    b_area = max(0.0, bw) * max(0.0, bh)
    union = a_area + b_area - overlap
    return {
        "overlap_area": overlap,
        "cluster_coverage": overlap / a_area if a_area else 0.0,
        "element_coverage": overlap / b_area if b_area else 0.0,
        "iou": overlap / union if union else 0.0,
    }


def websee_dom_localization_tags(
    candidate_html: PathLike,
    reference_screenshot: PathLike | Image.Image,
    candidate_screenshot: PathLike | Image.Image,
    *,
    threshold: float = 0.1,
    min_cluster_area: int = 64,
    max_elements_per_cluster: int = 5,
    viewport: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """Map WebSee-style visual diff clusters to candidate DOM elements.

    This is not the upstream Java WebSee implementation. It follows the same
    detection -> localization shape using our local screenshot diff clusters and
    Playwright-rendered CSSOM boxes.
    """

    diff = presentation_diff_tags(
        reference_screenshot,
        candidate_screenshot,
        threshold=threshold,
        min_cluster_area=min_cluster_area,
        resize_candidate=True,
        include_clusters=True,
    )
    snapshot = extract_cssom_snapshot(candidate_html, screenshot_path=candidate_screenshot, viewport=viewport)

    ref_width, ref_height = _image_size(reference_screenshot)
    cand_width, cand_height = _image_size(candidate_screenshot)
    scale_x = ref_width / cand_width if cand_width else 1.0
    scale_y = ref_height / cand_height if cand_height else 1.0

    localized_clusters = []
    unresolved_count = 0
    for cluster in diff.get("clusters", []):
        cluster_bbox = [float(value) for value in cluster["bbox_px"]]
        matches = []
        for element in snapshot["elements"]:
            element_bbox_raw = element["bbox_px"]
            element_bbox = [
                float(element_bbox_raw["x"]) * scale_x,
                float(element_bbox_raw["y"]) * scale_y,
                float(element_bbox_raw["width"]) * scale_x,
                float(element_bbox_raw["height"]) * scale_y,
            ]
            overlap = _bbox_overlap(cluster_bbox, element_bbox)
            if overlap["overlap_area"] <= 0:
                continue
            rank_score = 0.55 * overlap["cluster_coverage"] + 0.30 * overlap["iou"] + 0.15 * overlap["element_coverage"]
            matches.append(
                {
                    "score": _round(rank_score),
                    "node_id": element["node_id"],
                    "tag": element["tag"],
                    "role": element["role"],
                    "type": element["type"],
                    "text": element["text"][:160],
                    "accessible_name": element["accessible_name"][:160],
                    "is_control": element["is_control"],
                    "bbox_px_scaled_to_diff": [_round(value) for value in element_bbox],
                    "overlap": {key: _round(value) for key, value in overlap.items()},
                }
            )
        non_root_matches = [match for match in matches if match["tag"] not in {"html", "body"}]
        if non_root_matches:
            matches = non_root_matches
        matches.sort(key=lambda item: item["score"], reverse=True)
        if not matches:
            unresolved_count += 1
        localized_clusters.append(
            {
                **cluster,
                "localized_elements": matches[:max_elements_per_cluster],
                "localized": bool(matches),
            }
        )

    tags = list(diff["tags"])
    if localized_clusters:
        tags.append("visual_diff_localization_attempted")
    if unresolved_count:
        tags.append("unlocalized_visual_diff_cluster")

    return {
        "tags": sorted(set(tags)),
        "cluster_count": diff["cluster_count"],
        "localized_cluster_count": len(localized_clusters) - unresolved_count,
        "unresolved_cluster_count": unresolved_count,
        "diff_ratio": diff["diff_ratio"],
        "scale": {"x": _round(scale_x), "y": _round(scale_y)},
        "clusters": localized_clusters,
        "candidate_snapshot": {
            "element_count": snapshot["element_count"],
            "control_count": snapshot["control_count"],
            "document": snapshot["document"],
            "viewport": snapshot["viewport"],
        },
        "source": "WebSee-style local fallback: visual diff clusters localized to Playwright CSSOM boxes",
        "upstream_websee": "not_used; upstream Java build blocked by old Maven dependencies",
    }
