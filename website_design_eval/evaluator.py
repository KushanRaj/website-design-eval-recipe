from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from PIL import Image
from playwright.sync_api import Browser, Page

from .block_visual import _score_bbox_geometry
from .scoring import (
    _pick_torch_device,
    cssom_block_style_score,
    dreamsim_distance,
    render_sanity_score,
    screenshot_size_match_score,
    visual_block_score,
    vlm_judge_score,
    webcode2m_dom_score,
    webcode2m_text_score,
)

PathLike = str | os.PathLike[str]


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


CSSOM_ARTIFACT_SCRIPT = """
({ controlSelectors }) => {
  const styleProps = [
    'font-family', 'font-size', 'font-weight', 'line-height', 'letter-spacing',
    'text-align', 'text-transform', 'color', 'background-color',
    'border-top-color', 'border-right-color', 'border-bottom-color', 'border-left-color',
    'padding-top', 'padding-right', 'padding-bottom', 'padding-left',
    'margin-top', 'margin-right', 'margin-bottom', 'margin-left',
    'row-gap', 'column-gap', 'border-top-width', 'border-right-width',
    'border-bottom-width', 'border-left-width', 'border-top-left-radius',
    'border-top-right-radius', 'border-bottom-right-radius', 'border-bottom-left-radius',
    'border-top-style', 'border-right-style', 'border-bottom-style', 'border-left-style',
    'opacity', 'box-shadow', 'filter', 'transform'
  ];
  const cleanText = (value) => (value || '').replace(/\\s+/g, ' ').trim();
  const controlMatches = (el) => {
    try { return el.matches(controlSelectors); } catch { return false; }
  };
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
      if (['submit', 'button', 'reset'].includes(type)) return 'button';
      return 'textbox';
    }
    return '';
  };
  const accessibleName = (el) => {
    const aria = el.getAttribute('aria-label');
    if (aria) return cleanText(aria);
    const labelledBy = el.getAttribute('aria-labelledby');
    if (labelledBy) {
      const text = labelledBy.split(/\\s+/).map((id) => document.getElementById(id)?.innerText || '').join(' ');
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
  for (const [index, el] of Array.from(document.querySelectorAll('*')).entries()) {
    const cs = window.getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    const rect = el.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) continue;
    const left = rect.left + window.scrollX;
    const top = rect.top + window.scrollY;
    const style = {};
    for (const prop of styleProps) style[prop] = cs.getPropertyValue(prop);
    const tag = el.tagName.toLowerCase();
    elements.push({
      node_id: `node-${index}`,
      tag,
      role: inferredRole(el),
      type: tag === 'input' ? (el.getAttribute('type') || 'text').toLowerCase() : '',
      id: el.id || '',
      class_name: typeof el.className === 'string' ? el.className : '',
      name: el.getAttribute('name') || '',
      text: cleanText(el.innerText || el.textContent || '').slice(0, 300),
      accessible_name: accessibleName(el).slice(0, 300),
      is_control: controlMatches(el),
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
        width: rect.width,
        height: rect.height,
      },
      style,
    });
  }
  return {
    url: window.location.href,
    title: document.title || '',
    viewport: {
      width: window.innerWidth,
      height: window.innerHeight,
      devicePixelRatio: window.devicePixelRatio,
    },
    document: {
      width: Math.max(document.documentElement.scrollWidth, document.body?.scrollWidth || 0, window.innerWidth),
      height: Math.max(document.documentElement.scrollHeight, document.body?.scrollHeight || 0, window.innerHeight),
    },
    scroll: { x: window.scrollX, y: window.scrollY },
    elements,
    controls: elements.filter((el) => el.is_control),
    element_count: elements.length,
    control_count: elements.filter((el) => el.is_control).length,
  };
}
"""


PAGE_STATE_SCRIPT = """
() => {
  const cleanText = (value) => (value || '').replace(/\\s+/g, ' ').trim();
  const visibleTexts = [];
  for (const el of Array.from(document.querySelectorAll('body *'))) {
    const cs = window.getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || Number(cs.opacity) === 0) continue;
    const rect = el.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) continue;
    const text = cleanText(el.innerText || el.textContent || '');
    if (text) visibleTexts.push(text.slice(0, 240));
  }
  const active = document.activeElement;
  const activeRect = active ? active.getBoundingClientRect() : null;
  return {
    url: window.location.href,
    title: document.title || '',
    visible_text: cleanText(document.body?.innerText || ''),
    visible_texts: Array.from(new Set(visibleTexts)),
    scroll: { x: window.scrollX, y: window.scrollY },
    active: active ? {
      tag: active.tagName.toLowerCase(),
      id: active.id || '',
      class_name: typeof active.className === 'string' ? active.className : '',
      name: active.getAttribute('name') || '',
      type: active.tagName.toLowerCase() === 'input' ? (active.getAttribute('type') || 'text').toLowerCase() : '',
      text: cleanText(active.innerText || active.textContent || ''),
      bbox: activeRect ? { x: activeRect.left + window.scrollX, y: activeRect.top + window.scrollY, width: activeRect.width, height: activeRect.height } : null,
    } : null,
  };
}
"""


ELEMENT_SIGNATURE_SCRIPT = """
({ selector }) => {
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
      if (['submit', 'button', 'reset'].includes(type)) return 'button';
      return 'textbox';
    }
    return '';
  };
  const accessibleName = (el) => {
    const aria = el.getAttribute('aria-label');
    if (aria) return cleanText(aria);
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
  const el = document.querySelector(selector);
  if (!el) return null;
  const cs = window.getComputedStyle(el);
  const rect = el.getBoundingClientRect();
  const tag = el.tagName.toLowerCase();
  return {
    selector,
    tag,
    role: inferredRole(el),
    type: tag === 'input' ? (el.getAttribute('type') || 'text').toLowerCase() : '',
    id: el.id || '',
    class_name: typeof el.className === 'string' ? el.className : '',
    name: el.getAttribute('name') || '',
    text: cleanText(el.innerText || el.textContent || ''),
    accessible_name: accessibleName(el),
    visible: cs.display !== 'none' && cs.visibility !== 'hidden' && Number(cs.opacity) !== 0 && rect.width > 0 && rect.height > 0,
    bbox_px: { x: rect.left + window.scrollX, y: rect.top + window.scrollY, width: rect.width, height: rect.height },
  };
}
"""


CANDIDATE_ELEMENTS_SCRIPT = """
() => {
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
      if (['submit', 'button', 'reset'].includes(type)) return 'button';
      return 'textbox';
    }
    return '';
  };
  const accessibleName = (el) => {
    const aria = el.getAttribute('aria-label');
    if (aria) return cleanText(aria);
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
  return Array.from(document.querySelectorAll('*')).map((el, index) => {
    const nodeId = `wde-${index}`;
    el.setAttribute('data-wde-node-id', nodeId);
    const cs = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    const tag = el.tagName.toLowerCase();
    return {
      selector: `[data-wde-node-id="${nodeId}"]`,
      tag,
      role: inferredRole(el),
      type: tag === 'input' ? (el.getAttribute('type') || 'text').toLowerCase() : '',
      id: el.id || '',
      class_name: typeof el.className === 'string' ? el.className : '',
      name: el.getAttribute('name') || '',
      text: cleanText(el.innerText || el.textContent || ''),
      accessible_name: accessibleName(el),
      visible: cs.display !== 'none' && cs.visibility !== 'hidden' && Number(cs.opacity) !== 0 && rect.width > 0 && rect.height > 0,
      bbox_px: { x: rect.left + window.scrollX, y: rect.top + window.scrollY, width: rect.width, height: rect.height },
    };
  });
}
"""


VISIBLE_ANCESTOR_SCRIPT = """
({ selector }) => {
  const el = document.querySelector(selector);
  if (!el) return null;
  let current = el.parentElement;
  let index = 0;
  while (current) {
    const cs = window.getComputedStyle(current);
    const rect = current.getBoundingClientRect();
    if (cs.display !== 'none' && cs.visibility !== 'hidden' && Number(cs.opacity) !== 0 && rect.width > 0 && rect.height > 0) {
      const nodeId = `wde-ancestor-${Date.now()}-${index}`;
      current.setAttribute('data-wde-node-id', nodeId);
      return {
        selector: `[data-wde-node-id="${nodeId}"]`,
        tag: current.tagName.toLowerCase(),
        id: current.id || '',
        class_name: typeof current.className === 'string' ? current.className : '',
        text: (current.innerText || current.textContent || '').replace(/\\s+/g, ' ').trim(),
        bbox_px: { x: rect.left + window.scrollX, y: rect.top + window.scrollY, width: rect.width, height: rect.height },
      };
    }
    current = current.parentElement;
    index += 1;
  }
  return null;
}
"""


def _load_dotenv(path: Path) -> None:
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


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _enabled_capture(capture: dict[str, Any]) -> bool:
    return capture.get("enabled", True) is not False


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def _text_similarity(reference: str | None, candidate: str | None) -> float:
    ref = _normalize_text(reference)
    cand = _normalize_text(candidate)
    if not ref or not cand:
        return 0.0
    if ref in cand or cand in ref:
        return min(len(ref), len(cand)) / max(len(ref), len(cand))
    return SequenceMatcher(None, ref, cand).ratio()


def _bbox_center_similarity(reference: dict[str, Any] | None, candidate: dict[str, Any] | None) -> float:
    if not reference or not candidate:
        return 0.0
    ref_width = max(float(reference.get("width", 0.0)), 1.0)
    ref_height = max(float(reference.get("height", 0.0)), 1.0)
    cand_width = max(float(candidate.get("width", 0.0)), 1.0)
    cand_height = max(float(candidate.get("height", 0.0)), 1.0)
    ref_x = float(reference.get("x", 0.0)) + ref_width / 2.0
    ref_y = float(reference.get("y", 0.0)) + ref_height / 2.0
    cand_x = float(candidate.get("x", 0.0)) + cand_width / 2.0
    cand_y = float(candidate.get("y", 0.0)) + cand_height / 2.0
    return max(0.0, 1.0 - max(abs(ref_x - cand_x) / 1440.0, abs(ref_y - cand_y) / 900.0))


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(float(sum(values) / len(values)), 6)


def _metric_error(metric: str, exc: BaseException) -> dict[str, Any]:
    return {"error": {"metric": metric, "type": type(exc).__name__, "message": str(exc)}}


def _score_from_dreamsim(distance: float | None) -> float | None:
    if distance is None:
        return None
    return round(max(0.0, min(1.0, 1.0 - float(distance))), 6)


def _screenshot_options(defaults: dict[str, Any], capture: dict[str, Any], path: Path) -> dict[str, Any]:
    screenshot_defaults = defaults.get("screenshot", {})
    capture_screenshot = capture.get("screenshot", {})
    options: dict[str, Any] = {
        "path": str(path),
        "full_page": bool(capture_screenshot.get("fullPage", screenshot_defaults.get("fullPage", False))),
        "animations": capture_screenshot.get("animations", screenshot_defaults.get("animations", "disabled")),
        "caret": capture_screenshot.get("caret", screenshot_defaults.get("caret", "hide")),
    }
    if "clip" in capture_screenshot:
        options["clip"] = capture_screenshot["clip"]
    return options


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args: Any) -> None:
        return


@dataclass
class StaticServer:
    root: Path
    httpd: ThreadingHTTPServer
    thread: threading.Thread
    base_url: str

    @classmethod
    def start(cls, root: Path) -> "StaticServer":
        root = root.resolve()
        handler = partial(_QuietHandler, directory=str(root))
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        host, port = httpd.server_address[:2]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        return cls(root=root, httpd=httpd, thread=thread, base_url=f"http://{host}:{port}")

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)


@dataclass
class EvaluateConfig:
    reference_root: Path
    reference_manifest: Path
    candidate_root: Path
    output_dir: Path
    repo_root: Path
    skip_vlm: bool = False
    skip_dreamsim: bool = False
    vlm_model: str = "gpt-5.4-mini"
    dreamsim_type: str = "ensemble"
    dreamsim_device: str | None = None
    dreamsim_cache_dir: str | None = None
    visual_block_device: str = "cpu"
    include_visual_block: bool = True
    capture_filter: set[str] | None = None


def _route_for_capture(root: Path, capture: dict[str, Any]) -> dict[str, Any]:
    capture_path = capture.get("path") or capture.get("urlPath") or "/index.html"
    relative = capture_path.lstrip("/") or "index.html"
    exact_path = root / relative
    if exact_path.exists():
        return {
            "requested_path": capture_path,
            "resolved_path": "/" + relative.replace(os.sep, "/"),
            "file_path": str(exact_path.resolve()),
            "confidence": 1.0,
            "status": "resolved",
            "method": "exact_path",
            "failure_mode": None,
        }

    page = str(capture.get("page") or "").strip().lower()
    candidates = []
    if page == "home":
        candidates.append(root / "index.html")
    if page:
        candidates.append(root / f"{page}.html")
    candidates.append(root / "index.html")
    for candidate in candidates:
        if candidate.exists():
            return {
                "requested_path": capture_path,
                "resolved_path": "/" + candidate.relative_to(root).as_posix(),
                "file_path": str(candidate.resolve()),
                "confidence": 0.6,
                "status": "resolved",
                "method": "fallback_page_file",
                "failure_mode": "exact_path_missing",
            }

    return {
        "requested_path": capture_path,
        "resolved_path": None,
        "file_path": None,
        "confidence": 0.0,
        "status": "missing",
        "method": None,
        "failure_mode": "no_matching_route_file",
    }


def _capture_viewport(capture: dict[str, Any], manifest: dict[str, Any]) -> dict[str, int]:
    viewport = capture.get("viewport") or manifest.get("defaults", {}).get("viewport") or {}
    return {"width": int(viewport.get("width", 1440)), "height": int(viewport.get("height", 900))}


def _page_state(page: Page) -> dict[str, Any]:
    return page.evaluate(PAGE_STATE_SCRIPT)


def _element_signature(page: Page, selector: str) -> dict[str, Any] | None:
    return page.evaluate(ELEMENT_SIGNATURE_SCRIPT, {"selector": selector})


def _candidate_elements(page: Page) -> list[dict[str, Any]]:
    return page.evaluate(CANDIDATE_ELEMENTS_SCRIPT)


def _visible_ancestor(page: Page, selector: str) -> dict[str, Any] | None:
    return page.evaluate(VISIBLE_ANCESTOR_SCRIPT, {"selector": selector})


def _route_url(base_url: str, resolved_path: str | None) -> str:
    path = resolved_path or "/index.html"
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _goto_capture(
    page: Page,
    base_url: str,
    route: dict[str, Any],
    capture: dict[str, Any],
    defaults: dict[str, Any],
) -> None:
    viewport = capture.get("viewport") or defaults.get("viewport")
    if viewport:
        page.set_viewport_size({"width": int(viewport["width"]), "height": int(viewport["height"])})
    color_scheme = capture.get("colorScheme") or defaults.get("colorScheme")
    if color_scheme:
        page.emulate_media(color_scheme=color_scheme)
    page.goto(
        _route_url(base_url, route.get("resolved_path")),
        wait_until=capture.get("waitUntil") or defaults.get("waitUntil") or "networkidle",
        timeout=int(capture.get("timeoutMs") or defaults.get("timeoutMs") or 30000),
    )
    after_load_wait_ms = int(defaults.get("afterLoadWaitMs") or 0)
    if after_load_wait_ms:
        page.wait_for_timeout(after_load_wait_ms)


def _selector_actionable(page: Page, selector: str, action_type: str) -> bool:
    try:
        if page.locator(selector).count() <= 0:
            return False
        if action_type in {"hover", "click", "focus"}:
            return page.locator(selector).first.is_visible(timeout=250)
        return True
    except Exception:
        return False


def _score_candidate_element(reference: dict[str, Any], candidate: dict[str, Any], action_type: str) -> float:
    ref_text = reference.get("accessible_name") or reference.get("text")
    cand_text = candidate.get("accessible_name") or candidate.get("text")
    text = _text_similarity(ref_text, cand_text)
    tag = 1.0 if reference.get("tag") and reference.get("tag") == candidate.get("tag") else 0.0
    role = 1.0 if reference.get("role") and reference.get("role") == candidate.get("role") else 0.0
    control = 0.0
    if reference.get("type") and reference.get("type") == candidate.get("type"):
        control += 0.45
    if reference.get("name") and reference.get("name") == candidate.get("name"):
        control += 0.35
    if reference.get("id") and reference.get("id") == candidate.get("id"):
        control += 0.20
    bbox = _bbox_center_similarity(reference.get("bbox_px"), candidate.get("bbox_px"))
    weights = (0.48, 0.12, 0.12, 0.18, 0.10)
    score = weights[0] * text + weights[1] * tag + weights[2] * role + weights[3] * min(control, 1.0) + weights[4] * bbox
    if action_type == "scroll":
        if candidate.get("id"):
            score += 0.15
        if candidate.get("tag") in {"section", "main", "article"}:
            score += 0.05
    if action_type in {"click", "focus", "fill"} and reference.get("type") == candidate.get("type") and candidate.get("type"):
        score = 1.0
    return round(float(min(score, 1.0)), 6)


def _resolve_action(page: Page, action: dict[str, Any], reference_signature: dict[str, Any] | None) -> dict[str, Any]:
    selector = action.get("selector")
    action_type = action.get("type", "")
    if selector and _selector_actionable(page, selector, action_type):
        return {
            "status": "resolved",
            "method": "exact_selector",
            "requested_selector": selector,
            "resolved_selector": selector,
            "confidence": 1.0,
            "failure_mode": None,
            "matched_element": None,
        }

    if selector and action_type == "hover":
        ancestor = _visible_ancestor(page, selector)
        if ancestor is not None:
            return {
                "status": "resolved",
                "method": "visible_ancestor_of_exact_selector",
                "requested_selector": selector,
                "resolved_selector": ancestor["selector"],
                "confidence": 1.0,
                "failure_mode": None,
                "matched_element": ancestor,
            }

    if not selector or reference_signature is None:
        return {
            "status": "unsupported",
            "method": None,
            "requested_selector": selector,
            "resolved_selector": None,
            "confidence": 0.0,
            "failure_mode": "selector_missing_or_reference_signature_unavailable",
            "matched_element": None,
        }

    candidates = [
        element
        for element in _candidate_elements(page)
        if element.get("visible") or action_type == "scroll"
    ]
    scored = [
        (_score_candidate_element(reference_signature, candidate, action_type), candidate)
        for candidate in candidates
    ]
    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored:
        return {
            "status": "unsupported",
            "method": "element_match",
            "requested_selector": selector,
            "resolved_selector": None,
            "confidence": 0.0,
            "failure_mode": "no_candidate_elements",
            "matched_element": None,
        }
    best_score, best_element = scored[0]
    threshold = 0.25 if action_type == "scroll" else 0.3 if action_type == "hover" else 0.45
    if best_score < threshold:
        return {
            "status": "unsupported",
            "method": "element_match",
            "requested_selector": selector,
            "resolved_selector": None,
            "confidence": best_score,
            "failure_mode": "no_candidate_element_above_threshold",
            "matched_element": best_element,
        }
    return {
        "status": "resolved",
        "method": "element_match",
        "requested_selector": selector,
        "resolved_selector": best_element["selector"],
        "confidence": best_score,
        "failure_mode": None,
        "matched_element": best_element,
    }


def _run_action(page: Page, action: dict[str, Any], selector: str | None = None) -> None:
    action_type = action.get("type")
    resolved_selector = selector or action.get("selector")
    settle_ms = int(action.get("settleMs") or 0)

    if action_type == "hover":
        page.locator(resolved_selector).first.hover(timeout=3000)
    elif action_type == "click":
        page.locator(resolved_selector).first.click(timeout=3000)
    elif action_type == "focus":
        page.locator(resolved_selector).first.focus(timeout=3000)
    elif action_type == "fill":
        page.locator(resolved_selector).first.fill(str(action.get("value") or ""), timeout=3000)
    elif action_type == "press":
        page.keyboard.press(str(action.get("key")))
    elif action_type == "wait":
        page.wait_for_timeout(int(action.get("ms") or 0))
    elif action_type == "waitForSelector":
        page.locator(resolved_selector).first.wait_for(
            state=action.get("state") or "visible",
            timeout=int(action.get("timeoutMs") or 3000),
        )
    elif action_type == "scroll":
        if resolved_selector:
            page.locator(resolved_selector).first.scroll_into_view_if_needed(timeout=3000)
        else:
            page.evaluate(
                "({ x, y }) => window.scrollTo(x || 0, y || 0)",
                {"x": action.get("x", 0), "y": action.get("y", 0)},
            )
    elif action_type == "scrollBy":
        page.evaluate(
            "({ x, y }) => window.scrollBy(x || 0, y || 0)",
            {"x": action.get("x", 0), "y": action.get("y", 0)},
        )
    else:
        raise ValueError(f"Unknown action type: {action_type}")

    if settle_ms:
        page.wait_for_timeout(settle_ms)


def _visible_text_delta(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    before_texts = {_normalize_text(text) for text in before.get("visible_texts", [])}
    delta = []
    for text in after.get("visible_texts", []):
        normalized = _normalize_text(text)
        if len(normalized) >= 3 and normalized not in before_texts:
            delta.append(text)
    return delta[:20]


def _validate_post_state(
    action: dict[str, Any],
    reference_before: dict[str, Any],
    reference_after: dict[str, Any],
    candidate_before: dict[str, Any],
    candidate_after: dict[str, Any],
) -> dict[str, Any]:
    action_type = action.get("type")
    expected_texts = _visible_text_delta(reference_before, reference_after)
    candidate_text = _normalize_text(candidate_after.get("visible_text", ""))
    matched_texts = [
        text
        for text in expected_texts
        if _normalize_text(text) and _normalize_text(text) in candidate_text
    ]

    if action_type == "scroll":
        reference_scroll_delta = abs(float(reference_after["scroll"]["y"]) - float(reference_before["scroll"]["y"]))
        candidate_scroll_delta = abs(float(candidate_after["scroll"]["y"]) - float(candidate_before["scroll"]["y"]))
        expected_scroll = reference_scroll_delta > 8
        score = 1.0 if not expected_scroll or candidate_scroll_delta > 8 else 0.0
        return {
            "score": score,
            "checks": {
                "reference_scroll_delta": round(reference_scroll_delta, 3),
                "candidate_scroll_delta": round(candidate_scroll_delta, 3),
                "expected_scroll": expected_scroll,
            },
        }

    if action_type in {"click", "focus", "fill"}:
        reference_active = reference_after.get("active") or {}
        candidate_active = candidate_after.get("active") or {}
        if reference_active.get("type"):
            score = 1.0 if reference_active.get("type") == candidate_active.get("type") else 0.0
        else:
            score = 1.0 if candidate_active else 0.0
        return {
            "score": score,
            "checks": {
                "reference_active": reference_active,
                "candidate_active": candidate_active,
            },
        }

    if expected_texts:
        score = len(matched_texts) / len(expected_texts)
        return {
            "score": round(float(score), 6),
            "checks": {
                "expected_visible_texts": expected_texts,
                "matched_visible_texts": matched_texts,
            },
        }

    return {"score": 1.0, "checks": {"reason": "no_reference_postcondition_detected"}}


def _execute_reference_actions(page: Page, capture: dict[str, Any]) -> list[dict[str, Any]]:
    executed = []
    for action in capture.get("actions") or []:
        before = _page_state(page)
        signature = _element_signature(page, action["selector"]) if action.get("selector") else None
        status = "resolved"
        failure = None
        try:
            _run_action(page, action)
        except Exception as exc:
            status = "failed"
            failure = f"{type(exc).__name__}: {exc}"
        after = _page_state(page)
        executed.append(
            {
                "action": action,
                "status": status,
                "failure": failure,
                "reference_signature": signature,
                "before_state": before,
                "after_state": after,
                "visible_text_delta": _visible_text_delta(before, after),
            }
        )
    return executed


def _execute_candidate_actions(page: Page, reference_actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    executed = []
    for reference_action in reference_actions:
        action = reference_action["action"]
        before = _page_state(page)
        resolution = _resolve_action(page, action, reference_action.get("reference_signature"))
        action_status = "skipped"
        failure = None
        post_state = {"score": 0.0, "checks": {"reason": "action_not_resolved"}}
        after = before

        if resolution["status"] == "resolved":
            try:
                _run_action(page, action, selector=resolution.get("resolved_selector"))
                after = _page_state(page)
                post_state = _validate_post_state(
                    action,
                    reference_action["before_state"],
                    reference_action["after_state"],
                    before,
                    after,
                )
                action_status = "completed" if post_state["score"] > 0 else "post_state_failed"
            except Exception as exc:
                failure = f"{type(exc).__name__}: {exc}"
                action_status = "failed"

        coverage = round(float(resolution.get("confidence", 0.0)) * float(post_state.get("score", 0.0)), 6)
        executed.append(
            {
                "action": action,
                "resolution": resolution,
                "status": action_status,
                "failure": failure,
                "post_state": post_state,
                "coverage_contribution": coverage,
                "before_state": before,
                "after_state": after,
            }
        )
    return executed


def _artifact_cssom(page: Page) -> dict[str, Any]:
    snapshot = page.evaluate(CSSOM_ARTIFACT_SCRIPT, {"controlSelectors": CONTROL_SELECTORS})
    return snapshot


def _artifact_from_page(
    page: Page,
    capture: dict[str, Any],
    defaults: dict[str, Any],
    artifact_dir: Path,
    actions: list[dict[str, Any]],
    *,
    side: str,
) -> dict[str, Any]:
    screenshot_dir = artifact_dir / "screenshots"
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = screenshot_dir / f"{capture['id']}.png"
    page.screenshot(**_screenshot_options(defaults, capture, screenshot_path))
    with Image.open(screenshot_path) as image:
        screenshot_dimensions = {"width": image.width, "height": image.height}
    outer_html = page.evaluate("() => document.documentElement.outerHTML")
    cssom = _artifact_cssom(page)
    artifact = {
        "capture_id": capture["id"],
        "side": side,
        "page": capture.get("page"),
        "state": capture.get("state"),
        "viewport": _capture_viewport(capture, {"defaults": defaults}),
        "actions": actions,
        "screenshot_path": str(screenshot_path),
        "screenshot_dimensions": screenshot_dimensions,
        "outer_html": outer_html,
        "cssom": cssom,
        "extraction_errors": [],
        "missing_reason": None,
    }
    _write_json(artifact_dir / f"{capture['id']}.json", artifact)
    return artifact


def _missing_artifact(
    capture: dict[str, Any],
    artifact_dir: Path,
    *,
    side: str,
    reason: str,
    route: dict[str, Any] | None = None,
) -> dict[str, Any]:
    artifact = {
        "capture_id": capture["id"],
        "side": side,
        "page": capture.get("page"),
        "state": capture.get("state"),
        "viewport": capture.get("viewport"),
        "actions": [],
        "route": route,
        "screenshot_path": None,
        "screenshot_dimensions": None,
        "outer_html": None,
        "cssom": None,
        "extraction_errors": [],
        "missing_reason": reason,
    }
    _write_json(artifact_dir / f"{capture['id']}.json", artifact)
    return artifact


def _capture_reference(
    browser: Browser,
    base_url: str,
    capture: dict[str, Any],
    manifest: dict[str, Any],
    route: dict[str, Any],
    artifact_dir: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    defaults = manifest.get("defaults", {})
    context = browser.new_context(device_scale_factor=defaults.get("deviceScaleFactor", 1))
    page = context.new_page()
    try:
        _goto_capture(page, base_url, route, capture, defaults)
        reference_actions = _execute_reference_actions(page, capture)
        artifact = _artifact_from_page(page, capture, defaults, artifact_dir, reference_actions, side="reference")
        artifact["route"] = route
        _write_json(artifact_dir / f"{capture['id']}.json", artifact)
        return artifact, reference_actions
    finally:
        context.close()


def _capture_candidate(
    browser: Browser,
    base_url: str,
    capture: dict[str, Any],
    manifest: dict[str, Any],
    route: dict[str, Any],
    reference_actions: list[dict[str, Any]],
    artifact_dir: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    defaults = manifest.get("defaults", {})
    context = browser.new_context(device_scale_factor=defaults.get("deviceScaleFactor", 1))
    page = context.new_page()
    try:
        _goto_capture(page, base_url, route, capture, defaults)
        candidate_actions = _execute_candidate_actions(page, reference_actions)
        artifact = _artifact_from_page(page, capture, defaults, artifact_dir, candidate_actions, side="candidate")
        artifact["route"] = route
        _write_json(artifact_dir / f"{capture['id']}.json", artifact)
        return artifact, candidate_actions
    finally:
        context.close()


def _capture_coverage(route: dict[str, Any], actions: list[dict[str, Any]], screenshot_path: str | None) -> dict[str, Any]:
    if route.get("status") != "resolved" or not screenshot_path:
        return {
            "score": 0.0,
            "route_score": float(route.get("confidence", 0.0)),
            "action_score": 0.0,
            "reason": route.get("failure_mode") or "screenshot_missing",
        }
    route_score = float(route.get("confidence", 0.0))
    if not actions:
        return {"score": route_score, "route_score": route_score, "action_score": None, "reason": None}
    action_values = [float(action.get("coverage_contribution", 0.0)) for action in actions]
    action_score = sum(action_values) / len(action_values)
    return {
        "score": round(route_score * action_score, 6),
        "route_score": round(route_score, 6),
        "action_score": round(action_score, 6),
        "reason": None if action_score > 0 else "action_or_post_state_failed",
    }


def _run_pair_metrics(
    reference_artifact: dict[str, Any],
    candidate_artifact: dict[str, Any],
    reference_route: dict[str, Any],
    candidate_route: dict[str, Any],
    config: EvaluateConfig,
) -> dict[str, Any]:
    reference_screenshot = reference_artifact.get("screenshot_path")
    candidate_screenshot = candidate_artifact.get("screenshot_path")
    if not reference_screenshot or not candidate_screenshot:
        return {
            "status": "missing",
            "reason": candidate_artifact.get("missing_reason") or reference_artifact.get("missing_reason"),
        }

    pair: dict[str, Any] = {
        "status": "scored",
        "reference_screenshot": reference_screenshot,
        "candidate_screenshot": candidate_screenshot,
        "screenshot_size_match": screenshot_size_match_score(reference_screenshot, candidate_screenshot),
        "reference_render_sanity": render_sanity_score(reference_screenshot),
        "candidate_render_sanity": render_sanity_score(candidate_screenshot),
    }
    reference_html = reference_artifact.get("outer_html")
    candidate_html = candidate_artifact.get("outer_html")
    if reference_html and candidate_html:
        try:
            pair["html_text"] = {
                **webcode2m_text_score(reference_html, candidate_html),
                "artifact_source": "rendered_outer_html",
            }
        except Exception as exc:
            pair["html_text"] = _metric_error("html_text", exc)
        try:
            pair["html_tree"] = {
                **webcode2m_dom_score(reference_html, candidate_html),
                "artifact_source": "rendered_outer_html",
            }
        except Exception as exc:
            pair["html_tree"] = _metric_error("html_tree", exc)
    else:
        pair["html_text"] = {"unsupported": True, "reason": "rendered_outer_html_missing"}
        pair["html_tree"] = {"unsupported": True, "reason": "rendered_outer_html_missing"}

    if config.skip_dreamsim:
        pair["dreamsim"] = {"skipped": True, "reason": "--skip-dreamsim"}
    else:
        try:
            distance = dreamsim_distance(
                reference_screenshot,
                candidate_screenshot,
                device=config.dreamsim_device,
                dreamsim_type=config.dreamsim_type,
                cache_dir=config.dreamsim_cache_dir,
            )
            pair["dreamsim"] = {
                "distance": distance,
                "score": _score_from_dreamsim(distance),
                "dreamsim_type": config.dreamsim_type,
                "device": _pick_torch_device(config.dreamsim_device),
            }
        except Exception as exc:
            pair["dreamsim"] = _metric_error("dreamsim", exc)

    if config.skip_vlm:
        pair["vlm_judge"] = {"skipped": True, "reason": "--skip-vlm"}
    elif not os.environ.get("OPENAI_API_KEY"):
        pair["vlm_judge"] = {"skipped": True, "reason": "OPENAI_API_KEY unavailable"}
    else:
        try:
            pair["vlm_judge"] = vlm_judge_score(reference_screenshot, candidate_screenshot, model=config.vlm_model)
        except Exception as exc:
            pair["vlm_judge"] = _metric_error("vlm_judge", exc)

    if config.include_visual_block:
        reference_html_path = reference_route.get("file_path")
        candidate_html_path = candidate_route.get("file_path")
        if reference_html_path and candidate_html_path:
            try:
                visual = visual_block_score(
                    reference_html_path,
                    candidate_html_path,
                    reference_screenshot,
                    candidate_screenshot,
                    device=config.visual_block_device,
                    include_pairs=True,
                    include_block_pixelmatch=False,
                )
                pair["visual_block"] = visual
                pair["bbox_geometry"] = {
                    **_score_bbox_geometry(
                        visual.get("matched_pairs", []),
                        coverage_score=float(visual.get("size", 0.0)),
                    ),
                    "visual_block": {
                        key: visual.get(key)
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
                try:
                    viewport = reference_artifact.get("viewport")
                    viewport_tuple = None
                    if isinstance(viewport, dict):
                        viewport_tuple = (int(viewport["width"]), int(viewport["height"]))
                    pair["cssom_block_style"] = cssom_block_style_score(
                        reference_html_path,
                        candidate_html_path,
                        reference_screenshot,
                        candidate_screenshot,
                        device=config.visual_block_device,
                        viewport=viewport_tuple,
                        visual_block_result=visual,
                    )
                except Exception as exc:
                    pair["cssom_block_style"] = _metric_error("cssom_block_style", exc)
            except Exception as exc:
                pair["visual_block"] = _metric_error("visual_block", exc)
                pair["bbox_geometry"] = {"unsupported": True, "reason": "visual_block_failed"}
                pair["cssom_block_style"] = {"unsupported": True, "reason": "visual_block_failed"}
        else:
            pair["visual_block"] = {"unsupported": True, "reason": "route_file_missing"}
            pair["bbox_geometry"] = {"unsupported": True, "reason": "route_file_missing"}
            pair["cssom_block_style"] = {"unsupported": True, "reason": "route_file_missing"}
    else:
        pair["visual_block"] = {"unsupported": True, "reason": "visual block disabled"}
        pair["bbox_geometry"] = {"unsupported": True, "reason": "visual block disabled"}
        pair["cssom_block_style"] = {"unsupported": True, "reason": "visual block disabled"}
    return pair


def _md_table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return "_No rows._\n"
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_md_cell(value) for value in row) + " |")
    return "\n".join(lines) + "\n"


def _md_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6f}".rstrip("0").rstrip(".")
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    return str(value).replace("|", "\\|").replace("\n", " ")


def _get_metric(payload: dict[str, Any], path: list[str]) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _build_report(result: dict[str, Any]) -> str:
    rows = []
    for capture_id, capture in result["captures"].items():
        metrics = capture.get("metrics", {})
        coverage = capture.get("coverage", {})
        rows.append(
            [
                capture_id,
                coverage.get("score"),
                coverage.get("route_score"),
                coverage.get("action_score"),
                _get_metric(metrics, ["screenshot_size_match", "score"]),
                _get_metric(metrics, ["dreamsim", "distance"]),
                _get_metric(metrics, ["dreamsim", "score"]),
                _get_metric(metrics, ["vlm_judge", "overall"]),
                _get_metric(metrics, ["html_text", "bleu_1"]),
                _get_metric(metrics, ["html_text", "rouge_1_recall"]),
                _get_metric(metrics, ["html_tree", "f1"]),
                _get_metric(metrics, ["visual_block", "score"]),
                _get_metric(metrics, ["bbox_geometry", "score"]),
                _get_metric(metrics, ["cssom_block_style", "score"]),
                capture.get("missing_reason") or coverage.get("reason"),
            ]
        )
    summary = result["summary"]
    return "\n".join(
        [
            "# Functional Evaluation Report",
            "",
            f"Generated at: `{result['metadata']['generated_at']}`",
            "",
            "## Summary",
            "",
            _md_table(
                ["Key", "Value"],
                [
                    ["reference_root", result["metadata"]["reference_root"]],
                    ["candidate_root", result["metadata"]["candidate_root"]],
                    ["captures", summary["capture_count"]],
                    ["covered_captures", summary["covered_capture_count"]],
                    ["missing_captures", summary["missing_capture_count"]],
                    ["manifest_coverage_score", summary["manifest_coverage_score"]],
                    ["mean_size_match", summary.get("mean_screenshot_size_match")],
                    ["mean_dreamsim_score", summary.get("mean_dreamsim_score")],
                    ["mean_vlm_overall", summary.get("mean_vlm_overall")],
                    ["mean_html_text_bleu_1", summary.get("mean_html_text_bleu_1")],
                    ["mean_html_text_rouge_1_recall", summary.get("mean_html_text_rouge_1_recall")],
                    ["mean_html_tree_f1", summary.get("mean_html_tree_f1")],
                    ["mean_visual_block_score", summary.get("mean_visual_block_score")],
                ],
            ),
            "## Captures",
            "",
            _md_table(
                [
                    "Capture",
                    "Coverage",
                    "Route",
                    "Action",
                    "Size",
                    "Dream Dist",
                    "Dream Score",
                    "VLM",
                    "Text BLEU",
                    "Text Rouge",
                    "Tree F1",
                    "VB",
                    "BBox",
                    "CSSOM",
                    "Reason",
                ],
                rows,
            ),
        ]
    )


def _summarize(result: dict[str, Any]) -> dict[str, Any]:
    captures = result["captures"]
    coverage_scores = [
        float(capture["coverage"]["score"])
        for capture in captures.values()
        if isinstance(capture.get("coverage"), dict)
    ]
    scored_metrics = [capture.get("metrics", {}) for capture in captures.values()]
    size_scores = [_get_metric(metric, ["screenshot_size_match", "score"]) for metric in scored_metrics]
    dream_scores = [_get_metric(metric, ["dreamsim", "score"]) for metric in scored_metrics]
    vlm_scores = [_get_metric(metric, ["vlm_judge", "overall"]) for metric in scored_metrics]
    html_text_bleu_scores = [_get_metric(metric, ["html_text", "bleu_1"]) for metric in scored_metrics]
    html_text_rouge_scores = [_get_metric(metric, ["html_text", "rouge_1_recall"]) for metric in scored_metrics]
    html_tree_f1_scores = [_get_metric(metric, ["html_tree", "f1"]) for metric in scored_metrics]
    visual_scores = [_get_metric(metric, ["visual_block", "score"]) for metric in scored_metrics]

    def numeric(values: list[Any]) -> list[float]:
        return [float(value) for value in values if isinstance(value, int | float)]

    return {
        "capture_count": len(captures),
        "covered_capture_count": sum(1 for score in coverage_scores if score > 0),
        "missing_capture_count": sum(1 for score in coverage_scores if score <= 0),
        "manifest_coverage_score": _mean(coverage_scores) or 0.0,
        "mean_screenshot_size_match": _mean(numeric(size_scores)),
        "mean_dreamsim_score": _mean(numeric(dream_scores)),
        "mean_vlm_overall": _mean(numeric(vlm_scores)),
        "mean_html_text_bleu_1": _mean(numeric(html_text_bleu_scores)),
        "mean_html_text_rouge_1_recall": _mean(numeric(html_text_rouge_scores)),
        "mean_html_tree_f1": _mean(numeric(html_tree_f1_scores)),
        "mean_visual_block_score": _mean(numeric(visual_scores)),
    }


def evaluate(config: EvaluateConfig) -> dict[str, Any]:
    _load_dotenv(config.repo_root / ".env")
    if config.dreamsim_cache_dir is None:
        config.dreamsim_cache_dir = str(config.repo_root / ".cache" / "dreamsim")
    config.output_dir.mkdir(parents=True, exist_ok=True)
    reference_manifest = _read_json(config.reference_manifest)
    captures = [
        capture
        for capture in reference_manifest.get("captures", [])
        if _enabled_capture(capture) and (not config.capture_filter or capture["id"] in config.capture_filter)
    ]

    from playwright.sync_api import sync_playwright

    started = time.time()
    reference_server = StaticServer.start(config.reference_root)
    candidate_server = StaticServer.start(config.candidate_root)
    candidate_plan: dict[str, Any] = {
        "reference_root": str(config.reference_root),
        "candidate_root": str(config.candidate_root),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "captures": {},
    }
    result: dict[str, Any] = {
        "metadata": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "reference_root": str(config.reference_root),
            "reference_manifest": str(config.reference_manifest),
            "candidate_root": str(config.candidate_root),
            "output_dir": str(config.output_dir),
            "vlm_model": config.vlm_model,
            "vlm_enabled": not config.skip_vlm and bool(os.environ.get("OPENAI_API_KEY")),
            "dreamsim_type": config.dreamsim_type,
            "dreamsim_device": _pick_torch_device(config.dreamsim_device),
            "visual_block_device": config.visual_block_device,
        },
        "captures": {},
    }

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for capture in captures:
                    capture_id = capture["id"]
                    reference_route = _route_for_capture(config.reference_root, capture)
                    candidate_route = _route_for_capture(config.candidate_root, capture)
                    reference_artifact_dir = config.output_dir / "artifacts" / "reference"
                    candidate_artifact_dir = config.output_dir / "artifacts" / "candidate"

                    if reference_route["status"] != "resolved":
                        reference_artifact = _missing_artifact(
                            capture,
                            reference_artifact_dir,
                            side="reference",
                            reason=reference_route["failure_mode"] or "reference_route_missing",
                            route=reference_route,
                        )
                        reference_actions: list[dict[str, Any]] = []
                    else:
                        reference_artifact, reference_actions = _capture_reference(
                            browser,
                            reference_server.base_url,
                            capture,
                            reference_manifest,
                            reference_route,
                            reference_artifact_dir,
                        )

                    if candidate_route["status"] != "resolved":
                        candidate_artifact = _missing_artifact(
                            capture,
                            candidate_artifact_dir,
                            side="candidate",
                            reason=candidate_route["failure_mode"] or "candidate_route_missing",
                            route=candidate_route,
                        )
                        candidate_actions: list[dict[str, Any]] = []
                    else:
                        try:
                            candidate_artifact, candidate_actions = _capture_candidate(
                                browser,
                                candidate_server.base_url,
                                capture,
                                reference_manifest,
                                candidate_route,
                                reference_actions,
                                candidate_artifact_dir,
                            )
                        except Exception as exc:
                            candidate_artifact = _missing_artifact(
                                capture,
                                candidate_artifact_dir,
                                side="candidate",
                                reason=f"candidate_capture_failed: {type(exc).__name__}: {exc}",
                                route=candidate_route,
                            )
                            candidate_actions = []

                    coverage = _capture_coverage(
                        candidate_route,
                        candidate_actions,
                        candidate_artifact.get("screenshot_path"),
                    )
                    candidate_plan["captures"][capture_id] = {
                        "capture": capture,
                        "route_resolution": candidate_route,
                        "actions": candidate_actions,
                        "coverage": coverage,
                    }
                    result["captures"][capture_id] = {
                        "capture": capture,
                        "reference_artifact": str(reference_artifact_dir / f"{capture_id}.json"),
                        "candidate_artifact": str(candidate_artifact_dir / f"{capture_id}.json"),
                        "reference_route": reference_route,
                        "candidate_route": candidate_route,
                        "coverage": coverage,
                        "metrics": {"status": "pending"},
                        "missing_reason": candidate_artifact.get("missing_reason") or reference_artifact.get("missing_reason"),
                    }
            finally:
                browser.close()
    finally:
        reference_server.close()
        candidate_server.close()

    for capture_payload in result["captures"].values():
        reference_artifact = _read_json(Path(capture_payload["reference_artifact"]))
        candidate_artifact = _read_json(Path(capture_payload["candidate_artifact"]))
        coverage = capture_payload["coverage"]
        if coverage["score"] <= 0:
            capture_payload["metrics"] = {
                "status": "unsupported",
                "reason": coverage.get("reason") or candidate_artifact.get("missing_reason"),
                "reference_screenshot": reference_artifact.get("screenshot_path"),
                "candidate_screenshot": candidate_artifact.get("screenshot_path"),
            }
        else:
            capture_payload["metrics"] = _run_pair_metrics(
                reference_artifact,
                candidate_artifact,
                capture_payload["reference_route"],
                capture_payload["candidate_route"],
                config,
            )

    result["summary"] = _summarize(result)
    result["metadata"]["elapsed_seconds"] = round(time.time() - started, 3)

    _write_json(config.output_dir / "candidate-capture-plan.json", candidate_plan)
    _write_json(config.output_dir / "metrics.json", result)
    (config.output_dir / "functional-report.md").write_text(_build_report(result), encoding="utf-8")
    return result


def print_functional_status(result: dict[str, Any]) -> None:
    summary = result["summary"]
    payload = {
        "status": "functional",
        "captures": summary["capture_count"],
        "covered_captures": summary["covered_capture_count"],
        "missing_captures": summary["missing_capture_count"],
        "manifest_coverage_score": summary["manifest_coverage_score"],
        "mean_screenshot_size_match": summary.get("mean_screenshot_size_match"),
        "mean_dreamsim_score": summary.get("mean_dreamsim_score"),
        "mean_vlm_overall": summary.get("mean_vlm_overall"),
        "mean_html_text_bleu_1": summary.get("mean_html_text_bleu_1"),
        "mean_html_text_rouge_1_recall": summary.get("mean_html_text_rouge_1_recall"),
        "mean_html_tree_f1": summary.get("mean_html_tree_f1"),
        "mean_visual_block_score": summary.get("mean_visual_block_score"),
        "output_dir": result["metadata"]["output_dir"],
        "metrics": str(Path(result["metadata"]["output_dir"]) / "metrics.json"),
        "report": str(Path(result["metadata"]["output_dir"]) / "functional-report.md"),
        "candidate_capture_plan": str(Path(result["metadata"]["output_dir"]) / "candidate-capture-plan.json"),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
