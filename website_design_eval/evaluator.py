from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from PIL import Image
from playwright.async_api import Browser as AsyncBrowser
from playwright.async_api import Page as AsyncPage
from playwright.async_api import async_playwright
from playwright.sync_api import Browser, Page

from .block_visual import (
    _score_bbox_geometry,
    extract_visual_blocks_from_async_playwright_page,
    extract_visual_blocks_from_playwright_page,
    visual_block_match_from_blocks,
)
from .candidate_planner import generate_candidate_manifest
from .cssom import _color_similarity
from .scoring import (
    _pick_torch_device,
    cssom_block_style_score_from_snapshots,
    dreamsim_distance,
    pixelmatch_score,
    render_sanity_score,
    screenshot_size_match_score,
    vlm_judge_score,
    webcode2m_dom_score,
    webcode2m_text_score,
)
from .static_server import StaticServer, normalize_serve_mode

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
({ controlSelectors, normalizeWidth, normalizeHeight, screenshotWidth, screenshotHeight }) => {
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
      bbox: [
        left / normalizeWidth,
        top / normalizeHeight,
        rect.width / normalizeWidth,
        rect.height / normalizeHeight,
      ],
      style,
    });
  }
  return {
    url: window.location.pathname + window.location.search + window.location.hash,
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
    screenshot: {
      width: screenshotWidth,
      height: screenshotHeight,
    },
    normalize_size: {
      width: normalizeWidth,
      height: normalizeHeight,
    },
    scroll: { x: window.scrollX, y: window.scrollY },
    coordinate_space: {
      bbox_px: "document_px",
      bbox: "normalized_document_to_screenshot",
      note: "bbox_px is document-space pixels; bbox is normalized by screenshot width/height for full-page visual-block matching.",
    },
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
    url: window.location.pathname + window.location.search + window.location.hash,
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
      const nodeId = `wde-visible-ancestor-${index}`;
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


REMOVE_EVALUATOR_ATTRIBUTES_SCRIPT = """
() => {
  for (const el of Array.from(document.querySelectorAll('[data-wde-node-id]'))) {
    el.removeAttribute('data-wde-node-id');
  }
  for (const el of Array.from(document.querySelectorAll('[data-wde-manifest-id]'))) {
    el.removeAttribute('data-wde-manifest-id');
  }
}
"""


STAMP_MANIFEST_ELEMENTS_SCRIPT = """
() => {
  const stampAttr = 'data-wde-manifest-id';
  const cleanText = (value) => (value || '').replace(/\\s+/g, ' ').trim();
  const cssEscape = (value) => window.CSS && CSS.escape
    ? CSS.escape(value)
    : String(value).replace(/[^a-zA-Z0-9_-]/g, '\\\\$&');
  const slug = (value) => cleanText(value).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 48) || 'element';
  const accessibleName = (el) => {
    const aria = el.getAttribute('aria-label');
    if (aria) return cleanText(aria);
    const labelledBy = el.getAttribute('aria-labelledby');
    if (labelledBy) {
      const text = labelledBy.split(/\\s+/).map((id) => document.getElementById(id)?.innerText || '').join(' ');
      if (cleanText(text)) return cleanText(text);
    }
    if (el.id) {
      const label = document.querySelector(`label[for="${cssEscape(el.id)}"]`);
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

  Array.from(document.querySelectorAll('*')).forEach((el, index) => {
    if (el.hasAttribute(stampAttr)) return;
    const tag = el.tagName.toLowerCase();
    const label = accessibleName(el) || el.id || el.getAttribute('name') || tag;
    el.setAttribute(stampAttr, `wde-${index}-${tag}-${slug(label)}`);
  });
}
"""


ANIMATION_SAMPLE_SCRIPT = """
({ selector, track }) => {
  const el = document.querySelector(selector);
  if (!el) return null;
  const cs = window.getComputedStyle(el);
  const rect = el.getBoundingClientRect();
  const style = {};
  for (const prop of track || []) style[prop] = cs.getPropertyValue(prop);
  return {
    selector,
    bbox_px: {
      x: rect.left,
      y: rect.top,
      width: rect.width,
      height: rect.height
    },
    visible: cs.display !== 'none' && cs.visibility !== 'hidden' && Number(cs.opacity) !== 0 && rect.width > 0 && rect.height > 0,
    style
  };
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


@dataclass
class EvaluateConfig:
    reference_root: Path
    reference_manifest: Path
    candidate_root: Path
    output_dir: Path
    repo_root: Path
    candidate_framework: str = "html"
    candidate_serve_mode: str = "static"
    skip_vlm: bool = False
    skip_dreamsim: bool = False
    vlm_model: str = "gpt-5.4-mini"
    dreamsim_type: str = "ensemble"
    dreamsim_device: str | None = None
    dreamsim_cache_dir: str | None = None
    visual_block_device: str = "cpu"
    include_visual_block: bool = True
    capture_filter: set[str] | None = None
    candidate_manifest: Path | None = None
    candidate_manifest_planner: str | None = None
    candidate_manifest_model: str = "opus"
    candidate_manifest_claude_auth: str = "api"
    capture_concurrency: int = 4
    vlm_concurrency: int = 4


_PROGRESS_LOCK = threading.Lock()


def _progress(config: EvaluateConfig, event: str, **fields: Any) -> None:
    payload = {
        "ts": datetime.now().isoformat(timespec="milliseconds"),
        "event": event,
        **fields,
    }
    line = json.dumps(payload, sort_keys=True)
    print(f"[wde-progress] {line}", flush=True)
    try:
        config.output_dir.mkdir(parents=True, exist_ok=True)
        with _PROGRESS_LOCK:
            with (config.output_dir / "progress.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
    except Exception:
        pass


class _ProgressTimer:
    def __init__(self, config: EvaluateConfig, event: str, **fields: Any):
        self.config = config
        self.event = event
        self.fields = fields
        self.started = 0.0

    def __enter__(self) -> "_ProgressTimer":
        self.started = time.time()
        _progress(self.config, f"{self.event}_start", **self.fields)
        return self

    def __exit__(self, exc_type: Any, exc: Any, _tb: Any) -> None:
        payload = {**self.fields, "elapsed_seconds": round(time.time() - self.started, 3)}
        if exc is not None:
            payload["error"] = f"{exc_type.__name__}: {exc}" if exc_type else str(exc)
            _progress(self.config, f"{self.event}_error", **payload)
        else:
            _progress(self.config, f"{self.event}_end", **payload)


def _route_for_capture(
    root: Path,
    capture: dict[str, Any],
    *,
    route_inventory: list[dict[str, Any]] | None = None,
    serve_mode: str = "static",
    candidate_manifest_mapped: bool = False,
) -> dict[str, Any]:
    serve_mode = normalize_serve_mode(serve_mode)
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
            "serve_mode": serve_mode,
            "route_resolution_coverage": 1.0,
        }

    if serve_mode == "spa":
        index_path = root / "index.html"
        if index_path.exists():
            route_confidence = 1.0 if candidate_manifest_mapped else 0.75
            return {
                "requested_path": capture_path,
                "resolved_path": capture_path if str(capture_path).startswith("/") else f"/{capture_path}",
                "file_path": str(index_path.resolve()),
                "confidence": route_confidence,
                "status": "resolved",
                "method": "spa_manifest_path" if candidate_manifest_mapped else "spa_fallback",
                "failure_mode": None if candidate_manifest_mapped else "exact_path_missing_spa_fallback",
                "serve_mode": serve_mode,
                "route_resolution_coverage": route_confidence,
            }
        return {
            "requested_path": capture_path,
            "resolved_path": None,
            "file_path": None,
            "confidence": 0.0,
            "status": "missing",
            "method": "spa_fallback",
            "failure_mode": "spa_index_missing",
            "serve_mode": serve_mode,
            "route_resolution_coverage": 0.0,
        }

    if route_inventory:
        semantic_route = _semantic_route_for_capture(capture, route_inventory)
        if semantic_route:
            semantic_route["serve_mode"] = serve_mode
            semantic_route["route_resolution_coverage"] = semantic_route.get("confidence", 0.0)
            return semantic_route

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
                "serve_mode": serve_mode,
                "route_resolution_coverage": 0.6,
            }

    return {
        "requested_path": capture_path,
        "resolved_path": None,
        "file_path": None,
        "confidence": 0.0,
        "status": "missing",
        "method": None,
        "failure_mode": "no_matching_route_file",
        "serve_mode": serve_mode,
        "route_resolution_coverage": 0.0,
    }


_ROUTE_STOPWORDS = {
    "a",
    "an",
    "and",
    "archive",
    "capture",
    "default",
    "desktop",
    "for",
    "full",
    "html",
    "index",
    "is",
    "it",
    "of",
    "page",
    "selected",
    "state",
    "the",
    "this",
    "to",
    "we",
    "with",
    "you",
}


def _route_tokens(value: Any) -> set[str]:
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(value or ""))
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 1 and token not in _ROUTE_STOPWORDS
    }


def _route_inventory(root: Path) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    for html_path in sorted(root.glob("*.html")):
        try:
            html = html_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        title = ""
        headings: list[str] = []
        nav_text = ""
        body_text = ""
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "html.parser")
            title = re.sub(r"\s+", " ", soup.title.get_text(" ", strip=True) if soup.title else "").strip()
            headings = [
                re.sub(r"\s+", " ", heading.get_text(" ", strip=True)).strip()
                for heading in soup.find_all(["h1", "h2", "h3"])[:12]
            ]
            nav_text = re.sub(
                r"\s+",
                " ",
                " ".join(nav.get_text(" ", strip=True) for nav in soup.find_all("nav")[:3]),
            ).strip()
            body_text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()[:3000]
        except Exception:
            text = re.sub(r"<[^>]+>", " ", html)
            body_text = re.sub(r"\s+", " ", text).strip()[:3000]
        rel_path = "/" + html_path.relative_to(root).as_posix()
        page = html_path.stem if html_path.stem != "index" else "home"
        inventory.append(
            {
                "path": rel_path,
                "page": page,
                "file_path": str(html_path.resolve()),
                "title": title,
                "headings": headings,
                "nav_text": nav_text,
                "route_tokens": _route_tokens(" ".join([rel_path, page, title, " ".join(headings)])),
                "content_tokens": _route_tokens(" ".join([rel_path, page, title, " ".join(headings), body_text])),
            }
        )
    return inventory


def _semantic_route_for_capture(
    capture: dict[str, Any],
    route_inventory: list[dict[str, Any]],
) -> dict[str, Any] | None:
    capture_path = capture.get("path") or capture.get("urlPath") or "/index.html"
    capture_page = str(capture.get("page") or "")
    route_query = _route_tokens(f"{Path(str(capture_path)).stem} {capture_page}")
    intent_query = _route_tokens(capture.get("intent"))
    query = route_query | intent_query
    if not query:
        return None

    best: tuple[float, dict[str, Any]] | None = None
    for route in route_inventory:
        route_tokens = set(route.get("route_tokens") or set())
        content_tokens = set(route.get("content_tokens") or route_tokens)
        if not route_tokens:
            continue
        route_hits = len(route_query & route_tokens)
        intent_route_hits = len(intent_query & route_tokens)
        intent_content_hits = len(intent_query & content_tokens)
        route_score = route_hits / max(1, min(len(route_query), len(route_tokens)))
        intent_route_score = intent_route_hits / max(1, min(3, len(intent_query)))
        intent_content_score = intent_content_hits / max(1, min(len(intent_query), len(content_tokens)))
        slug_score = SequenceMatcher(
            None,
            re.sub(r"[^a-z0-9]+", "", f"{Path(str(capture_path)).stem}{capture_page}".lower()),
            re.sub(r"[^a-z0-9]+", "", f"{route.get('path')} {route.get('page')}".lower()),
        ).ratio()
        score = max(
            route_score,
            intent_route_score,
            slug_score * 0.7,
            route_score * 0.7 + intent_content_score * 0.3,
        )
        if best is None or score > best[0]:
            best = (score, route)

    if not best or best[0] < 0.45:
        return None

    score, route = best
    confidence = 1.0 if score >= 0.65 else round(max(0.75, min(0.95, score)), 6)
    return {
        "requested_path": capture_path,
        "resolved_path": route["path"],
        "file_path": route["file_path"],
        "confidence": confidence,
        "status": "resolved",
        "method": "semantic_route_inventory",
        "failure_mode": "exact_path_missing",
        "match_score": round(score, 6),
        "matched_page": route.get("page"),
        "matched_title": route.get("title"),
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


def _stability_wait_ms(defaults: dict[str, Any], capture: dict[str, Any]) -> int:
    if "stabilityWaitMs" in capture:
        return int(capture.get("stabilityWaitMs") or 0)
    return int(defaults.get("stabilityWaitMs") or 120)


def _wait_for_render_stability(page: Page, quiet_ms: int) -> None:
    page.evaluate(
        """() => new Promise((resolve) => {
          requestAnimationFrame(() => requestAnimationFrame(resolve));
        })"""
    )
    if quiet_ms <= 0:
        return
    page.evaluate(
        """(quietMs) => new Promise((resolve) => {
          let timer = null;
          const done = () => {
            observer.disconnect();
            resolve();
          };
          const observer = new MutationObserver(() => {
            if (timer !== null) clearTimeout(timer);
            timer = setTimeout(done, quietMs);
          });
          observer.observe(document.documentElement, {
            attributes: true,
            childList: true,
            subtree: true,
            characterData: true
          });
          timer = setTimeout(done, quietMs);
        })""",
        quiet_ms,
    )


async def _wait_for_render_stability_async(page: AsyncPage, quiet_ms: int) -> None:
    await page.evaluate(
        """() => new Promise((resolve) => {
          requestAnimationFrame(() => requestAnimationFrame(resolve));
        })"""
    )
    if quiet_ms <= 0:
        return
    await page.evaluate(
        """(quietMs) => new Promise((resolve) => {
          let timer = null;
          const done = () => {
            observer.disconnect();
            resolve();
          };
          const observer = new MutationObserver(() => {
            if (timer !== null) clearTimeout(timer);
            timer = setTimeout(done, quietMs);
          });
          observer.observe(document.documentElement, {
            attributes: true,
            childList: true,
            subtree: true,
            characterData: true
          });
          timer = setTimeout(done, quietMs);
        })""",
        quiet_ms,
    )


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
    _wait_for_render_stability(page, _stability_wait_ms(defaults, capture))
    page.evaluate(STAMP_MANIFEST_ELEMENTS_SCRIPT)


def _is_manifest_stamp_selector(selector: str | None) -> bool:
    return bool(selector and "data-wde-manifest-id" in selector)


def _is_coverage_scored_action(action: dict[str, Any]) -> bool:
    return action.get("type") in {"hover", "click", "focus", "fill", "press", "scroll", "scrollBy"}


def _selector_actionable(page: Page, selector: str, action_type: str) -> bool:
    try:
        if page.locator(selector).count() != 1:
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
    return round(float(min(score, 1.0)), 6)


def _resolve_action(page: Page, action: dict[str, Any], reference_signature: dict[str, Any] | None) -> dict[str, Any]:
    selector = action.get("selector")
    action_type = action.get("type", "")
    if selector and not _is_manifest_stamp_selector(selector) and _selector_actionable(page, selector, action_type):
        return {
            "status": "resolved",
            "method": "exact_selector",
            "requested_selector": selector,
            "resolved_selector": selector,
            "confidence": 1.0,
            "failure_mode": None,
            "matched_element": None,
        }

    if selector and not _is_manifest_stamp_selector(selector) and action_type == "hover":
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


def _run_action(
    page: Page,
    action: dict[str, Any],
    selector: str | None = None,
    *,
    scroll_strategy: str = "playwright_with_dom_nearest_fallback",
) -> None:
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
            if scroll_strategy == "dom_nearest":
                page.evaluate(
                    """(selector) => {
                      const el = document.querySelector(selector);
                      if (!el) throw new Error(`No element matches selector: ${selector}`);
                      el.scrollIntoView({ block: 'nearest', inline: 'nearest' });
                    }""",
                    resolved_selector,
                )
            elif scroll_strategy == "playwright_with_dom_nearest_fallback":
                try:
                    page.locator(resolved_selector).first.scroll_into_view_if_needed(timeout=3000)
                except Exception:
                    page.evaluate(
                        """(selector) => {
                          const el = document.querySelector(selector);
                          if (!el) throw new Error(`No element matches selector: ${selector}`);
                          el.scrollIntoView({ block: 'nearest', inline: 'nearest' });
                        }""",
                        resolved_selector,
                    )
            else:
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


def _execute_reference_actions(
    page: Page,
    capture: dict[str, Any],
    *,
    scroll_strategy: str = "playwright_with_dom_nearest_fallback",
) -> list[dict[str, Any]]:
    executed = []
    for action in capture.get("actions") or []:
        before = _page_state(page)
        signature = _element_signature(page, action["selector"]) if action.get("selector") else None
        status = "resolved"
        failure = None
        try:
            _run_action(page, action, scroll_strategy=scroll_strategy)
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


def _execute_candidate_actions(
    page: Page,
    reference_actions: list[dict[str, Any]],
    *,
    scroll_strategy: str = "playwright_with_dom_nearest_fallback",
) -> list[dict[str, Any]]:
    executed = []
    for reference_action in reference_actions:
        action = reference_action["action"]
        coverage_scored = _is_coverage_scored_action(action)
        before = _page_state(page)
        if action.get("type") in {"wait", "press", "scrollBy"} and not action.get("selector"):
            resolution = {
                "status": "resolved",
                "method": "direct_non_selector_action",
                "requested_selector": None,
                "resolved_selector": None,
                "confidence": 1.0,
                "failure_mode": None,
                "matched_element": None,
            }
        else:
            resolution = _resolve_action(page, action, reference_action.get("reference_signature"))
        action_status = "skipped"
        failure = None
        post_state = {"score": 0.0, "checks": {"reason": "action_not_resolved"}}
        after = before

        if resolution["status"] == "resolved":
            try:
                _run_action(
                    page,
                    action,
                    selector=resolution.get("resolved_selector"),
                    scroll_strategy=scroll_strategy,
                )
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

        coverage = None
        if coverage_scored:
            coverage = round(float(resolution.get("confidence", 0.0)) * float(post_state.get("score", 0.0)), 6)
        executed.append(
            {
                "action": action,
                "resolution": resolution,
                "status": action_status,
                "failure": failure,
                "post_state": post_state,
                "coverage_scored": coverage_scored,
                "coverage_contribution": coverage,
                "before_state": before,
                "after_state": after,
            }
        )
    return executed


def _execute_direct_manifest_actions(
    page: Page,
    capture: dict[str, Any],
    *,
    scroll_strategy: str = "playwright_with_dom_nearest_fallback",
) -> list[dict[str, Any]]:
    executed = []
    for action in capture.get("actions") or []:
        before = _page_state(page)
        action_status = "completed"
        failure = None
        after = before
        try:
            _run_action(page, action, scroll_strategy=scroll_strategy)
            after = _page_state(page)
        except Exception as exc:
            action_status = "failed"
            failure = f"{type(exc).__name__}: {exc}"

        coverage_scored = action.get("type") in {
            "hover",
            "click",
            "focus",
            "fill",
            "press",
            "scroll",
            "scrollBy",
            "waitForSelector",
        }
        executed.append(
            {
                "action": action,
                "resolution": {
                    "status": "resolved" if action_status == "completed" else "failed",
                    "method": "candidate_manifest_direct_action",
                    "requested_selector": action.get("selector"),
                    "resolved_selector": action.get("selector"),
                    "confidence": 1.0 if action_status == "completed" else 0.0,
                    "failure_mode": None if action_status == "completed" else "candidate_manifest_action_failed",
                    "matched_element": None,
                },
                "status": action_status,
                "failure": failure,
                "post_state": {"score": 1.0 if action_status == "completed" else 0.0, "checks": {"source": "candidate_manifest"}},
                "coverage_scored": coverage_scored,
                "coverage_contribution": 1.0 if coverage_scored and action_status == "completed" else 0.0 if coverage_scored else None,
                "before_state": before,
                "after_state": after,
            }
        )
    return executed


def _artifact_cssom(page: Page, screenshot_dimensions: dict[str, int]) -> dict[str, Any]:
    snapshot = page.evaluate(
        CSSOM_ARTIFACT_SCRIPT,
        {
            "controlSelectors": CONTROL_SELECTORS,
            "normalizeWidth": screenshot_dimensions["width"],
            "normalizeHeight": screenshot_dimensions["height"],
            "screenshotWidth": screenshot_dimensions["width"],
            "screenshotHeight": screenshot_dimensions["height"],
        },
    )
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
    page.evaluate(REMOVE_EVALUATOR_ATTRIBUTES_SCRIPT)
    page.screenshot(**_screenshot_options(defaults, capture, screenshot_path))
    with Image.open(screenshot_path) as image:
        screenshot_dimensions = {"width": image.width, "height": image.height}
    outer_html = page.evaluate("() => document.documentElement.outerHTML")
    cssom = _artifact_cssom(page, screenshot_dimensions)
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


def _safe_box(box: dict[str, Any] | None) -> dict[str, float] | None:
    if not box:
        return None
    width = float(box.get("width", 0.0))
    height = float(box.get("height", 0.0))
    if width <= 0 or height <= 0:
        return None
    return {
        "x": float(box.get("x", 0.0)),
        "y": float(box.get("y", 0.0)),
        "width": width,
        "height": height,
    }


def _bbox_iou(reference: dict[str, Any] | None, candidate: dict[str, Any] | None) -> float:
    ref = _safe_box(reference)
    cand = _safe_box(candidate)
    if ref is None or cand is None:
        return 0.0
    x1 = max(ref["x"], cand["x"])
    y1 = max(ref["y"], cand["y"])
    x2 = min(ref["x"] + ref["width"], cand["x"] + cand["width"])
    y2 = min(ref["y"] + ref["height"], cand["y"] + cand["height"])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = ref["width"] * ref["height"] + cand["width"] * cand["height"] - intersection
    return round(float(intersection / union), 6) if union > 0 else 0.0


def _bbox_center(box: dict[str, Any] | None) -> tuple[float, float] | None:
    safe = _safe_box(box)
    if safe is None:
        return None
    return (safe["x"] + safe["width"] / 2.0, safe["y"] + safe["height"] / 2.0)


def _distance(a: tuple[float, float] | None, b: tuple[float, float] | None) -> float | None:
    if a is None or b is None:
        return None
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _clip_box(box: dict[str, Any] | None, width: int, height: int) -> tuple[int, int, int, int] | None:
    safe = _safe_box(box)
    if safe is None:
        return None
    left = max(0, min(width, int(round(safe["x"]))))
    top = max(0, min(height, int(round(safe["y"]))))
    right = max(0, min(width, int(round(safe["x"] + safe["width"]))))
    bottom = max(0, min(height, int(round(safe["y"] + safe["height"]))))
    if right <= left or bottom <= top:
        return None
    return (left, top, right, bottom)


def _crop_from_frame(frame_path: Path, box: dict[str, Any] | None, output_path: Path) -> str | None:
    with Image.open(frame_path) as image:
        clip = _clip_box(box, image.width, image.height)
        if clip is None:
            return None
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.crop(clip).save(output_path)
        return str(output_path)


def _resolve_target(page: Page, target: dict[str, Any], reference_signature: dict[str, Any] | None) -> dict[str, Any]:
    selector = target.get("selector")
    if selector:
        try:
            if page.locator(selector).count() == 1:
                return {
                    "status": "resolved",
                    "method": "exact_selector",
                    "requested_selector": selector,
                    "resolved_selector": selector,
                    "confidence": 1.0,
                    "failure_mode": None,
                    "matched_element": None,
                }
        except Exception:
            pass
    if reference_signature is None:
        return {
            "status": "unsupported",
            "method": None,
            "requested_selector": selector,
            "resolved_selector": None,
            "confidence": 0.0,
            "failure_mode": "target_selector_missing_or_reference_signature_unavailable",
            "matched_element": None,
        }
    candidates = [element for element in _candidate_elements(page) if element.get("visible")]
    scored = [(_score_candidate_element(reference_signature, candidate, "focus"), candidate) for candidate in candidates]
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
    if best_score < 0.35:
        return {
            "status": "unsupported",
            "method": "element_match",
            "requested_selector": selector,
            "resolved_selector": None,
            "confidence": best_score,
            "failure_mode": "no_candidate_target_above_threshold",
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


def _animation_action(animation: dict[str, Any]) -> dict[str, Any]:
    trigger = animation.get("trigger") or {}
    return {
        "type": trigger.get("type") or "click",
        "selector": trigger.get("selector"),
        "settleMs": trigger.get("settleMs") or 0,
    }


def _animation_samples(animation: dict[str, Any]) -> list[int]:
    timeline = animation.get("timeline") or {}
    samples = sorted({int(value) for value in timeline.get("samplesMs") or [] if isinstance(value, int | float) and value >= 0})
    if 0 not in samples:
        samples.insert(0, 0)
    if len(samples) < 2:
        duration = int(timeline.get("durationMs") or 600)
        samples = [0, duration]
    return samples


def _sample_animation_page(
    page: Page,
    animation: dict[str, Any],
    target_resolutions: list[dict[str, Any]],
    artifact_dir: Path,
    *,
    side: str,
) -> dict[str, Any]:
    frames_dir = artifact_dir / "animations" / animation["id"] / "frames"
    crops_dir = artifact_dir / "animations" / animation["id"] / "target-crops"
    samples = _animation_samples(animation)
    timeline_rows = []

    def sample_at(timestamp_ms: int) -> dict[str, Any]:
        frame_path = frames_dir / f"frame-{timestamp_ms:04d}.png"
        frames_dir.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(frame_path), full_page=False, animations="allow", caret="hide")
        target_rows = []
        for index, target in enumerate(animation.get("targets") or []):
            resolution = target_resolutions[index] if index < len(target_resolutions) else {}
            selector = resolution.get("resolved_selector")
            sample = page.evaluate(
                ANIMATION_SAMPLE_SCRIPT,
                {"selector": selector, "track": target.get("track") or []},
            ) if selector else None
            crop_path = None
            if sample:
                crop_path = _crop_from_frame(
                    frame_path,
                    sample.get("bbox_px"),
                    crops_dir / f"target-{index}-frame-{timestamp_ms:04d}.png",
                )
            target_rows.append(
                {
                    "target_index": index,
                    "name": target.get("name"),
                    "channels": target.get("channels") or [],
                    "track": target.get("track") or [],
                    "resolution": resolution,
                    "sample": sample,
                    "crop_path": crop_path,
                }
            )
        return {"timestampMs": timestamp_ms, "frame_path": str(frame_path), "targets": target_rows}

    timeline_rows.append(sample_at(samples[0]))
    action = _animation_action(animation)
    trigger_signature = _element_signature(page, action["selector"]) if action.get("selector") else None
    trigger_status = "resolved"
    trigger_failure = None
    try:
        settle_before_ms = int((animation.get("trigger") or {}).get("settleBeforeMs") or 0)
        if settle_before_ms:
            page.wait_for_timeout(settle_before_ms)
        if action.get("type") != "wait":
            _run_action(page, action, scroll_strategy="playwright_with_dom_nearest_fallback")
    except Exception as exc:
        trigger_status = "failed"
        trigger_failure = f"{type(exc).__name__}: {exc}"

    previous = samples[0]
    for timestamp_ms in samples[1:]:
        page.wait_for_timeout(max(0, timestamp_ms - previous))
        timeline_rows.append(sample_at(timestamp_ms))
        previous = timestamp_ms

    artifact = {
        "animation_id": animation["id"],
        "side": side,
        "page": animation.get("page"),
        "path": animation.get("path"),
        "viewport": animation.get("viewport"),
        "trigger": {
            "action": action,
            "status": trigger_status,
            "failure": trigger_failure,
            "reference_signature": trigger_signature,
        },
        "timeline": timeline_rows,
    }
    _write_json(artifact_dir / "animations" / animation["id"] / "timeline.json", artifact)
    return artifact


def _capture_reference_animation(
    browser: Browser,
    base_url: str,
    animation: dict[str, Any],
    manifest: dict[str, Any],
    route: dict[str, Any],
    artifact_dir: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any] | None]:
    defaults = manifest.get("defaults", {})
    context = browser.new_context(device_scale_factor=defaults.get("deviceScaleFactor", 1))
    page = context.new_page()
    try:
        _goto_capture(page, base_url, route, animation, defaults)
        target_resolutions = []
        for target in animation.get("targets") or []:
            signature = _element_signature(page, target.get("selector")) if target.get("selector") else None
            target_resolutions.append(
                {
                    "status": "resolved" if signature else "unsupported",
                    "method": "exact_selector" if signature else None,
                    "requested_selector": target.get("selector"),
                    "resolved_selector": target.get("selector") if signature else None,
                    "confidence": 1.0 if signature else 0.0,
                    "failure_mode": None if signature else "reference_target_unresolved",
                    "reference_signature": signature,
                }
            )
        artifact = _sample_animation_page(page, animation, target_resolutions, artifact_dir, side="reference")
        return artifact, target_resolutions, artifact.get("trigger", {}).get("reference_signature")
    finally:
        context.close()


def _capture_candidate_animation(
    browser: Browser,
    base_url: str,
    animation: dict[str, Any],
    manifest: dict[str, Any],
    route: dict[str, Any],
    reference_target_resolutions: list[dict[str, Any]],
    reference_trigger_signature: dict[str, Any] | None,
    artifact_dir: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    defaults = manifest.get("defaults", {})
    context = browser.new_context(device_scale_factor=defaults.get("deviceScaleFactor", 1))
    page = context.new_page()
    try:
        _goto_capture(page, base_url, route, animation, defaults)
        target_resolutions = []
        for index, target in enumerate(animation.get("targets") or []):
            reference_signature = None
            if index < len(reference_target_resolutions):
                reference_signature = reference_target_resolutions[index].get("reference_signature")
            target_resolutions.append(_resolve_target(page, target, reference_signature))

        action = _animation_action(animation)
        if action.get("type") != "wait":
            trigger_resolution = _resolve_action(page, action, reference_trigger_signature)
            if trigger_resolution["status"] == "resolved":
                animation = json.loads(json.dumps(animation))
                animation["trigger"]["selector"] = trigger_resolution.get("resolved_selector")
            else:
                artifact = {
                    "animation_id": animation["id"],
                    "side": "candidate",
                    "page": animation.get("page"),
                    "path": animation.get("path"),
                    "viewport": animation.get("viewport"),
                    "trigger": {"action": action, "status": "unsupported", "resolution": trigger_resolution},
                    "timeline": [],
                }
                _write_json(artifact_dir / "animations" / animation["id"] / "timeline.json", artifact)
                return artifact, target_resolutions

        artifact = _sample_animation_page(page, animation, target_resolutions, artifact_dir, side="candidate")
        return artifact, target_resolutions
    finally:
        context.close()


def _score_motion_target(reference_rows: list[dict[str, Any]], candidate_rows: list[dict[str, Any]]) -> dict[str, Any]:
    ious = []
    for ref_row, cand_row in zip(reference_rows, candidate_rows, strict=False):
        ref_box = ((ref_row.get("sample") or {}).get("bbox_px") if ref_row else None)
        cand_box = ((cand_row.get("sample") or {}).get("bbox_px") if cand_row else None)
        ious.append(_bbox_iou(ref_box, cand_box))

    interval_scores = []
    weighted_total = 0.0
    weight_sum = 0.0
    for index in range(max(0, min(len(reference_rows), len(candidate_rows)) - 1)):
        ref_a = _bbox_center((reference_rows[index].get("sample") or {}).get("bbox_px"))
        ref_b = _bbox_center((reference_rows[index + 1].get("sample") or {}).get("bbox_px"))
        cand_a = _bbox_center((candidate_rows[index].get("sample") or {}).get("bbox_px"))
        cand_b = _bbox_center((candidate_rows[index + 1].get("sample") or {}).get("bbox_px"))
        ref_move = _distance(ref_a, ref_b)
        cand_move = _distance(cand_a, cand_b)
        if ref_move is None or cand_move is None or ref_move <= 1.0:
            continue
        interval_score = max(0.0, 1.0 - abs(cand_move - ref_move) / max(ref_move, 1.0))
        interval_scores.append(
            {
                "interval": [index, index + 1],
                "reference_movement_px": round(ref_move, 6),
                "candidate_movement_px": round(cand_move, 6),
                "score": round(interval_score, 6),
                "weight": round(ref_move, 6),
            }
        )
        weighted_total += interval_score * ref_move
        weight_sum += ref_move

    return {
        "bbox_iou": round(float(sum(ious) / len(ious)), 6) if ious else 0.0,
        "bbox_iou_by_frame": ious,
        "motion_delta": round(float(weighted_total / weight_sum), 6) if weight_sum else 1.0,
        "motion_delta_intervals": interval_scores,
        "movement_weight_sum": round(weight_sum, 6),
    }


def _normalize_style_value(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _animation_style_similarity(prop: str, reference: str, candidate: str) -> float:
    if prop.endswith("color") or prop == "color":
        color_score = _color_similarity(reference, candidate)
        if color_score is not None:
            return color_score
    return 1.0 if reference == candidate else 0.0


def _score_color_target(reference_rows: list[dict[str, Any]], candidate_rows: list[dict[str, Any]]) -> dict[str, Any]:
    pixel_scores = []
    cssom_scores = []
    cssom_rows = []
    for ref_row, cand_row in zip(reference_rows, candidate_rows, strict=False):
        ref_crop = ref_row.get("crop_path")
        cand_crop = cand_row.get("crop_path")
        if ref_crop and cand_crop:
            pixel_scores.append(pixelmatch_score(ref_crop, cand_crop)["score"])
        ref_style = (ref_row.get("sample") or {}).get("style") or {}
        cand_style = (cand_row.get("sample") or {}).get("style") or {}
        props = sorted(set(ref_style) | set(cand_style))
        prop_scores = []
        for prop in props:
            ref_value = _normalize_style_value(ref_style.get(prop))
            cand_value = _normalize_style_value(cand_style.get(prop))
            score = _animation_style_similarity(prop, ref_value, cand_value)
            prop_scores.append(score)
            cssom_rows.append(
                {
                    "property": prop,
                    "reference": ref_value,
                    "candidate": cand_value,
                    "score": round(score, 6),
                    "method": "rgb_distance" if prop.endswith("color") or prop == "color" else "exact",
                }
            )
        if prop_scores:
            cssom_scores.append(sum(prop_scores) / len(prop_scores))
    return {
        "target_box_pixelmatch": round(float(sum(pixel_scores) / len(pixel_scores)), 6) if pixel_scores else None,
        "target_box_pixelmatch_by_frame": pixel_scores,
        "cssom_color": round(float(sum(cssom_scores) / len(cssom_scores)), 6) if cssom_scores else None,
        "cssom_color_by_property": cssom_rows,
    }


def _score_animation_pair(reference_artifact: dict[str, Any], candidate_artifact: dict[str, Any]) -> dict[str, Any]:
    if not reference_artifact.get("timeline") or not candidate_artifact.get("timeline"):
        return {"status": "unsupported", "reason": "animation_timeline_missing"}
    target_count = max(
        len(reference_artifact["timeline"][0].get("targets", [])),
        len(candidate_artifact["timeline"][0].get("targets", [])),
    )
    targets = []
    for target_index in range(target_count):
        ref_rows = [
            sample.get("targets", [])[target_index]
            for sample in reference_artifact.get("timeline", [])
            if len(sample.get("targets", [])) > target_index
        ]
        cand_rows = [
            sample.get("targets", [])[target_index]
            for sample in candidate_artifact.get("timeline", [])
            if len(sample.get("targets", [])) > target_index
        ]
        channels = sorted(set(ref_rows[0].get("channels") or []) | set(cand_rows[0].get("channels") or [])) if ref_rows and cand_rows else []
        channel_scores: dict[str, Any] = {}
        if "motion" in channels:
            channel_scores["motion"] = _score_motion_target(ref_rows, cand_rows)
        if "color" in channels:
            channel_scores["color"] = _score_color_target(ref_rows, cand_rows)
        targets.append(
            {
                "target_index": target_index,
                "name": ref_rows[0].get("name") if ref_rows else None,
                "channels": channels,
                "scores": channel_scores,
            }
        )
    return {
        "status": "scored",
        "trigger": {
            "reference_status": (reference_artifact.get("trigger") or {}).get("status"),
            "candidate_status": (candidate_artifact.get("trigger") or {}).get("status"),
        },
        "targets": targets,
    }


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


def _extract_visual_blocks_for_artifact(
    browser: Browser,
    base_url: str,
    capture: dict[str, Any],
    manifest: dict[str, Any],
    route: dict[str, Any],
    reference_actions: list[dict[str, Any]],
    artifact: dict[str, Any],
    *,
    side: str,
    direct_candidate_actions: bool = False,
    config: EvaluateConfig | None = None,
) -> dict[str, Any]:
    defaults = manifest.get("defaults", {})
    context = browser.new_context(device_scale_factor=defaults.get("deviceScaleFactor", 1))
    page = context.new_page()
    try:
        _goto_capture(page, base_url, route, capture, defaults)
        if side == "reference":
            replay_actions = _execute_reference_actions(
                page,
                capture,
                scroll_strategy="playwright_with_dom_nearest_fallback",
            )
        elif direct_candidate_actions:
            replay_actions = _execute_direct_manifest_actions(
                page,
                capture,
                scroll_strategy="playwright_with_dom_nearest_fallback",
            )
        else:
            replay_actions = _execute_candidate_actions(
                page,
                reference_actions,
                scroll_strategy="playwright_with_dom_nearest_fallback",
            )
        replay_failure = _visual_block_replay_failure(replay_actions)
        if replay_failure:
            return {
                "status": "unsupported",
                "reason": replay_failure,
                "blocks": [],
                "block_count": 0,
                "artifact_source": "isolated_playwright_manifest_state",
                "replay_actions": replay_actions,
            }

        screenshot_path = artifact.get("screenshot_path")
        if not screenshot_path:
            return {
                "status": "unsupported",
                "reason": "screenshot_missing",
                "blocks": [],
                "block_count": 0,
                "artifact_source": "isolated_playwright_manifest_state",
                "replay_actions": replay_actions,
            }

        page.evaluate(REMOVE_EVALUATOR_ATTRIBUTES_SCRIPT)
        screenshot_options = _screenshot_options(defaults, capture, Path(screenshot_path))

        def progress_callback(event: str, **fields: Any) -> None:
            if config is None:
                return
            _progress(
                config,
                event,
                capture_id=capture["id"],
                side=side,
                **fields,
            )

        visual_blocks = extract_visual_blocks_from_playwright_page(
            page,
            screenshot_path,
            screenshot_options=screenshot_options,
            progress_callback=progress_callback,
        )
        visual_blocks["replay_actions"] = replay_actions
        return visual_blocks
    finally:
        context.close()


def _capture_reference(
    browser: Browser,
    base_url: str,
    capture: dict[str, Any],
    manifest: dict[str, Any],
    route: dict[str, Any],
    artifact_dir: Path,
    *,
    include_visual_blocks: bool,
    config: EvaluateConfig | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    defaults = manifest.get("defaults", {})
    context = browser.new_context(device_scale_factor=defaults.get("deviceScaleFactor", 1))
    page = context.new_page()
    try:
        _goto_capture(page, base_url, route, capture, defaults)
        reference_actions = _execute_reference_actions(page, capture)
        artifact = _artifact_from_page(page, capture, defaults, artifact_dir, reference_actions, side="reference")
        artifact["route"] = route
        if include_visual_blocks:
            try:
                artifact["visual_blocks"] = _extract_visual_blocks_for_artifact(
                    browser,
                    base_url,
                    capture,
                    manifest,
                    route,
                    reference_actions,
                    artifact,
                    side="reference",
                    config=config,
                )
            except Exception as exc:
                artifact["visual_blocks"] = {
                    "status": "error",
                    "reason": f"{type(exc).__name__}: {exc}",
                    "blocks": [],
                    "block_count": 0,
                    "artifact_source": "isolated_playwright_manifest_state",
                }
                artifact["extraction_errors"].append({"metric": "visual_blocks", "message": artifact["visual_blocks"]["reason"]})
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
    *,
    include_visual_blocks: bool,
    config: EvaluateConfig | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    defaults = manifest.get("defaults", {})
    context = browser.new_context(device_scale_factor=defaults.get("deviceScaleFactor", 1))
    page = context.new_page()
    try:
        _goto_capture(page, base_url, route, capture, defaults)
        candidate_actions = _execute_candidate_actions(page, reference_actions)
        artifact = _artifact_from_page(page, capture, defaults, artifact_dir, candidate_actions, side="candidate")
        artifact["route"] = route
        if include_visual_blocks:
            try:
                artifact["visual_blocks"] = _extract_visual_blocks_for_artifact(
                    browser,
                    base_url,
                    capture,
                    manifest,
                    route,
                    reference_actions,
                    artifact,
                    side="candidate",
                    config=config,
                )
            except Exception as exc:
                artifact["visual_blocks"] = {
                    "status": "error",
                    "reason": f"{type(exc).__name__}: {exc}",
                    "blocks": [],
                    "block_count": 0,
                    "artifact_source": "isolated_playwright_manifest_state",
                }
                artifact["extraction_errors"].append({"metric": "visual_blocks", "message": artifact["visual_blocks"]["reason"]})
        _write_json(artifact_dir / f"{capture['id']}.json", artifact)
        return artifact, candidate_actions
    finally:
        context.close()


def _capture_candidate_from_manifest(
    browser: Browser,
    base_url: str,
    capture: dict[str, Any],
    manifest: dict[str, Any],
    route: dict[str, Any],
    artifact_dir: Path,
    *,
    include_visual_blocks: bool,
    config: EvaluateConfig | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    defaults = manifest.get("defaults", {})
    context = browser.new_context(device_scale_factor=defaults.get("deviceScaleFactor", 1))
    page = context.new_page()
    try:
        _goto_capture(page, base_url, route, capture, defaults)
        candidate_actions = _execute_direct_manifest_actions(page, capture)
        artifact = _artifact_from_page(page, capture, defaults, artifact_dir, candidate_actions, side="candidate")
        artifact["route"] = route
        artifact["capture_source"] = "candidate_manifest"
        if include_visual_blocks:
            try:
                artifact["visual_blocks"] = _extract_visual_blocks_for_artifact(
                    browser,
                    base_url,
                    capture,
                    manifest,
                    route,
                    candidate_actions,
                    artifact,
                    side="candidate",
                    direct_candidate_actions=True,
                    config=config,
                )
            except Exception as exc:
                artifact["visual_blocks"] = {
                    "status": "error",
                    "reason": f"{type(exc).__name__}: {exc}",
                    "blocks": [],
                    "block_count": 0,
                    "artifact_source": "isolated_playwright_manifest_state",
                }
                artifact["extraction_errors"].append({"metric": "visual_blocks", "message": artifact["visual_blocks"]["reason"]})
        _write_json(artifact_dir / f"{capture['id']}.json", artifact)
        return artifact, candidate_actions
    finally:
        context.close()


def _visual_block_replay_failure(actions: list[dict[str, Any]]) -> str | None:
    for index, action in enumerate(actions):
        status = action.get("status")
        if status in {"failed", "post_state_failed", "skipped"}:
            return f"replay_action_{index}_{status}"
        if action.get("coverage_scored") and action.get("coverage_contribution") == 0:
            return f"replay_action_{index}_zero_coverage"
    return None


async def _page_state_async(page: AsyncPage) -> dict[str, Any]:
    return await page.evaluate(PAGE_STATE_SCRIPT)


async def _element_signature_async(page: AsyncPage, selector: str) -> dict[str, Any] | None:
    return await page.evaluate(ELEMENT_SIGNATURE_SCRIPT, {"selector": selector})


async def _candidate_elements_async(page: AsyncPage) -> list[dict[str, Any]]:
    return await page.evaluate(CANDIDATE_ELEMENTS_SCRIPT)


async def _visible_ancestor_async(page: AsyncPage, selector: str) -> dict[str, Any] | None:
    return await page.evaluate(VISIBLE_ANCESTOR_SCRIPT, {"selector": selector})


async def _goto_capture_async(
    page: AsyncPage,
    base_url: str,
    route: dict[str, Any],
    capture: dict[str, Any],
    defaults: dict[str, Any],
) -> None:
    viewport = capture.get("viewport") or defaults.get("viewport")
    if viewport:
        await page.set_viewport_size({"width": int(viewport["width"]), "height": int(viewport["height"])})
    color_scheme = capture.get("colorScheme") or defaults.get("colorScheme")
    if color_scheme:
        await page.emulate_media(color_scheme=color_scheme)
    await page.goto(
        _route_url(base_url, route.get("resolved_path")),
        wait_until=capture.get("waitUntil") or defaults.get("waitUntil") or "networkidle",
        timeout=int(capture.get("timeoutMs") or defaults.get("timeoutMs") or 30000),
    )
    after_load_wait_ms = int(defaults.get("afterLoadWaitMs") or 0)
    if after_load_wait_ms:
        await page.wait_for_timeout(after_load_wait_ms)
    await _wait_for_render_stability_async(page, _stability_wait_ms(defaults, capture))
    await page.evaluate(STAMP_MANIFEST_ELEMENTS_SCRIPT)


async def _selector_actionable_async(page: AsyncPage, selector: str, action_type: str) -> bool:
    try:
        locator = page.locator(selector)
        if await locator.count() != 1:
            return False
        if action_type in {"hover", "click", "focus"}:
            return await locator.first.is_visible(timeout=250)
        return True
    except Exception:
        return False


async def _resolve_action_async(
    page: AsyncPage,
    action: dict[str, Any],
    reference_signature: dict[str, Any] | None,
) -> dict[str, Any]:
    selector = action.get("selector")
    action_type = action.get("type", "")
    if selector and not _is_manifest_stamp_selector(selector) and await _selector_actionable_async(page, selector, action_type):
        return {
            "status": "resolved",
            "method": "exact_selector",
            "requested_selector": selector,
            "resolved_selector": selector,
            "confidence": 1.0,
            "failure_mode": None,
            "matched_element": None,
        }

    if selector and not _is_manifest_stamp_selector(selector) and action_type == "hover":
        ancestor = await _visible_ancestor_async(page, selector)
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
        for element in await _candidate_elements_async(page)
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


async def _run_action_async(
    page: AsyncPage,
    action: dict[str, Any],
    selector: str | None = None,
    *,
    scroll_strategy: str = "playwright_with_dom_nearest_fallback",
) -> None:
    action_type = action.get("type")
    resolved_selector = selector or action.get("selector")
    settle_ms = int(action.get("settleMs") or 0)

    if action_type == "hover":
        await page.locator(resolved_selector).first.hover(timeout=3000)
    elif action_type == "click":
        await page.locator(resolved_selector).first.click(timeout=3000)
    elif action_type == "focus":
        await page.locator(resolved_selector).first.focus(timeout=3000)
    elif action_type == "fill":
        await page.locator(resolved_selector).first.fill(str(action.get("value") or ""), timeout=3000)
    elif action_type == "press":
        await page.keyboard.press(str(action.get("key")))
    elif action_type == "wait":
        await page.wait_for_timeout(int(action.get("ms") or 0))
    elif action_type == "waitForSelector":
        await page.locator(resolved_selector).first.wait_for(
            state=action.get("state") or "visible",
            timeout=int(action.get("timeoutMs") or 3000),
        )
    elif action_type == "scroll":
        if resolved_selector:
            if scroll_strategy == "dom_nearest":
                await page.evaluate(
                    """(selector) => {
                      const el = document.querySelector(selector);
                      if (!el) throw new Error(`No element matches selector: ${selector}`);
                      el.scrollIntoView({ block: 'nearest', inline: 'nearest' });
                    }""",
                    resolved_selector,
                )
            elif scroll_strategy == "playwright_with_dom_nearest_fallback":
                try:
                    await page.locator(resolved_selector).first.scroll_into_view_if_needed(timeout=3000)
                except Exception:
                    await page.evaluate(
                        """(selector) => {
                          const el = document.querySelector(selector);
                          if (!el) throw new Error(`No element matches selector: ${selector}`);
                          el.scrollIntoView({ block: 'nearest', inline: 'nearest' });
                        }""",
                        resolved_selector,
                    )
            else:
                await page.locator(resolved_selector).first.scroll_into_view_if_needed(timeout=3000)
        else:
            await page.evaluate(
                "({ x, y }) => window.scrollTo(x || 0, y || 0)",
                {"x": action.get("x", 0), "y": action.get("y", 0)},
            )
    elif action_type == "scrollBy":
        await page.evaluate(
            "({ x, y }) => window.scrollBy(x || 0, y || 0)",
            {"x": action.get("x", 0), "y": action.get("y", 0)},
        )
    else:
        raise ValueError(f"Unknown action type: {action_type}")

    if settle_ms:
        await page.wait_for_timeout(settle_ms)


async def _execute_reference_actions_async(
    page: AsyncPage,
    capture: dict[str, Any],
    *,
    scroll_strategy: str = "playwright_with_dom_nearest_fallback",
) -> list[dict[str, Any]]:
    executed = []
    for action in capture.get("actions") or []:
        before = await _page_state_async(page)
        signature = await _element_signature_async(page, action["selector"]) if action.get("selector") else None
        status = "resolved"
        failure = None
        try:
            await _run_action_async(page, action, scroll_strategy=scroll_strategy)
        except Exception as exc:
            status = "failed"
            failure = f"{type(exc).__name__}: {exc}"
        after = await _page_state_async(page)
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


async def _execute_candidate_actions_async(
    page: AsyncPage,
    reference_actions: list[dict[str, Any]],
    *,
    scroll_strategy: str = "playwright_with_dom_nearest_fallback",
) -> list[dict[str, Any]]:
    executed = []
    for reference_action in reference_actions:
        action = reference_action["action"]
        coverage_scored = _is_coverage_scored_action(action)
        before = await _page_state_async(page)
        if action.get("type") in {"wait", "press", "scrollBy"} and not action.get("selector"):
            resolution = {
                "status": "resolved",
                "method": "direct_non_selector_action",
                "requested_selector": None,
                "resolved_selector": None,
                "confidence": 1.0,
                "failure_mode": None,
                "matched_element": None,
            }
        else:
            resolution = await _resolve_action_async(page, action, reference_action.get("reference_signature"))
        action_status = "skipped"
        failure = None
        post_state = {"score": 0.0, "checks": {"reason": "action_not_resolved"}}
        after = before

        if resolution["status"] == "resolved":
            try:
                await _run_action_async(
                    page,
                    action,
                    selector=resolution.get("resolved_selector"),
                    scroll_strategy=scroll_strategy,
                )
                after = await _page_state_async(page)
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

        coverage = None
        if coverage_scored:
            coverage = round(float(resolution.get("confidence", 0.0)) * float(post_state.get("score", 0.0)), 6)
        executed.append(
            {
                "action": action,
                "resolution": resolution,
                "status": action_status,
                "failure": failure,
                "post_state": post_state,
                "coverage_scored": coverage_scored,
                "coverage_contribution": coverage,
                "before_state": before,
                "after_state": after,
            }
        )
    return executed


async def _execute_direct_manifest_actions_async(
    page: AsyncPage,
    capture: dict[str, Any],
    *,
    scroll_strategy: str = "playwright_with_dom_nearest_fallback",
) -> list[dict[str, Any]]:
    executed = []
    for action in capture.get("actions") or []:
        before = await _page_state_async(page)
        action_status = "completed"
        failure = None
        after = before
        try:
            await _run_action_async(page, action, scroll_strategy=scroll_strategy)
            after = await _page_state_async(page)
        except Exception as exc:
            action_status = "failed"
            failure = f"{type(exc).__name__}: {exc}"

        coverage_scored = action.get("type") in {
            "hover",
            "click",
            "focus",
            "fill",
            "press",
            "scroll",
            "scrollBy",
            "waitForSelector",
        }
        executed.append(
            {
                "action": action,
                "resolution": {
                    "status": "resolved" if action_status == "completed" else "failed",
                    "method": "candidate_manifest_direct_action",
                    "requested_selector": action.get("selector"),
                    "resolved_selector": action.get("selector"),
                    "confidence": 1.0 if action_status == "completed" else 0.0,
                    "failure_mode": None if action_status == "completed" else "candidate_manifest_action_failed",
                    "matched_element": None,
                },
                "status": action_status,
                "failure": failure,
                "post_state": {"score": 1.0 if action_status == "completed" else 0.0, "checks": {"source": "candidate_manifest"}},
                "coverage_scored": coverage_scored,
                "coverage_contribution": 1.0 if coverage_scored and action_status == "completed" else 0.0 if coverage_scored else None,
                "before_state": before,
                "after_state": after,
            }
        )
    return executed


async def _artifact_cssom_async(page: AsyncPage, screenshot_dimensions: dict[str, int]) -> dict[str, Any]:
    return await page.evaluate(
        CSSOM_ARTIFACT_SCRIPT,
        {
            "controlSelectors": CONTROL_SELECTORS,
            "normalizeWidth": screenshot_dimensions["width"],
            "normalizeHeight": screenshot_dimensions["height"],
            "screenshotWidth": screenshot_dimensions["width"],
            "screenshotHeight": screenshot_dimensions["height"],
        },
    )


async def _artifact_from_page_async(
    page: AsyncPage,
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
    await page.evaluate(REMOVE_EVALUATOR_ATTRIBUTES_SCRIPT)
    await page.screenshot(**_screenshot_options(defaults, capture, screenshot_path))
    with Image.open(screenshot_path) as image:
        screenshot_dimensions = {"width": image.width, "height": image.height}
    outer_html = await page.evaluate("() => document.documentElement.outerHTML")
    cssom = await _artifact_cssom_async(page, screenshot_dimensions)
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


async def _extract_visual_blocks_for_artifact_async(
    browser: AsyncBrowser,
    base_url: str,
    capture: dict[str, Any],
    manifest: dict[str, Any],
    route: dict[str, Any],
    reference_actions: list[dict[str, Any]],
    artifact: dict[str, Any],
    *,
    side: str,
    direct_candidate_actions: bool = False,
    config: EvaluateConfig | None = None,
) -> dict[str, Any]:
    defaults = manifest.get("defaults", {})
    context = await browser.new_context(device_scale_factor=defaults.get("deviceScaleFactor", 1))
    page = await context.new_page()
    try:
        await _goto_capture_async(page, base_url, route, capture, defaults)
        if side == "reference":
            replay_actions = await _execute_reference_actions_async(
                page,
                capture,
                scroll_strategy="playwright_with_dom_nearest_fallback",
            )
        elif direct_candidate_actions:
            replay_actions = await _execute_direct_manifest_actions_async(
                page,
                capture,
                scroll_strategy="playwright_with_dom_nearest_fallback",
            )
        else:
            replay_actions = await _execute_candidate_actions_async(
                page,
                reference_actions,
                scroll_strategy="playwright_with_dom_nearest_fallback",
            )
        replay_failure = _visual_block_replay_failure(replay_actions)
        if replay_failure:
            return {
                "status": "unsupported",
                "reason": replay_failure,
                "blocks": [],
                "block_count": 0,
                "artifact_source": "isolated_playwright_manifest_state",
                "replay_actions": replay_actions,
            }

        screenshot_path = artifact.get("screenshot_path")
        if not screenshot_path:
            return {
                "status": "unsupported",
                "reason": "screenshot_missing",
                "blocks": [],
                "block_count": 0,
                "artifact_source": "isolated_playwright_manifest_state",
                "replay_actions": replay_actions,
            }

        await page.evaluate(REMOVE_EVALUATOR_ATTRIBUTES_SCRIPT)
        screenshot_options = _screenshot_options(defaults, capture, Path(screenshot_path))

        def progress_callback(event: str, **fields: Any) -> None:
            if config is None:
                return
            _progress(
                config,
                event,
                capture_id=capture["id"],
                side=side,
                **fields,
            )

        visual_blocks = await extract_visual_blocks_from_async_playwright_page(
            page,
            screenshot_path,
            screenshot_options=screenshot_options,
            progress_callback=progress_callback,
        )
        visual_blocks["replay_actions"] = replay_actions
        return visual_blocks
    finally:
        await context.close()


async def _capture_reference_async(
    browser: AsyncBrowser,
    base_url: str,
    capture: dict[str, Any],
    manifest: dict[str, Any],
    route: dict[str, Any],
    artifact_dir: Path,
    *,
    include_visual_blocks: bool,
    config: EvaluateConfig | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    defaults = manifest.get("defaults", {})
    context = await browser.new_context(device_scale_factor=defaults.get("deviceScaleFactor", 1))
    page = await context.new_page()
    try:
        await _goto_capture_async(page, base_url, route, capture, defaults)
        reference_actions = await _execute_reference_actions_async(
            page,
            capture,
            scroll_strategy="playwright_with_dom_nearest_fallback",
        )
        artifact = await _artifact_from_page_async(page, capture, defaults, artifact_dir, reference_actions, side="reference")
        artifact["route"] = route
        if include_visual_blocks:
            try:
                artifact["visual_blocks"] = await _extract_visual_blocks_for_artifact_async(
                    browser,
                    base_url,
                    capture,
                    manifest,
                    route,
                    reference_actions,
                    artifact,
                    side="reference",
                    config=config,
                )
            except Exception as exc:
                artifact["visual_blocks"] = {
                    "status": "error",
                    "reason": f"{type(exc).__name__}: {exc}",
                    "blocks": [],
                    "block_count": 0,
                    "artifact_source": "isolated_playwright_manifest_state",
                }
                artifact["extraction_errors"].append({"metric": "visual_blocks", "message": artifact["visual_blocks"]["reason"]})
        _write_json(artifact_dir / f"{capture['id']}.json", artifact)
        return artifact, reference_actions
    finally:
        await context.close()


async def _capture_candidate_async(
    browser: AsyncBrowser,
    base_url: str,
    capture: dict[str, Any],
    manifest: dict[str, Any],
    route: dict[str, Any],
    reference_actions: list[dict[str, Any]],
    artifact_dir: Path,
    *,
    include_visual_blocks: bool,
    config: EvaluateConfig | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    defaults = manifest.get("defaults", {})
    context = await browser.new_context(device_scale_factor=defaults.get("deviceScaleFactor", 1))
    page = await context.new_page()
    try:
        await _goto_capture_async(page, base_url, route, capture, defaults)
        candidate_actions = await _execute_candidate_actions_async(
            page,
            reference_actions,
            scroll_strategy="playwright_with_dom_nearest_fallback",
        )
        artifact = await _artifact_from_page_async(page, capture, defaults, artifact_dir, candidate_actions, side="candidate")
        artifact["route"] = route
        if include_visual_blocks:
            try:
                artifact["visual_blocks"] = await _extract_visual_blocks_for_artifact_async(
                    browser,
                    base_url,
                    capture,
                    manifest,
                    route,
                    reference_actions,
                    artifact,
                    side="candidate",
                    config=config,
                )
            except Exception as exc:
                artifact["visual_blocks"] = {
                    "status": "error",
                    "reason": f"{type(exc).__name__}: {exc}",
                    "blocks": [],
                    "block_count": 0,
                    "artifact_source": "isolated_playwright_manifest_state",
                }
                artifact["extraction_errors"].append({"metric": "visual_blocks", "message": artifact["visual_blocks"]["reason"]})
        _write_json(artifact_dir / f"{capture['id']}.json", artifact)
        return artifact, candidate_actions
    finally:
        await context.close()


async def _capture_candidate_from_manifest_async(
    browser: AsyncBrowser,
    base_url: str,
    capture: dict[str, Any],
    manifest: dict[str, Any],
    route: dict[str, Any],
    artifact_dir: Path,
    *,
    include_visual_blocks: bool,
    config: EvaluateConfig | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    defaults = manifest.get("defaults", {})
    context = await browser.new_context(device_scale_factor=defaults.get("deviceScaleFactor", 1))
    page = await context.new_page()
    try:
        await _goto_capture_async(page, base_url, route, capture, defaults)
        candidate_actions = await _execute_direct_manifest_actions_async(
            page,
            capture,
            scroll_strategy="playwright_with_dom_nearest_fallback",
        )
        artifact = await _artifact_from_page_async(page, capture, defaults, artifact_dir, candidate_actions, side="candidate")
        artifact["route"] = route
        artifact["capture_source"] = "candidate_manifest"
        if include_visual_blocks:
            try:
                artifact["visual_blocks"] = await _extract_visual_blocks_for_artifact_async(
                    browser,
                    base_url,
                    capture,
                    manifest,
                    route,
                    candidate_actions,
                    artifact,
                    side="candidate",
                    direct_candidate_actions=True,
                    config=config,
                )
            except Exception as exc:
                artifact["visual_blocks"] = {
                    "status": "error",
                    "reason": f"{type(exc).__name__}: {exc}",
                    "blocks": [],
                    "block_count": 0,
                    "artifact_source": "isolated_playwright_manifest_state",
                }
                artifact["extraction_errors"].append({"metric": "visual_blocks", "message": artifact["visual_blocks"]["reason"]})
        _write_json(artifact_dir / f"{capture['id']}.json", artifact)
        return artifact, candidate_actions
    finally:
        await context.close()


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
    action_values = [
        float(action.get("coverage_contribution", 0.0))
        for action in actions
        if action.get("coverage_scored", True) and action.get("coverage_contribution") is not None
    ]
    if not action_values:
        return {"score": route_score, "route_score": route_score, "action_score": None, "reason": None}
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
    *,
    vlm_semaphore: threading.Semaphore | None = None,
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
        "pixelmatch": pixelmatch_score(reference_screenshot, candidate_screenshot),
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
            with vlm_semaphore or nullcontext():
                pair["vlm_judge"] = vlm_judge_score(reference_screenshot, candidate_screenshot, model=config.vlm_model)
        except Exception as exc:
            pair["vlm_judge"] = _metric_error("vlm_judge", exc)

    if config.include_visual_block:
        reference_visual_blocks = reference_artifact.get("visual_blocks") or {}
        candidate_visual_blocks = candidate_artifact.get("visual_blocks") or {}
        if reference_visual_blocks.get("status") == "ok" and candidate_visual_blocks.get("status") == "ok":
            try:
                visual = visual_block_match_from_blocks(
                    reference_visual_blocks.get("blocks", []),
                    candidate_visual_blocks.get("blocks", []),
                    device=config.visual_block_device,
                    include_pairs=True,
                )
                visual["score_skipped"] = True
                visual["score_skip_reason"] = "visual_block_score_disabled"
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
                    reference_cssom = reference_artifact.get("cssom")
                    candidate_cssom = candidate_artifact.get("cssom")
                    if not reference_cssom or not candidate_cssom:
                        pair["cssom_block_style"] = {"unsupported": True, "reason": "cssom_snapshot_missing"}
                    else:
                        pair["cssom_block_style"] = cssom_block_style_score_from_snapshots(
                            reference_cssom,
                            candidate_cssom,
                            visual,
                        )
                except Exception as exc:
                    pair["cssom_block_style"] = _metric_error("cssom_block_style", exc)
            except Exception as exc:
                pair["visual_block"] = _metric_error("visual_block", exc)
                pair["bbox_geometry"] = {"unsupported": True, "reason": "visual_block_failed"}
                pair["cssom_block_style"] = {"unsupported": True, "reason": "visual_block_failed"}
        else:
            reason = (
                reference_visual_blocks.get("reason")
                or candidate_visual_blocks.get("reason")
                or "visual_block_artifact_missing"
            )
            pair["visual_block"] = {
                "unsupported": True,
                "reason": reason,
                "reference_status": reference_visual_blocks.get("status"),
                "candidate_status": candidate_visual_blocks.get("status"),
            }
            pair["bbox_geometry"] = {"unsupported": True, "reason": "visual_block_artifact_missing"}
            pair["cssom_block_style"] = {"unsupported": True, "reason": "visual_block_artifact_missing"}
    else:
        pair["visual_block"] = {"unsupported": True, "reason": "visual block disabled"}
        pair["bbox_geometry"] = {"unsupported": True, "reason": "visual block disabled"}
        pair["cssom_block_style"] = {"unsupported": True, "reason": "visual block disabled"}
    return pair


async def _run_pair_metrics_async(
    reference_artifact: dict[str, Any],
    candidate_artifact: dict[str, Any],
    reference_route: dict[str, Any],
    candidate_route: dict[str, Any],
    config: EvaluateConfig,
    *,
    vlm_semaphore: asyncio.Semaphore,
    dreamsim_semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    capture_id = (
        reference_artifact.get("capture_id")
        or candidate_artifact.get("capture_id")
        or "unknown"
    )
    reference_screenshot = reference_artifact.get("screenshot_path")
    candidate_screenshot = candidate_artifact.get("screenshot_path")
    if not reference_screenshot or not candidate_screenshot:
        _progress(
            config,
            "capture_metrics_missing_screenshot",
            capture_id=capture_id,
            reference_screenshot=bool(reference_screenshot),
            candidate_screenshot=bool(candidate_screenshot),
        )
        return {
            "status": "missing",
            "reason": candidate_artifact.get("missing_reason") or reference_artifact.get("missing_reason"),
        }

    _progress(config, "capture_metrics_start", capture_id=capture_id)
    with _ProgressTimer(config, "screenshot_metrics", capture_id=capture_id):
        pair: dict[str, Any] = {
            "status": "scored",
            "reference_screenshot": reference_screenshot,
            "candidate_screenshot": candidate_screenshot,
            "screenshot_size_match": screenshot_size_match_score(reference_screenshot, candidate_screenshot),
            "pixelmatch": pixelmatch_score(reference_screenshot, candidate_screenshot),
            "reference_render_sanity": render_sanity_score(reference_screenshot),
            "candidate_render_sanity": render_sanity_score(candidate_screenshot),
        }
    reference_html = reference_artifact.get("outer_html")
    candidate_html = candidate_artifact.get("outer_html")
    if reference_html and candidate_html:
        with _ProgressTimer(config, "html_metrics", capture_id=capture_id):
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
        with _ProgressTimer(config, "dreamsim", capture_id=capture_id):
            try:
                async with dreamsim_semaphore:
                    distance = await asyncio.to_thread(
                        dreamsim_distance,
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
        with _ProgressTimer(config, "vlm_judge", capture_id=capture_id, model=config.vlm_model):
            try:
                async with vlm_semaphore:
                    pair["vlm_judge"] = await asyncio.to_thread(
                        vlm_judge_score,
                        reference_screenshot,
                        candidate_screenshot,
                        model=config.vlm_model,
                    )
            except Exception as exc:
                pair["vlm_judge"] = _metric_error("vlm_judge", exc)

    if config.include_visual_block:
        reference_visual_blocks = reference_artifact.get("visual_blocks") or {}
        candidate_visual_blocks = candidate_artifact.get("visual_blocks") or {}
        if reference_visual_blocks.get("status") == "ok" and candidate_visual_blocks.get("status") == "ok":
            try:
                with _ProgressTimer(
                    config,
                    "visual_block_match",
                    capture_id=capture_id,
                    reference_block_count=reference_visual_blocks.get("block_count"),
                    candidate_block_count=candidate_visual_blocks.get("block_count"),
                ):
                    visual = await asyncio.to_thread(
                        visual_block_match_from_blocks,
                        reference_visual_blocks.get("blocks", []),
                        candidate_visual_blocks.get("blocks", []),
                        device=config.visual_block_device,
                        include_pairs=True,
                    )
                visual["score_skipped"] = True
                visual["score_skip_reason"] = "visual_block_score_disabled"
                pair["visual_block"] = visual
                with _ProgressTimer(config, "bbox_geometry", capture_id=capture_id):
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
                    reference_cssom = reference_artifact.get("cssom")
                    candidate_cssom = candidate_artifact.get("cssom")
                    if not reference_cssom or not candidate_cssom:
                        pair["cssom_block_style"] = {"unsupported": True, "reason": "cssom_snapshot_missing"}
                    else:
                        with _ProgressTimer(config, "cssom_block_style", capture_id=capture_id):
                            pair["cssom_block_style"] = cssom_block_style_score_from_snapshots(
                                reference_cssom,
                                candidate_cssom,
                                visual,
                            )
                except Exception as exc:
                    pair["cssom_block_style"] = _metric_error("cssom_block_style", exc)
            except Exception as exc:
                pair["visual_block"] = _metric_error("visual_block", exc)
                pair["bbox_geometry"] = {"unsupported": True, "reason": "visual_block_failed"}
                pair["cssom_block_style"] = {"unsupported": True, "reason": "visual_block_failed"}
        else:
            reason = (
                reference_visual_blocks.get("reason")
                or candidate_visual_blocks.get("reason")
                or "visual_block_artifact_missing"
            )
            pair["visual_block"] = {
                "unsupported": True,
                "reason": reason,
                "reference_status": reference_visual_blocks.get("status"),
                "candidate_status": candidate_visual_blocks.get("status"),
            }
            pair["bbox_geometry"] = {"unsupported": True, "reason": "visual_block_artifact_missing"}
            pair["cssom_block_style"] = {"unsupported": True, "reason": "visual_block_artifact_missing"}
    else:
        pair["visual_block"] = {"unsupported": True, "reason": "visual block disabled"}
        pair["bbox_geometry"] = {"unsupported": True, "reason": "visual block disabled"}
        pair["cssom_block_style"] = {"unsupported": True, "reason": "visual block disabled"}
    _progress(config, "capture_metrics_end", capture_id=capture_id)
    return pair


async def _evaluate_capture_async(
    browser: AsyncBrowser,
    capture: dict[str, Any],
    *,
    config: EvaluateConfig,
    reference_manifest: dict[str, Any],
    candidate_manifest: dict[str, Any] | None,
    candidate_captures_by_id: dict[str, dict[str, Any]],
    candidate_route_inventory: list[dict[str, Any]],
    reference_base_url: str,
    candidate_base_url: str,
    reference_artifact_dir: Path,
    candidate_artifact_dir: Path,
    capture_semaphore: asyncio.Semaphore,
    vlm_semaphore: asyncio.Semaphore,
    dreamsim_semaphore: asyncio.Semaphore,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    capture_id = capture["id"]
    _progress(config, "capture_start", capture_id=capture_id)
    reference_route = _route_for_capture(config.reference_root, capture, serve_mode="static")
    candidate_capture = candidate_captures_by_id.get(capture_id)
    if candidate_manifest is not None and candidate_capture is None:
        candidate_route = {
            "requested_path": capture.get("path") or capture.get("urlPath") or "/index.html",
            "resolved_path": None,
            "file_path": None,
            "confidence": 0.0,
            "status": "missing",
            "method": "candidate_manifest",
            "failure_mode": "candidate_manifest_capture_missing",
        }
    else:
        candidate_route = _route_for_capture(
            config.candidate_root,
            candidate_capture or capture,
            route_inventory=candidate_route_inventory,
            serve_mode=config.candidate_serve_mode,
            candidate_manifest_mapped=candidate_capture is not None,
        )

    async with capture_semaphore:
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
            with _ProgressTimer(config, "reference_capture", capture_id=capture_id):
                reference_artifact, reference_actions = await _capture_reference_async(
                    browser,
                    reference_base_url,
                    capture,
                    reference_manifest,
                    reference_route,
                    reference_artifact_dir,
                    include_visual_blocks=config.include_visual_block,
                    config=config,
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
                if candidate_capture is not None:
                    with _ProgressTimer(config, "candidate_capture", capture_id=capture_id, source="candidate_manifest"):
                        candidate_artifact, candidate_actions = await _capture_candidate_from_manifest_async(
                            browser,
                            candidate_base_url,
                            candidate_capture,
                            reference_manifest,
                            candidate_route,
                            candidate_artifact_dir,
                            include_visual_blocks=config.include_visual_block,
                            config=config,
                        )
                else:
                    with _ProgressTimer(config, "candidate_capture", capture_id=capture_id, source="deterministic"):
                        candidate_artifact, candidate_actions = await _capture_candidate_async(
                            browser,
                            candidate_base_url,
                            capture,
                            reference_manifest,
                            candidate_route,
                            reference_actions,
                            candidate_artifact_dir,
                            include_visual_blocks=config.include_visual_block,
                            config=config,
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
    plan_payload = {
        "capture": capture,
        "candidate_capture": candidate_capture,
        "route_resolution": candidate_route,
        "actions": candidate_actions,
        "coverage": coverage,
    }
    result_payload = {
        "capture": capture,
        "reference_artifact": str(reference_artifact_dir / f"{capture_id}.json"),
        "candidate_artifact": str(candidate_artifact_dir / f"{capture_id}.json"),
        "reference_route": reference_route,
        "candidate_route": candidate_route,
        "candidate_capture_source": "candidate_manifest" if candidate_capture is not None else "deterministic",
        "coverage": coverage,
        "metrics": {"status": "pending"},
        "missing_reason": candidate_artifact.get("missing_reason") or reference_artifact.get("missing_reason"),
    }

    if coverage["score"] <= 0:
        _progress(
            config,
            "capture_metrics_skipped",
            capture_id=capture_id,
            coverage_score=coverage.get("score"),
            reason=coverage.get("reason") or candidate_artifact.get("missing_reason"),
        )
        result_payload["metrics"] = {
            "status": "unsupported",
            "reason": coverage.get("reason") or candidate_artifact.get("missing_reason"),
            "reference_screenshot": reference_artifact.get("screenshot_path"),
            "candidate_screenshot": candidate_artifact.get("screenshot_path"),
        }
    else:
        result_payload["metrics"] = await _run_pair_metrics_async(
            reference_artifact,
            candidate_artifact,
            reference_route,
            candidate_route,
            config,
            vlm_semaphore=vlm_semaphore,
            dreamsim_semaphore=dreamsim_semaphore,
        )

    _progress(
        config,
        "capture_end",
        capture_id=capture_id,
        coverage_score=coverage.get("score"),
        metrics_status=result_payload["metrics"].get("status"),
    )
    return capture_id, plan_payload, result_payload


async def _evaluate_captures_async(
    captures: list[dict[str, Any]],
    *,
    config: EvaluateConfig,
    reference_manifest: dict[str, Any],
    candidate_manifest: dict[str, Any] | None,
    candidate_captures_by_id: dict[str, dict[str, Any]],
    candidate_route_inventory: list[dict[str, Any]],
    reference_base_url: str,
    candidate_base_url: str,
    reference_artifact_dir: Path,
    candidate_artifact_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _progress(
        config,
        "captures_batch_start",
        capture_count=len(captures),
        capture_concurrency=max(1, int(config.capture_concurrency)),
        vlm_concurrency=max(1, int(config.vlm_concurrency)),
        dreamsim_concurrency=1,
    )
    capture_semaphore = asyncio.Semaphore(max(1, int(config.capture_concurrency)))
    vlm_semaphore = asyncio.Semaphore(max(1, int(config.vlm_concurrency)))
    dreamsim_semaphore = asyncio.Semaphore(1)
    tasks: dict[str, asyncio.Task[tuple[str, dict[str, Any], dict[str, Any]]]] = {}
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            async with asyncio.TaskGroup() as task_group:
                for capture in captures:
                    tasks[capture["id"]] = task_group.create_task(
                        _evaluate_capture_async(
                            browser,
                            capture,
                            config=config,
                            reference_manifest=reference_manifest,
                            candidate_manifest=candidate_manifest,
                            candidate_captures_by_id=candidate_captures_by_id,
                            candidate_route_inventory=candidate_route_inventory,
                            reference_base_url=reference_base_url,
                            candidate_base_url=candidate_base_url,
                            reference_artifact_dir=reference_artifact_dir,
                            candidate_artifact_dir=candidate_artifact_dir,
                            capture_semaphore=capture_semaphore,
                            vlm_semaphore=vlm_semaphore,
                            dreamsim_semaphore=dreamsim_semaphore,
                        )
                    )
        finally:
            await browser.close()

    plan_rows: dict[str, Any] = {}
    result_rows: dict[str, Any] = {}
    for capture in captures:
        capture_id, plan_payload, result_payload = tasks[capture["id"]].result()
        plan_rows[capture_id] = plan_payload
        result_rows[capture_id] = result_payload
    _progress(config, "captures_batch_end", capture_count=len(captures))
    return plan_rows, result_rows


def _evaluate_animations_sync(
    animations: list[dict[str, Any]],
    *,
    config: EvaluateConfig,
    reference_manifest: dict[str, Any],
    candidate_manifest: dict[str, Any] | None,
    candidate_animations_by_id: dict[str, dict[str, Any]],
    candidate_route_inventory: list[dict[str, Any]],
    reference_base_url: str,
    candidate_base_url: str,
    reference_artifact_dir: Path,
    candidate_artifact_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    from playwright.sync_api import sync_playwright

    plan_rows: dict[str, Any] = {}
    result_rows: dict[str, Any] = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for animation in animations:
                animation_id = animation["id"]
                reference_route = _route_for_capture(config.reference_root, animation, serve_mode="static")
                candidate_animation = candidate_animations_by_id.get(animation_id)
                if candidate_manifest is not None and candidate_animation is None:
                    candidate_route = {
                        "requested_path": animation.get("path") or animation.get("urlPath") or "/index.html",
                        "resolved_path": None,
                        "file_path": None,
                        "confidence": 0.0,
                        "status": "missing",
                        "method": "candidate_manifest",
                        "failure_mode": "candidate_manifest_animation_missing",
                    }
                else:
                    candidate_route = _route_for_capture(
                        config.candidate_root,
                        candidate_animation or animation,
                        route_inventory=candidate_route_inventory,
                        serve_mode=config.candidate_serve_mode,
                        candidate_manifest_mapped=candidate_animation is not None,
                    )

                if reference_route["status"] != "resolved":
                    reference_artifact = {
                        "animation_id": animation_id,
                        "side": "reference",
                        "missing_reason": reference_route["failure_mode"] or "reference_route_missing",
                        "timeline": [],
                    }
                    reference_target_resolutions = []
                    reference_trigger_signature = None
                    _write_json(reference_artifact_dir / "animations" / animation_id / "timeline.json", reference_artifact)
                else:
                    try:
                        reference_artifact, reference_target_resolutions, reference_trigger_signature = _capture_reference_animation(
                            browser,
                            reference_base_url,
                            animation,
                            reference_manifest,
                            reference_route,
                            reference_artifact_dir,
                        )
                    except Exception as exc:
                        reference_artifact = {
                            "animation_id": animation_id,
                            "side": "reference",
                            "missing_reason": f"reference_animation_capture_failed: {type(exc).__name__}: {exc}",
                            "timeline": [],
                        }
                        reference_target_resolutions = []
                        reference_trigger_signature = None
                        _write_json(reference_artifact_dir / "animations" / animation_id / "timeline.json", reference_artifact)

                if candidate_route["status"] != "resolved":
                    candidate_artifact = {
                        "animation_id": animation_id,
                        "side": "candidate",
                        "missing_reason": candidate_route["failure_mode"] or "candidate_route_missing",
                        "timeline": [],
                    }
                    candidate_target_resolutions = []
                    _write_json(candidate_artifact_dir / "animations" / animation_id / "timeline.json", candidate_artifact)
                else:
                    try:
                        candidate_artifact, candidate_target_resolutions = _capture_candidate_animation(
                            browser,
                            candidate_base_url,
                            candidate_animation or animation,
                            reference_manifest,
                            candidate_route,
                            reference_target_resolutions,
                            reference_trigger_signature,
                            candidate_artifact_dir,
                        )
                    except Exception as exc:
                        candidate_artifact = {
                            "animation_id": animation_id,
                            "side": "candidate",
                            "missing_reason": f"candidate_animation_capture_failed: {type(exc).__name__}: {exc}",
                            "timeline": [],
                        }
                        candidate_target_resolutions = []
                        _write_json(candidate_artifact_dir / "animations" / animation_id / "timeline.json", candidate_artifact)

                plan_rows[animation_id] = {
                    "animation": animation,
                    "candidate_animation": candidate_animation,
                    "route_resolution": candidate_route,
                    "target_resolutions": candidate_target_resolutions,
                }
                result_rows[animation_id] = {
                    "animation": animation,
                    "candidate_animation": candidate_animation,
                    "reference_artifact": str(reference_artifact_dir / "animations" / animation_id / "timeline.json"),
                    "candidate_artifact": str(candidate_artifact_dir / "animations" / animation_id / "timeline.json"),
                    "reference_route": reference_route,
                    "candidate_route": candidate_route,
                    "candidate_animation_source": "candidate_manifest" if candidate_animation is not None else "deterministic",
                    "metrics": _score_animation_pair(reference_artifact, candidate_artifact),
                    "missing_reason": candidate_artifact.get("missing_reason") or reference_artifact.get("missing_reason"),
                }
        finally:
            browser.close()
    return plan_rows, result_rows


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
                _get_metric(metrics, ["pixelmatch", "score"]),
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
    animation_rows = []
    for animation_id, animation in result.get("animations", {}).items():
        metrics = animation.get("metrics", {})
        for target in metrics.get("targets", []) if isinstance(metrics, dict) else []:
            scores = target.get("scores") or {}
            animation_rows.append(
                [
                    animation_id,
                    target.get("target_index"),
                    ",".join(target.get("channels") or []),
                    _get_metric(scores, ["motion", "bbox_iou"]),
                    _get_metric(scores, ["motion", "motion_delta"]),
                    _get_metric(scores, ["color", "target_box_pixelmatch"]),
                    _get_metric(scores, ["color", "cssom_color"]),
                    animation.get("missing_reason") or metrics.get("reason"),
                ]
            )
    summary = result["summary"]
    sections = [
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
                    ["mean_pixelmatch", summary.get("mean_pixelmatch")],
                    ["mean_dreamsim_score", summary.get("mean_dreamsim_score")],
                    ["mean_vlm_overall", summary.get("mean_vlm_overall")],
                    ["mean_html_text_bleu_1", summary.get("mean_html_text_bleu_1")],
                    ["mean_html_text_rouge_1_recall", summary.get("mean_html_text_rouge_1_recall")],
                    ["mean_html_tree_f1", summary.get("mean_html_tree_f1")],
                    ["mean_visual_block_score", summary.get("mean_visual_block_score")],
                    ["animations", summary.get("animation_count")],
                    ["scored_animations", summary.get("scored_animation_count")],
                    ["mean_animation_bbox_iou", summary.get("mean_animation_bbox_iou")],
                    ["mean_animation_motion_delta", summary.get("mean_animation_motion_delta")],
                    ["mean_animation_target_pixelmatch", summary.get("mean_animation_target_pixelmatch")],
                    ["mean_animation_cssom_color", summary.get("mean_animation_cssom_color")],
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
                    "Pixel",
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
    if animation_rows:
        sections.extend(
            [
                "## Animations",
                "",
                _md_table(
                    [
                        "Animation",
                        "Target",
                        "Channels",
                        "BBox IoU",
                        "Motion Delta",
                        "Target Pixel",
                        "CSSOM Color",
                        "Reason",
                    ],
                    animation_rows,
                ),
            ]
        )
    return "\n".join(sections)


def _summarize(result: dict[str, Any]) -> dict[str, Any]:
    captures = result["captures"]
    coverage_scores = [
        float(capture["coverage"]["score"])
        for capture in captures.values()
        if isinstance(capture.get("coverage"), dict)
    ]
    scored_metrics = [capture.get("metrics", {}) for capture in captures.values()]
    size_scores = [_get_metric(metric, ["screenshot_size_match", "score"]) for metric in scored_metrics]
    pixel_scores = [_get_metric(metric, ["pixelmatch", "score"]) for metric in scored_metrics]
    dream_scores = [_get_metric(metric, ["dreamsim", "score"]) for metric in scored_metrics]
    vlm_scores = [_get_metric(metric, ["vlm_judge", "overall"]) for metric in scored_metrics]
    html_text_bleu_scores = [_get_metric(metric, ["html_text", "bleu_1"]) for metric in scored_metrics]
    html_text_rouge_scores = [_get_metric(metric, ["html_text", "rouge_1_recall"]) for metric in scored_metrics]
    html_tree_f1_scores = [_get_metric(metric, ["html_tree", "f1"]) for metric in scored_metrics]
    visual_scores = [_get_metric(metric, ["visual_block", "score"]) for metric in scored_metrics]
    animation_payloads = result.get("animations", {})
    animation_metrics = [payload.get("metrics", {}) for payload in animation_payloads.values()]
    animation_bbox = []
    animation_motion = []
    animation_pixel = []
    animation_cssom = []
    for metric in animation_metrics:
        for target in metric.get("targets", []) if isinstance(metric, dict) else []:
            scores = target.get("scores") or {}
            animation_bbox.append(_get_metric(scores, ["motion", "bbox_iou"]))
            animation_motion.append(_get_metric(scores, ["motion", "motion_delta"]))
            animation_pixel.append(_get_metric(scores, ["color", "target_box_pixelmatch"]))
            animation_cssom.append(_get_metric(scores, ["color", "cssom_color"]))

    def numeric(values: list[Any]) -> list[float]:
        return [float(value) for value in values if isinstance(value, int | float)]

    return {
        "capture_count": len(captures),
        "covered_capture_count": sum(1 for score in coverage_scores if score > 0),
        "missing_capture_count": sum(1 for score in coverage_scores if score <= 0),
        "manifest_coverage_score": _mean(coverage_scores) or 0.0,
        "mean_screenshot_size_match": _mean(numeric(size_scores)),
        "mean_pixelmatch": _mean(numeric(pixel_scores)),
        "mean_dreamsim_score": _mean(numeric(dream_scores)),
        "mean_vlm_overall": _mean(numeric(vlm_scores)),
        "mean_html_text_bleu_1": _mean(numeric(html_text_bleu_scores)),
        "mean_html_text_rouge_1_recall": _mean(numeric(html_text_rouge_scores)),
        "mean_html_tree_f1": _mean(numeric(html_tree_f1_scores)),
        "mean_visual_block_score": _mean(numeric(visual_scores)),
        "animation_count": len(animation_payloads),
        "scored_animation_count": sum(1 for metric in animation_metrics if metric.get("status") == "scored"),
        "mean_animation_bbox_iou": _mean(numeric(animation_bbox)),
        "mean_animation_motion_delta": _mean(numeric(animation_motion)),
        "mean_animation_target_pixelmatch": _mean(numeric(animation_pixel)),
        "mean_animation_cssom_color": _mean(numeric(animation_cssom)),
    }


def evaluate(config: EvaluateConfig) -> dict[str, Any]:
    started = time.time()
    _load_dotenv(config.repo_root / ".env")
    config.candidate_serve_mode = normalize_serve_mode(config.candidate_serve_mode)
    if config.dreamsim_cache_dir is None:
        config.dreamsim_cache_dir = str(config.repo_root / ".cache" / "dreamsim")
    config.output_dir.mkdir(parents=True, exist_ok=True)
    reference_manifest = _read_json(config.reference_manifest)
    captures = [
        capture
        for capture in reference_manifest.get("captures", [])
        if _enabled_capture(capture) and (not config.capture_filter or capture["id"] in config.capture_filter)
    ]
    animations = [
        animation
        for animation in reference_manifest.get("animations", [])
        if _enabled_capture(animation) and (not config.capture_filter or animation["id"] in config.capture_filter)
    ]
    _progress(
        config,
        "evaluator_start",
        capture_count=len(captures),
        animation_count=len(animations),
        reference_root=str(config.reference_root),
        candidate_root=str(config.candidate_root),
        candidate_framework=config.candidate_framework,
        candidate_serve_mode=config.candidate_serve_mode,
        output_dir=str(config.output_dir),
        vlm_model=config.vlm_model,
        skip_vlm=config.skip_vlm,
        skip_dreamsim=config.skip_dreamsim,
        include_visual_block=config.include_visual_block,
    )
    candidate_manifest_result: dict[str, Any] | None = None
    candidate_manifest: dict[str, Any] | None = None
    if config.candidate_manifest is not None:
        candidate_manifest = _read_json(config.candidate_manifest)
        candidate_manifest_result = {
            "backend": "provided",
            "output_path": str(config.candidate_manifest),
            "capture_count": len(candidate_manifest.get("captures") or []),
        }
    elif config.candidate_manifest_planner:
        if config.candidate_manifest_planner != "claude-code":
            raise ValueError(f"Unknown candidate manifest planner: {config.candidate_manifest_planner}")
        with _ProgressTimer(
            config,
            "candidate_manifest_generation",
            planner=config.candidate_manifest_planner,
            model=config.candidate_manifest_model,
        ):
            candidate_manifest_result = generate_candidate_manifest(
                config.reference_manifest,
                config.candidate_root,
                config.output_dir / "generated-candidate-manifest.json",
                model=config.candidate_manifest_model,
                repo_root=config.repo_root,
                reference_root=config.reference_root,
                backend=config.candidate_manifest_planner,
                claude_auth=config.candidate_manifest_claude_auth,
                candidate_framework=config.candidate_framework,
                candidate_serve_mode=config.candidate_serve_mode,
            )
        candidate_manifest = candidate_manifest_result["manifest"]
    candidate_captures_by_id = {
        str(capture["id"]): capture
        for capture in (candidate_manifest or {}).get("captures") or []
        if isinstance(capture, dict) and capture.get("id")
    }
    candidate_animations_by_id = {
        str(animation["id"]): animation
        for animation in (candidate_manifest or {}).get("animations") or []
        if isinstance(animation, dict) and animation.get("id")
    }

    reference_server = StaticServer.start(config.reference_root, serve_mode="static")
    candidate_server = StaticServer.start(config.candidate_root, serve_mode=config.candidate_serve_mode)
    candidate_route_inventory = _route_inventory(config.candidate_root)
    candidate_plan: dict[str, Any] = {
        "reference_root": str(config.reference_root),
        "candidate_root": str(config.candidate_root),
        "candidate_framework": config.candidate_framework,
        "candidate_serve_mode": config.candidate_serve_mode,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "candidate_manifest_planner": candidate_manifest_result,
        "candidate_route_inventory": [
            {key: route.get(key) for key in ("path", "page", "title", "headings", "nav_text")}
            for route in candidate_route_inventory
        ],
        "captures": {},
        "animations": {},
    }
    result: dict[str, Any] = {
        "metadata": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "reference_root": str(config.reference_root),
            "reference_manifest": str(config.reference_manifest),
            "candidate_root": str(config.candidate_root),
            "candidate_framework": config.candidate_framework,
            "candidate_serve_mode": config.candidate_serve_mode,
            "output_dir": str(config.output_dir),
            "vlm_model": config.vlm_model,
            "vlm_enabled": not config.skip_vlm and bool(os.environ.get("OPENAI_API_KEY")),
            "dreamsim_type": config.dreamsim_type,
            "dreamsim_device": _pick_torch_device(config.dreamsim_device),
            "visual_block_device": config.visual_block_device,
            "candidate_manifest_planner": candidate_manifest_result,
            "capture_concurrency": config.capture_concurrency,
            "vlm_concurrency": config.vlm_concurrency,
        },
        "captures": {},
        "animations": {},
    }

    try:
        reference_artifact_dir = config.output_dir / "artifacts" / "reference"
        candidate_artifact_dir = config.output_dir / "artifacts" / "candidate"
        if captures:
            capture_plan_rows, capture_result_rows = asyncio.run(
                _evaluate_captures_async(
                    captures,
                    config=config,
                    reference_manifest=reference_manifest,
                    candidate_manifest=candidate_manifest,
                    candidate_captures_by_id=candidate_captures_by_id,
                    candidate_route_inventory=candidate_route_inventory,
                    reference_base_url=reference_server.base_url,
                    candidate_base_url=candidate_server.base_url,
                    reference_artifact_dir=reference_artifact_dir,
                    candidate_artifact_dir=candidate_artifact_dir,
                )
            )
            candidate_plan["captures"].update(capture_plan_rows)
            result["captures"].update(capture_result_rows)

        if animations:
            animation_plan_rows, animation_result_rows = _evaluate_animations_sync(
                animations,
                config=config,
                reference_manifest=reference_manifest,
                candidate_manifest=candidate_manifest,
                candidate_animations_by_id=candidate_animations_by_id,
                candidate_route_inventory=candidate_route_inventory,
                reference_base_url=reference_server.base_url,
                candidate_base_url=candidate_server.base_url,
                reference_artifact_dir=reference_artifact_dir,
                candidate_artifact_dir=candidate_artifact_dir,
            )
            candidate_plan["animations"].update(animation_plan_rows)
            result["animations"].update(animation_result_rows)
    finally:
        reference_server.close()
        candidate_server.close()

    result["summary"] = _summarize(result)
    result["metadata"]["elapsed_seconds"] = round(time.time() - started, 3)

    _write_json(config.output_dir / "candidate-capture-plan.json", candidate_plan)
    _write_json(config.output_dir / "metrics.json", result)
    (config.output_dir / "functional-report.md").write_text(_build_report(result), encoding="utf-8")
    _progress(
        config,
        "evaluator_end",
        elapsed_seconds=result["metadata"]["elapsed_seconds"],
        manifest_coverage_score=result["summary"].get("manifest_coverage_score"),
        mean_vlm_overall=result["summary"].get("mean_vlm_overall"),
        mean_dreamsim_score=result["summary"].get("mean_dreamsim_score"),
    )
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
        "mean_pixelmatch": summary.get("mean_pixelmatch"),
        "mean_dreamsim_score": summary.get("mean_dreamsim_score"),
        "mean_vlm_overall": summary.get("mean_vlm_overall"),
        "mean_html_text_bleu_1": summary.get("mean_html_text_bleu_1"),
        "mean_html_text_rouge_1_recall": summary.get("mean_html_text_rouge_1_recall"),
        "mean_html_tree_f1": summary.get("mean_html_tree_f1"),
        "mean_visual_block_score": summary.get("mean_visual_block_score"),
        "animations": summary.get("animation_count"),
        "scored_animations": summary.get("scored_animation_count"),
        "mean_animation_bbox_iou": summary.get("mean_animation_bbox_iou"),
        "mean_animation_motion_delta": summary.get("mean_animation_motion_delta"),
        "mean_animation_target_pixelmatch": summary.get("mean_animation_target_pixelmatch"),
        "mean_animation_cssom_color": summary.get("mean_animation_cssom_color"),
        "output_dir": result["metadata"]["output_dir"],
        "metrics": str(Path(result["metadata"]["output_dir"]) / "metrics.json"),
        "report": str(Path(result["metadata"]["output_dir"]) / "functional-report.md"),
        "candidate_capture_plan": str(Path(result["metadata"]["output_dir"]) / "candidate-capture-plan.json"),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
