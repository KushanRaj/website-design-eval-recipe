from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

from .cssom import extract_cssom_snapshot

PathLike = str | os.PathLike[str]

DEFAULT_DESKTOP_VIEWPORT = (1440, 900)
DEFAULT_MOBILE_VIEWPORT = (390, 844)

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


def _load_rgb_array(path_or_image: PathLike | Image.Image) -> np.ndarray:
    if isinstance(path_or_image, Image.Image):
        image = path_or_image.convert("RGB")
    else:
        image = Image.open(path_or_image).convert("RGB")
    return np.asarray(image)


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
