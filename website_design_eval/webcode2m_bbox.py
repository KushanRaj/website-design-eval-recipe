from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any

PathLike = str | os.PathLike[str]


def _read_text(path_or_text: PathLike | str) -> str:
    if isinstance(path_or_text, os.PathLike):
        return Path(path_or_text).read_text(encoding="utf-8", errors="ignore")
    try:
        path = Path(path_or_text)
        if "\n" not in path_or_text and len(path_or_text) < 512 and path.exists():
            return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        pass
    return str(path_or_text)


def _wait_images_loaded(page: Any, timeout: float = 3.0) -> None:
    end_time = time.time() + timeout
    for image in page.query_selector_all("img"):
        while time.time() < end_time:
            if page.evaluate("(img) => img.complete", image):
                break
            time.sleep(0.01)


def extract_webcode2m_bbox_tree(
    html_path: PathLike,
    *,
    viewport: tuple[int, int] | None = None,
    timeout_ms: int = 10000,
    image_timeout_s: float = 3.0,
) -> dict[str, Any] | None:
    """Extract WebCode2M's rendered bbox tree.

    This mirrors the `output_bbox` branch in WebCode2M's
    `scripts/evaluation/html2screenshot.py`: it renders HTML with Playwright,
    starts from `document.body`, skips hidden/zero-size nodes, keeps inline
    `style` attributes, and stores integer `[x, y, width, height]` boxes.
    """

    from playwright.sync_api import sync_playwright

    html = _read_text(html_path)
    script = """
() => {
  let depth = 0;
  function generateBbox(element, depth) {
    if (depth > 20) {
      return;
    }
    let rect = element.getBoundingClientRect();
    let style = window.getComputedStyle(element);
    let content = '';
    if (element.childNodes.length === 1 && element.childNodes[0].nodeType === Node.TEXT_NODE) {
      content = element.childNodes[0].textContent.trim();
      if (content[0] === '<') content = '';
    }
    if (((rect.width === 0 || rect.height === 0) && content === '') || style.display === 'none' || style.visibility === 'hidden') {
      return null;
    }
    return {
      type: element.tagName.toLowerCase(),
      content: content,
      style: element.getAttribute('style'),
      bbox: [
        parseInt(rect.left + window.scrollX),
        parseInt(rect.top + window.scrollY),
        parseInt(rect.width),
        parseInt(rect.height)
      ],
      children: Array.from(element.children).map(item => generateBbox(item, depth + 1)).filter(item => item)
    };
  }
  return generateBbox(document.body, 0);
}
"""

    context_args: dict[str, Any] = {}
    if viewport is not None:
        context_args["viewport"] = {"width": int(viewport[0]), "height": int(viewport[1])}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(**context_args)
        page = context.new_page()
        try:
            page.set_content(html, timeout=timeout_ms, wait_until="domcontentloaded")
            _wait_images_loaded(page, timeout=image_timeout_s)
            return page.evaluate(script)
        finally:
            context.close()
            browser.close()


def webcode2m_bbox_tree_to_html(
    node: dict[str, Any] | str | None,
    *,
    style: bool = False,
    size: tuple[int, int] = (1, 1),
    precision: int = 3,
) -> str:
    """Mirror WebCode2M `BboxTree2Html` from `scripts/train/utils.py`."""

    if isinstance(node, str):
        return node
    if not node:
        return ""

    dom_type = node["type"]
    children = node.get("children") or []
    child_doms = [webcode2m_bbox_tree_to_html(child, style=style, size=size, precision=precision) for child in children]
    if style:
        style_attr = node.get("style") or ""
        if dom_type == "input":
            return f"<{dom_type} style='{style_attr}' value='{''.join(child_doms)}'></{dom_type}>"
        if dom_type == "img":
            src = child_doms[0] if child_doms else ""
            return f"<{dom_type} style='{style_attr}' src='{src}'></{dom_type}>"
        return f"<{dom_type} style='{style_attr}'>{''.join(child_doms)}</{dom_type}>"

    width, height = size
    bbox = node["bbox"]
    normalized_bbox = [
        round(float(bbox[0]) / width, precision),
        round(float(bbox[1]) / height, precision),
        round(float(bbox[2]) / width, precision),
        round(float(bbox[3]) / height, precision),
    ]
    return f"<{dom_type} bbox={normalized_bbox}>{''.join(child_doms)}</{dom_type}>"


def webcode2m_bbox_tree_to_style_list(
    node: dict[str, Any],
    *,
    index: str = "",
    skip_leaf: bool = True,
) -> list[dict[str, Any]]:
    """Mirror WebCode2M `BboxTree2StyleList` from `scripts/train/utils.py`."""

    children = node.get("children") or []
    if skip_leaf and not children:
        return []

    style_list = [
        {
            "type": node["type"],
            "bbox": node["bbox"],
            "index": index,
            "style": node.get("style", "").strip() if node.get("style") else "",
            "children": [
                {
                    "type": child["type"],
                    "bbox": child["bbox"],
                    "style": child.get("style", "").strip() if child.get("style") else "",
                }
                for child in children
            ],
        }
    ]
    for child_index, child in enumerate(children):
        next_index = f"{index}{'-' if index else ''}{child_index}"
        style_list.extend(webcode2m_bbox_tree_to_style_list(child, index=next_index, skip_leaf=skip_leaf))
    return style_list


def webcode2m_html_to_bbox_tree(html: str, *, size: tuple[int, int] = (1, 1)) -> dict[str, Any] | None:
    """Mirror WebCode2M `Html2BboxTree` for bbox-annotated pseudo-HTML."""

    root_node = None
    index: list[int] | None = None
    remaining = html

    while remaining:
        remaining = remaining.replace("<s>", "").strip()
        match_bot = re.search(r"^<([a-zA-Z0-9]+)\s*([^>]*)\s*>", remaining)
        match_eot = re.search(r"^</([a-zA-Z0-9]+)\s*>", remaining)

        if match_bot:
            dom_type, bbox_str = match_bot.groups()
            bbox = [float(value) for value in bbox_str.split("[", 1)[1].split("]", 1)[0].split(",")]
            bbox[0] = int(bbox[0] * size[0])
            bbox[1] = int(bbox[1] * size[1])
            bbox[2] = int(bbox[2] * size[0])
            bbox[3] = int(bbox[3] * size[1])
            remaining = remaining[match_bot.end() :]
            node = {"type": dom_type, "bbox": bbox, "children": []}

            if not root_node:
                root_node = node
                index = []
            else:
                target = root_node
                assert index is not None
                for child_index in index:
                    target = target["children"][child_index]
                target["children"].append(node)
                index.append(len(target["children"]) - 1)
        elif match_eot:
            (dom_type,) = match_eot.groups()
            remaining = remaining[match_eot.end() :]
            if root_node is None or index is None:
                break
            target = root_node
            for child_index in index:
                target = target["children"][child_index]
            if target["type"] == dom_type and len(index):
                index.pop()
        else:
            break

    return root_node
