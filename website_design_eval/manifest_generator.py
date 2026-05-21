from __future__ import annotations

import json
import logging
import os
import re
import asyncio
import inspect
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

from .static_server import StaticServer, normalize_serve_mode


logger = logging.getLogger(__name__)

PathLike = str | os.PathLike[str]
ClaudeAuthMode = str


class ClaudeManifestGenerationError(RuntimeError):
    """Raised when Claude Code fails before returning a usable manifest."""


DEFAULT_MANIFEST = {
    "schemaVersion": 1,
    "site": {"name": "generated-reference-site", "root": "."},
    "outputDir": "./screenshots/reference",
    "cleanOutputDir": True,
    "defaults": {
        "viewport": {"width": 1440, "height": 900},
        "deviceScaleFactor": 1,
        "waitUntil": "networkidle",
        "afterLoadWaitMs": 100,
        "timeoutMs": 30000,
        "screenshot": {
            "fullPage": False,
            "animations": "disabled",
            "caret": "hide",
        },
    },
    "captures": [],
    "animations": [],
}


ACTION_TYPES = {"hover", "click", "focus", "fill", "press", "wait", "waitForSelector", "scroll", "scrollBy"}


MANIFEST_VIEWPORT = {"width": 1440, "height": 900}


BROWSER_INVENTORY_SCRIPT = """
() => {
  const cleanText = (value) => (value || '').replace(/\\s+/g, ' ').trim();
  const cssEscape = (value) => window.CSS && CSS.escape
    ? CSS.escape(value)
    : String(value).replace(/[^a-zA-Z0-9_-]/g, '\\\\$&');
  const attrEscape = (value) => String(value).replace(/\\\\/g, '\\\\\\\\').replace(/"/g, '\\"');
  const stampAttr = 'data-wde-manifest-id';
  const slug = (value) => cleanText(value).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 48) || 'element';
  const isVisible = (el) => {
    const cs = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return cs.display !== 'none' && cs.visibility !== 'hidden' && Number(cs.opacity) !== 0 && rect.width > 0 && rect.height > 0;
  };
  const inferredRole = (el) => {
    const explicit = el.getAttribute('role');
    if (explicit) return explicit;
    const tag = el.tagName.toLowerCase();
    if (tag === 'a' && el.hasAttribute('href')) return 'link';
    if (tag === 'button') return 'button';
    if (tag === 'select') return 'combobox';
    if (tag === 'textarea') return 'textbox';
    if (tag === 'summary') return 'button';
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
  const nthSelector = (el) => {
    const parts = [];
    let current = el;
    while (current && current.nodeType === Node.ELEMENT_NODE && current !== document.documentElement) {
      const tag = current.tagName.toLowerCase();
      if (current.id) {
        parts.unshift(`#${cssEscape(current.id)}`);
        break;
      }
      const siblings = Array.from(current.parentElement?.children || []).filter((sib) => sib.tagName === current.tagName);
      const index = siblings.indexOf(current) + 1;
      parts.unshift(`${tag}:nth-of-type(${index})`);
      current = current.parentElement;
    }
    return parts.join(' > ');
  };
  const selectorCount = (selector) => {
    try { return document.querySelectorAll(selector).length; } catch { return 0; }
  };
  const addCandidate = (candidates, seen, selector, kind) => {
    if (!selector || seen.has(selector)) return;
    seen.add(selector);
    candidates.push({ selector, kind, count: selectorCount(selector) });
  };
  const selectorCandidatesFor = (el) => {
    const tag = el.tagName.toLowerCase();
    const candidates = [];
    const seen = new Set();
    if (el.id) {
      addCandidate(candidates, seen, `#${cssEscape(el.id)}`, 'id');
      addCandidate(candidates, seen, `${tag}#${cssEscape(el.id)}`, 'tag_id');
    }
    for (const attr of Array.from(el.attributes || [])) {
      const name = attr.name;
      const value = attr.value;
      if (!name.startsWith('data-') || name.startsWith('data-wde-') || !value || value.length > 100) continue;
      addCandidate(candidates, seen, `${tag}[${name}="${attrEscape(value)}"]`, 'data_attr');
      addCandidate(candidates, seen, `[${name}="${attrEscape(value)}"]`, 'data_attr');
    }
    const name = el.getAttribute('name');
    if (name) addCandidate(candidates, seen, `${tag}[name="${attrEscape(name)}"]`, 'name');
    const aria = el.getAttribute('aria-label');
    if (aria) addCandidate(candidates, seen, `${tag}[aria-label="${attrEscape(aria)}"]`, 'aria_label');
    const type = el.getAttribute('type');
    if (type && ['button', 'input'].includes(tag)) {
      const value = el.getAttribute('value');
      if (value) addCandidate(candidates, seen, `${tag}[type="${attrEscape(type)}"][value="${attrEscape(value)}"]`, 'type_value');
      const placeholder = el.getAttribute('placeholder');
      if (placeholder) addCandidate(candidates, seen, `${tag}[type="${attrEscape(type)}"][placeholder="${attrEscape(placeholder)}"]`, 'type_placeholder');
    }
    const classes = Array.from(el.classList || []).filter(Boolean).slice(0, 3);
    if (classes.length) {
      addCandidate(candidates, seen, `${tag}.${classes.map(cssEscape).join('.')}`, 'class');
      addCandidate(candidates, seen, `.${classes.map(cssEscape).join('.')}`, 'class');
    }
    const stamp = el.getAttribute(stampAttr);
    if (stamp) addCandidate(candidates, seen, `[${stampAttr}="${attrEscape(stamp)}"]`, 'manifest_stamp');
    addCandidate(candidates, seen, nthSelector(el), 'nth_path');
    return candidates;
  };
  const selectorFor = (el) => {
    const candidates = selectorCandidatesFor(el);
    return candidates.find((candidate) => candidate.count === 1)?.selector
      || candidates[0]?.selector
      || null;
  };
  const all = Array.from(document.querySelectorAll('*'));
  all.forEach((el, index) => {
    if (el.hasAttribute(stampAttr)) return;
    const tag = el.tagName.toLowerCase();
    const label = accessibleName(el) || el.id || el.getAttribute('name') || tag;
    el.setAttribute(stampAttr, `wde-${index}-${tag}-${slug(label)}`);
  });
  const elementPayload = (el) => {
    const rect = el.getBoundingClientRect();
    const tag = el.tagName.toLowerCase();
    const selectorCandidates = selectorCandidatesFor(el);
    return {
      selector: selectorFor(el),
      selector_candidates: selectorCandidates,
      tag,
      role: inferredRole(el),
      type: tag === 'input' ? (el.getAttribute('type') || 'text').toLowerCase() : '',
      id: el.id || '',
      class_name: typeof el.className === 'string' ? el.className : '',
      name: el.getAttribute('name') || '',
      text: cleanText(el.innerText || el.textContent || '').slice(0, 180),
      accessible_name: accessibleName(el).slice(0, 180),
      visible: isVisible(el),
      bbox_px: { x: rect.left + window.scrollX, y: rect.top + window.scrollY, width: rect.width, height: rect.height },
    };
  };
  const links = all
    .filter((el) => el.tagName.toLowerCase() === 'a' && el.getAttribute('href'))
    .map((el) => ({ ...elementPayload(el), href: el.getAttribute('href') || '' }))
    .filter((el) => el.visible || el.text || el.accessible_name)
    .slice(0, 80);
  const controls = all
    .filter((el) => {
      const tag = el.tagName.toLowerCase();
      return ['a', 'button', 'input', 'select', 'textarea', 'summary'].includes(tag)
        || el.hasAttribute('role')
        || el.hasAttribute('tabindex');
    })
    .map(elementPayload)
    .filter((el) => el.visible || el.text || el.accessible_name)
    .slice(0, 80);
  const sections = all
    .filter((el) => {
      const tag = el.tagName.toLowerCase();
      return ['header', 'nav', 'main', 'section', 'article', 'form', 'footer'].includes(tag) || el.id;
    })
    .map((el) => {
      const payload = elementPayload(el);
      const headings = Array.from(el.querySelectorAll('h1,h2,h3')).map((heading) => cleanText(heading.innerText || heading.textContent || '')).filter(Boolean).slice(0, 6);
      return { ...payload, headings };
    })
    .filter((el) => el.visible && (el.id || el.text || el.headings.length))
    .slice(0, 50);
  const interactionCandidates = all
    .filter((el) => {
      const tag = el.tagName.toLowerCase();
      const cls = typeof el.className === 'string' ? el.className.toLowerCase() : '';
      const id = (el.id || '').toLowerCase();
      const role = (el.getAttribute('role') || '').toLowerCase();
      const tokens = `${cls} ${id} ${role}`;
      return ['button', 'input', 'select', 'textarea', 'summary', 'nav'].includes(tag)
        || el.hasAttribute('tabindex')
        || /dropdown|drop|menu|nav|tab|modal|accordion|drawer|popover|tooltip|contact|search|filter|work/.test(tokens);
    })
    .map(elementPayload)
    .filter((el) => el.selector && (el.visible || /dropdown|menu|modal|accordion|popover/.test(`${el.class_name} ${el.id}`.toLowerCase())))
    .slice(0, 80);
  const visibleTexts = [];
  for (const el of all) {
    if (!isVisible(el)) continue;
    const text = cleanText(el.innerText || el.textContent || '');
    if (text) visibleTexts.push(text.slice(0, 220));
  }
  return {
    url: window.location.pathname + window.location.search + window.location.hash,
    title: document.title || '',
    visible_text: cleanText(document.body?.innerText || '').slice(0, 5000),
    visible_texts: Array.from(new Set(visibleTexts)).slice(0, 80),
    viewport: { width: window.innerWidth, height: window.innerHeight, devicePixelRatio: window.devicePixelRatio },
    document: {
      width: Math.max(document.documentElement.scrollWidth, document.body?.scrollWidth || 0, window.innerWidth),
      height: Math.max(document.documentElement.scrollHeight, document.body?.scrollHeight || 0, window.innerHeight),
    },
    links,
    controls,
    sections,
    interaction_candidates: interactionCandidates,
  };
}
"""


MANIFEST_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": True,
    "required": ["schemaVersion", "site", "defaults", "captures"],
    "properties": {
        "schemaVersion": {"type": "integer"},
        "site": {
            "type": "object",
            "additionalProperties": True,
            "properties": {
                "name": {"type": "string"},
                "root": {"type": "string"},
            },
        },
        "outputDir": {"type": "string"},
        "cleanOutputDir": {"type": "boolean"},
        "defaults": {
            "type": "object",
            "additionalProperties": True,
        },
        "captures": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": True,
                "required": ["id", "page", "state", "path"],
                "properties": {
                    "id": {"type": "string"},
                    "weight": {"type": "number"},
                    "page": {"type": "string"},
                    "state": {"type": "string"},
                    "intent": {"type": "string"},
                    "path": {"type": "string"},
                    "viewport": {
                        "type": "object",
                        "additionalProperties": True,
                        "properties": {
                            "width": {"type": "integer"},
                            "height": {"type": "integer"},
                        },
                    },
                    "actions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": True,
                            "required": ["type"],
                            "properties": {
                                "type": {"type": "string", "enum": sorted(ACTION_TYPES)},
                                "selector": {"type": "string"},
                                "value": {"type": "string"},
                                "key": {"type": "string"},
                                "settleMs": {"type": "integer"},
                                "timeoutMs": {"type": "integer"},
                                "state": {"type": "string"},
                                "x": {"type": "number"},
                                "y": {"type": "number"},
                                "ms": {"type": "integer"},
                            },
                        },
                    },
                    "screenshot": {
                        "type": "object",
                        "additionalProperties": True,
                    },
                },
            },
        },
        "animations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": True,
                "required": ["id", "kind", "path", "trigger", "timeline", "targets"],
                "properties": {
                    "id": {"type": "string"},
                    "kind": {"type": "string"},
                    "page": {"type": "string"},
                    "path": {"type": "string"},
                    "viewport": {"type": "object", "additionalProperties": True},
                    "trigger": {"type": "object", "additionalProperties": True},
                    "timeline": {"type": "object", "additionalProperties": True},
                    "targets": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": True,
                            "required": ["name", "selector", "channels"],
                            "properties": {
                                "name": {"type": "string"},
                                "selector": {"type": "string"},
                                "channels": {
                                    "type": "array",
                                    "minItems": 1,
                                    "items": {"type": "string", "enum": ["motion", "color"]},
                                },
                                "track": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                        },
                    },
                },
            },
        },
    },
}


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


def _normalize_anthropic_key() -> None:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    for key in ("CLAUDE_API_KEY", "CLAUDE_CODE_API_KEY", "ANTHROPIC_KEY"):
        value = os.environ.get(key)
        if value:
            os.environ["ANTHROPIC_API_KEY"] = value
            return


def _claude_subprocess_env(auth_mode: ClaudeAuthMode) -> dict[str, str]:
    if auth_mode != "subscription":
        return {}
    return {
        "ANTHROPIC_API_KEY": "",
        "CLAUDE_API_KEY": "",
        "CLAUDE_CODE_API_KEY": "",
        "ANTHROPIC_KEY": "",
    }


def _capture_budget_from_existing_manifest(root: Path) -> int | None:
    manifest_path = root / "screenshot-manifest.json"
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    captures = manifest.get("captures")
    if not isinstance(captures, list):
        return None
    enabled_count = sum(1 for capture in captures if isinstance(capture, dict) and capture.get("enabled", True))
    return enabled_count or None


def _existing_manifest_prior(root: Path) -> dict[str, Any] | None:
    manifest_path = root / "screenshot-manifest.json"
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    captures = []
    for capture in manifest.get("captures") or []:
        if not isinstance(capture, dict) or capture.get("enabled", True) is False:
            continue
        captures.append(
            {
                key: capture[key]
                for key in ("id", "weight", "page", "state", "path", "viewport", "actions", "screenshot", "intent")
                if key in capture
            }
        )
    if not captures:
        return None
    return {
        "source": "reference_root/screenshot-manifest.json",
        "capture_count": len(captures),
        "captures": captures,
    }


def _resolve_capture_budget(_root: Path, max_captures: int | None) -> int | None:
    return max_captures


def _capture_limit_rule(max_captures: int | None) -> str:
    if max_captures is None:
        return "- Include all materially distinct captures and avoid redundant near-duplicates."
    return f"- Keep at most {max_captures} captures."


def _manifest_site_root(root: Path, output_path: Path) -> str:
    relative = os.path.relpath(root, output_path.parent)
    return "." if relative == "." else relative


def _clean_text(value: str | None, *, limit: int = 160) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    return text[:limit]


def _selector_for(element: Any) -> str | None:
    element_id = element.get("id")
    if element_id:
        return f"#{element_id}"
    name = element.get("name")
    if name:
        return f'{element.name}[name="{name}"]'
    classes = element.get("class") or []
    if classes:
        return "." + ".".join(str(item) for item in classes[:3])
    return None


def _html_inventory(root: Path) -> dict[str, Any]:
    pages = []
    for html_path in sorted(root.glob("*.html")):
        soup = BeautifulSoup(html_path.read_text(encoding="utf-8", errors="ignore"), "html.parser")
        rel_path = "/" + html_path.relative_to(root).as_posix()
        title = _clean_text(soup.title.string if soup.title else "", limit=120)
        headings = [
            {"tag": heading.name, "text": _clean_text(heading.get_text(" "), limit=120)}
            for heading in soup.find_all(["h1", "h2", "h3"])[:16]
        ]
        links = [
            {
                "text": _clean_text(link.get_text(" "), limit=80),
                "href": link.get("href") or "",
                "selector": _selector_for(link),
            }
            for link in soup.find_all("a")[:40]
        ]
        controls = [
            {
                "tag": control.name,
                "type": control.get("type") or "",
                "name": control.get("name") or "",
                "id": control.get("id") or "",
                "text": _clean_text(control.get_text(" ") or control.get("placeholder") or control.get("value"), limit=80),
                "selector": _selector_for(control),
            }
            for control in soup.find_all(["button", "input", "select", "textarea"])[:24]
        ]
        sections = [
            {
                "tag": element.name,
                "id": element.get("id") or "",
                "class": " ".join(element.get("class") or []),
                "text": _clean_text(element.get_text(" "), limit=140),
                "selector": _selector_for(element),
            }
            for element in soup.find_all(["section", "main", "article", "form"])[:24]
        ]
        interaction_candidates = [
            {
                "tag": element.name,
                "id": element.get("id") or "",
                "class": " ".join(element.get("class") or []),
                "text": _clean_text(element.get_text(" "), limit=120),
                "selector": _selector_for(element),
            }
            for element in soup.find_all(True)
            if element.get("id")
            or element.get("name")
            or any(
                token in " ".join(element.get("class") or []).lower()
                for token in ["dropdown", "menu", "nav", "tab", "modal", "accordion", "work", "contact"]
            )
        ][:40]
        pages.append(
            {
                "path": rel_path,
                "page": html_path.stem if html_path.stem != "index" else "home",
                "title": title,
                "headings": headings,
                "links": links,
                "controls": controls,
                "sections": sections,
                "interaction_candidates": interaction_candidates,
            }
        )
    return {"root": str(root), "pages": pages}


def _static_route_paths(root: Path) -> list[str]:
    paths = []
    for html_path in sorted(root.glob("*.html")):
        paths.append("/" + html_path.relative_to(root).as_posix())
    return paths or ["/"]


def _unique_route_paths(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for path in paths:
        if not path:
            continue
        normalized = path if path.startswith("/") else f"/{path}"
        if normalized not in seen:
            seen.add(normalized)
            unique.append(normalized)
    return unique


def _page_name_for_path(path: str) -> str:
    parsed = urlparse(path)
    stem = Path(parsed.path or "/").stem
    if not stem or stem == "index":
        return "home"
    return stem


def _normalize_discovered_path(
    base_url: str,
    current_url: str,
    href: str,
    *,
    preserve_fragment: bool = False,
) -> str | None:
    if not href or href.startswith(("mailto:", "tel:", "javascript:")):
        return None
    absolute = urljoin(current_url, href)
    if not preserve_fragment:
        absolute, _fragment = urldefrag(absolute)
    parsed = urlparse(absolute)
    base = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or parsed.netloc != base.netloc:
        return None
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    if preserve_fragment and parsed.fragment:
        path = f"{path}#{parsed.fragment}"
    return path


def _browser_inventory(
    root: Path,
    *,
    max_routes: int = 24,
    serve_mode: str = "static",
    route_paths: list[str] | None = None,
) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    serve_mode = normalize_serve_mode(serve_mode)
    server = StaticServer.start(root, serve_mode=serve_mode)
    route_queue = _unique_route_paths([*(route_paths or []), *_static_route_paths(root)])
    seen = set(route_queue)
    pages: list[dict[str, Any]] = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = browser.new_context(
                    viewport=MANIFEST_VIEWPORT,
                    device_scale_factor=1,
                )
                page = context.new_page()
                try:
                    index = 0
                    while index < len(route_queue) and len(pages) < max_routes:
                        route_path = route_queue[index]
                        index += 1
                        url = f"{server.base_url.rstrip('/')}/{route_path.lstrip('/')}"
                        try:
                            page.goto(url, wait_until="networkidle", timeout=30000)
                            page.wait_for_timeout(100)
                            observed = page.evaluate(BROWSER_INVENTORY_SCRIPT)
                        except Exception as exc:
                            pages.append(
                                {
                                    "path": route_path,
                                    "page": _page_name_for_path(route_path),
                                    "status": "error",
                                    "error": f"{type(exc).__name__}: {exc}",
                                    "links": [],
                                    "controls": [],
                                    "sections": [],
                                    "interaction_candidates": [],
                                }
                            )
                            continue

                        links = observed.get("links") or []
                        for link in links:
                            discovered = _normalize_discovered_path(
                                server.base_url,
                                page.url,
                                str(link.get("href") or ""),
                                preserve_fragment=serve_mode == "spa",
                            )
                            if discovered and discovered not in seen and len(seen) < max_routes:
                                seen.add(discovered)
                                route_queue.append(discovered)

                        pages.append(
                            {
                                "path": route_path,
                                "page": _page_name_for_path(route_path),
                                "status": "ok",
                                **observed,
                            }
                        )
                finally:
                    context.close()
            finally:
                browser.close()
    finally:
        server.close()

    return {
        "root": str(root),
        "source": "playwright_rendered_browser_state",
        "serve_mode": serve_mode,
        "viewport": MANIFEST_VIEWPORT,
        "pages": pages,
    }


def _inventory_for_prompt(root: Path) -> dict[str, Any]:
    try:
        inventory = _browser_inventory(root)
        if any(page.get("status") == "ok" for page in inventory.get("pages", [])):
            prior = _existing_manifest_prior(root)
            if prior:
                inventory["existing_manifest_prior"] = prior
            return inventory
    except Exception as exc:
        inventory = {
            **_html_inventory(root),
            "source": "static_html_fallback",
            "browser_error": f"{type(exc).__name__}: {exc}",
        }
        prior = _existing_manifest_prior(root)
        if prior:
            inventory["existing_manifest_prior"] = prior
        return inventory
    inventory = {
        **_html_inventory(root),
        "source": "static_html_fallback",
        "browser_error": "no browser-rendered pages discovered",
    }
    prior = _existing_manifest_prior(root)
    if prior:
        inventory["existing_manifest_prior"] = prior
    return inventory


def _inventory_paths(inventory: dict[str, Any]) -> set[str]:
    return {
        str(page.get("path"))
        for page in inventory.get("pages", [])
        if isinstance(page, dict) and page.get("path")
    }


def _inventory_selectors_by_path(inventory: dict[str, Any]) -> dict[str, set[str]]:
    selectors_by_path: dict[str, set[str]] = {}
    for page in inventory.get("pages", []):
        if not isinstance(page, dict) or not page.get("path"):
            continue
        selectors = selectors_by_path.setdefault(str(page["path"]), set())
        for key in ("links", "controls", "sections", "interaction_candidates"):
            for element in page.get(key) or []:
                if isinstance(element, dict) and element.get("selector"):
                    selectors.add(str(element["selector"]))
                if isinstance(element, dict):
                    for candidate in element.get("selector_candidates") or []:
                        if isinstance(candidate, dict) and candidate.get("selector"):
                            selectors.add(str(candidate["selector"]))
                if isinstance(element, dict) and element.get("id"):
                    selectors.add(f"#{element['id']}")
                if isinstance(element, dict) and element.get("name") and element.get("tag"):
                    selectors.add(f"{element['tag']}[name=\"{element['name']}\"]")
                    selectors.add(f"{element['tag']}[name='{element['name']}']")
                if isinstance(element, dict) and element.get("class_name"):
                    classes = [token for token in str(element["class_name"]).split() if token]
                    if classes:
                        selectors.add("." + ".".join(classes[:3]))
                        if element.get("tag"):
                            selectors.add(f"{element['tag']}." + ".".join(classes[:3]))
    return selectors_by_path


def _inventory_selector_counts_by_path(inventory: dict[str, Any]) -> dict[str, dict[str, int]]:
    counts_by_path: dict[str, dict[str, int]] = {}
    for page in inventory.get("pages", []):
        if not isinstance(page, dict) or not page.get("path"):
            continue
        counts = counts_by_path.setdefault(str(page["path"]), {})
        for key in ("links", "controls", "sections", "interaction_candidates"):
            for element in page.get(key) or []:
                if not isinstance(element, dict):
                    continue
                selector = element.get("selector")
                if selector and selector not in counts:
                    counts[str(selector)] = 1
                for candidate in element.get("selector_candidates") or []:
                    if not isinstance(candidate, dict) or not candidate.get("selector"):
                        continue
                    try:
                        counts[str(candidate["selector"])] = int(candidate.get("count") or 0)
                    except (TypeError, ValueError):
                        counts[str(candidate["selector"])] = 0
    return counts_by_path


def _fallback_manifest(root: Path, *, max_captures: int | None) -> dict[str, Any]:
    manifest = json.loads(json.dumps(DEFAULT_MANIFEST))
    manifest["site"]["name"] = root.name
    captures = []
    html_paths = sorted(root.glob("*.html"))
    if max_captures is not None:
        html_paths = html_paths[:max_captures]
    for html_path in html_paths:
        page = html_path.stem if html_path.stem != "index" else "home"
        captures.append(
            {
                "id": f"{page}.desktop.full",
                "weight": 1.0,
                "page": page,
                "state": "full page",
                "path": "/" + html_path.relative_to(root).as_posix(),
                "viewport": {"width": 1440, "height": 900},
                "screenshot": {"fullPage": True},
            }
        )
    manifest["captures"] = captures
    return manifest


def _selector_exists(root: Path, path: str, selector: str) -> bool:
    try:
        html_path = root / path.lstrip("/")
        soup = BeautifulSoup(html_path.read_text(encoding="utf-8", errors="ignore"), "html.parser")
        return bool(soup.select(selector))
    except Exception:
        return False


def _selector_unique_in_source(root: Path, path: str, selector: str) -> bool:
    if "data-wde-manifest-id" in selector:
        return False
    try:
        html_path = root / path.lstrip("/")
        soup = BeautifulSoup(html_path.read_text(encoding="utf-8", errors="ignore"), "html.parser")
        return len(soup.select(selector)) == 1
    except Exception:
        return False


def _rendered_path_accessible(root: Path, path: str) -> bool:
    try:
        from playwright.sync_api import sync_playwright

        server = StaticServer.start(root)
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    context = browser.new_context(
                        viewport=MANIFEST_VIEWPORT,
                        device_scale_factor=1,
                    )
                    page = context.new_page()
                    response = page.goto(
                        f"{server.base_url.rstrip('/')}/{path.lstrip('/')}",
                        wait_until="networkidle",
                        timeout=30000,
                    )
                    page.wait_for_timeout(100)
                    if response is not None and response.status >= 400:
                        return False
                    return bool(page.evaluate("() => document.body !== null"))
                finally:
                    browser.close()
        finally:
            server.close()
    except Exception:
        return False


def _rendered_selector_count(root: Path, path: str, selector: str) -> int | None:
    try:
        from playwright.sync_api import sync_playwright

        server = StaticServer.start(root)
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    context = browser.new_context(
                        viewport=MANIFEST_VIEWPORT,
                        device_scale_factor=1,
                    )
                    page = context.new_page()
                    page.goto(f"{server.base_url.rstrip('/')}/{path.lstrip('/')}", wait_until="networkidle", timeout=30000)
                    page.wait_for_timeout(100)
                    try:
                        return int(
                            page.evaluate(
                                "(selector) => document.querySelectorAll(selector).length",
                                selector,
                            )
                        )
                    except Exception:
                        return int(page.locator(selector).count())
                finally:
                    browser.close()
        finally:
            server.close()
    except Exception:
        return None


def _context_block(context: dict[str, Any] | None) -> str:
    if not context:
        return ""
    return f"""

Additional generation context:
{json.dumps(context, indent=2, sort_keys=True)}
""".rstrip()


def _manifest_prompt(inventory: dict[str, Any], max_captures: int | None, context: dict[str, Any] | None = None) -> str:
    return f"""
Create a screenshot capture manifest for evaluating whether a candidate website reproduces this reference website.

The inventory below was produced from a Playwright-rendered browser state wherever possible. Treat the rendered browser inventory as the source of truth, not raw source files. For each page, the inventory includes visible text, rendered links, controls, sections, interaction candidates, selectors, and layout boxes.
{_context_block(context)}

Return strict JSON only. Use this schema:
{{
  "schemaVersion": 1,
  "site": {{"name": "...", "root": "."}},
  "outputDir": "./screenshots/reference",
  "cleanOutputDir": true,
  "defaults": {{
    "viewport": {{"width": 1440, "height": 900}},
    "deviceScaleFactor": 1,
    "waitUntil": "networkidle",
    "afterLoadWaitMs": 100,
    "timeoutMs": 30000,
    "screenshot": {{"fullPage": false, "animations": "disabled", "caret": "hide"}}
  }},
  "captures": [
    {{
      "id": "page.desktop.full",
      "weight": 1.0,
      "page": "page",
      "state": "full page",
      "intent": "Capture the full rendered page",
      "path": "/page.html",
      "viewport": {{"width": 1440, "height": 900}},
      "actions": [{{"type": "hover", "selector": ".dropdown", "settleMs": 250}}],
      "screenshot": {{"fullPage": true}}
    }}
  ],
  "animations": [
    {{
      "id": "page.card-hover",
      "kind": "animation",
      "page": "page",
      "path": "/page.html",
      "viewport": {{"width": 1440, "height": 900}},
      "trigger": {{"type": "hover", "selector": ".card", "settleBeforeMs": 0}},
      "timeline": {{"durationMs": 300, "samplesMs": [0, 100, 200, 300], "recordFrames": true, "recordBoundingBoxes": true, "recordComputedStyles": true}},
      "targets": [
        {{"name": "animated card", "selector": ".card", "channels": ["motion"], "track": ["transform"]}}
      ]
    }}
  ]
}}

Rules:
- Use only paths shown in the browser-rendered inventory.
- Use only selectors shown in the browser-rendered inventory. Do not invent ids/classes.
- Treat each capture as a desired browser-visible state. The action list is only the reproducible route to that state for this source website.
- If an existing/prior manifest is used as intent guidance, preserve the target state, not the exact prior action or selector.
- Pick the action that actually opens/reveals the state in this website. Do not use hover just because the state is called a dropdown/menu.
- For disclosure widgets, details/summary controls, buttons, tabs, accordions, filters, and toggles, prefer click unless the rendered inventory or source clearly shows hover is required.
- Use hover only for genuine hover-reveal or hover-style states where click would not be the natural control semantics.
- Example: if the prior/oracle state is "Work dropdown open" reached by hovering `.dropdown`, but this website uses `<summary>Work</summary>` or a menu button, use click on the summary/button if that reveals the same Work menu state.
- Example: if the prior/oracle state is "filter panel expanded" reached by clicking a button, but this website exposes the panel through a tab or accordion control, use the tab/accordion action that reaches the expanded filter-panel state.
- For action selectors, prefer a selector_candidates entry with count=1. Prefer data_attr, id, name, and aria_label selectors over class or nth_path selectors.
- data-wde-manifest-id selectors are deterministic oracle replay stamps and are acceptable when no semantic unique selector exists.
- Avoid nth_path selectors unless they are the only unique selector candidate.
- If existing_manifest_prior is present, treat it as the intent/coverage guide. Preserve the same broad capture intentions unless the rendered browser inventory proves a selector/path is invalid.
- Include full-page desktop captures for important unique pages.
- Add interaction/state captures only when the state reveals substantial hidden content, changes the visible layout, or changes the visible data/content being evaluated.
- Hidden navigation panels such as dropdowns, megamenus, and submenus are high-value interaction states when they reveal link groups or structured navigation content. Include a minimal representative set of these before lower-value filter, focus, or hover-style states.
- Avoid redundant or duplicate state types. For example, do not capture the highlighted state for every item in a dropdown or every repeated hover/focus variant.
- Generate the minimal set of states that covers the most information.
- Do not stop after full-page captures when important hidden or stateful surfaces exist.
{_capture_limit_rule(max_captures)}
- Use weights: full unique page = 1.0, major hidden surface or alternate layout = 0.5, representative filter/tab/accordion state = 0.25 to 0.5.
- Use only these actions when needed: hover, click, focus, scroll, waitForSelector.
- For scroll actions prefer rendered section selectors like "#work" or a stable section id.
- For focus actions prefer inputs with id/name selectors.
- Add a short intent string for each non-default state capture.
- Do not include disabled captures.
- The accepted_concept is the source of truth for required animation captures.
  If accepted_concept.animations is non-empty, copy every declared animation id
  into the manifest's top-level animations array.
- Resolve each declared concept animation to one concrete rendered trigger
  selector and one concrete rendered target selector from the Playwright
  inventory. If a concept selector matches repeated elements, choose one visible
  instance and use its unique selector candidate; anchor descendant targets
  under that same instance.
- Convert concept trigger variants into manifest trigger fields: trigger.on or
  trigger.selector becomes trigger.selector; trigger.event or trigger.type
  becomes trigger.type.
- Use kind="animation" for every animation entry.
- For V1 animations, use only channels "motion" and "color". Motion animations
  need target selectors and timeline samples. Color animations also need track
  entries for computed color properties such as background-color, color, and
  border colors.

Browser-rendered inventory:
{json.dumps(inventory, indent=2)}
""".strip()


def _claude_code_prompt(
    inventory: dict[str, Any],
    max_captures: int | None,
    output_path: Path,
    context: dict[str, Any] | None = None,
) -> str:
    return f"""
You are generating a screenshot manifest for a website design evaluation task.

The caller has already rendered the reference website in Playwright and extracted browser-observed routes, visible text, controls, sections, interaction candidates, selectors, and layout boxes. Use this browser-rendered inventory as the source of truth. You may inspect files with Read, Glob, and Grep if you need extra context, but do not write files and do not prefer raw source over rendered state.
{_context_block(context)}

Your final answer must be one JSON object only; the caller will write it to:

{output_path}

The manifest must follow this schema:
{{
  "schemaVersion": 1,
  "site": {{"name": "...", "root": "."}},
  "outputDir": "./screenshots/reference",
  "cleanOutputDir": true,
  "defaults": {{
    "viewport": {{"width": 1440, "height": 900}},
    "deviceScaleFactor": 1,
    "waitUntil": "networkidle",
    "afterLoadWaitMs": 100,
    "timeoutMs": 30000,
    "screenshot": {{"fullPage": false, "animations": "disabled", "caret": "hide"}}
  }},
  "captures": [],
  "animations": []
}}

Capture rules:
- If existing_manifest_prior is present, treat it as the intent/coverage guide. Preserve the same broad capture intentions unless the rendered browser inventory proves a selector/path is invalid.
- Treat each capture as a desired browser-visible state. The action list is only the reproducible route to that state for this source website.
- If an existing/prior manifest is used as intent guidance, preserve the target state, not the exact prior action or selector.
- Pick the action that actually opens/reveals the state in this website. Do not use hover just because the state is called a dropdown/menu.
- For disclosure widgets, details/summary controls, buttons, tabs, accordions, filters, and toggles, prefer click unless the rendered inventory or source clearly shows hover is required.
- Use hover only for genuine hover-reveal or hover-style states where click would not be the natural control semantics.
- Example: if the prior/oracle state is "Work dropdown open" reached by hovering `.dropdown`, but this website uses `<summary>Work</summary>` or a menu button, use click on the summary/button if that reveals the same Work menu state.
- Example: if the prior/oracle state is "filter panel expanded" reached by clicking a button, but this website exposes the panel through a tab or accordion control, use the tab/accordion action that reaches the expanded filter-panel state.
- Include full-page desktop captures for important unique pages.
- Add interaction/state captures only when the state reveals substantial hidden content, changes the visible layout, or changes the visible data/content being evaluated.
- Hidden navigation panels such as dropdowns, megamenus, and submenus are high-value interaction states when they reveal link groups or structured navigation content. Include a minimal representative set of these before lower-value filter, focus, or hover-style states.
- Avoid redundant or duplicate state types. For example, do not capture the highlighted state for every item in a dropdown or every repeated hover/focus variant.
- Generate the minimal set of states that covers the most information.
- For action selectors, prefer a selector_candidates entry with count=1. Prefer data_attr, id, name, and aria_label selectors over class or nth_path selectors.
- data-wde-manifest-id selectors are deterministic oracle replay stamps and are acceptable when no semantic unique selector exists.
- Avoid nth_path selectors unless they are the only unique selector candidate.
- Do not stop after full-page captures when important hidden or stateful surfaces exist.
{_capture_limit_rule(max_captures)}
- Use weights: full unique page = 1.0, major hidden surface or alternate layout = 0.5, representative filter/tab/accordion state = 0.25 to 0.5.
- Use only these actions: hover, click, focus, scroll, waitForSelector.
- Use only paths and selectors present in the rendered inventory.
- Add a short intent string for each non-default state capture.
- Do not include disabled captures.
- The accepted_concept is the source of truth for required animation captures.
  If accepted_concept.animations is non-empty, copy every declared animation id
  into the manifest's top-level animations array.
- Resolve each declared concept animation to one concrete rendered trigger
  selector and one concrete rendered target selector from the Playwright
  inventory. If a concept selector matches repeated elements, choose one visible
  instance and use its unique selector candidate; anchor descendant targets
  under that same instance.
- Convert concept trigger variants into manifest trigger fields: trigger.on or
  trigger.selector becomes trigger.selector; trigger.event or trigger.type
  becomes trigger.type.
- Use kind="animation" for every animation entry.
- For V1 animations, use only channels "motion" and "color". Motion animations
  need target selectors and timeline samples. Color animations also need track
  entries for computed color properties such as background-color, color, and
  border colors.
- Return strict JSON only. No markdown, no commentary.

Browser-rendered inventory:
{json.dumps(inventory, indent=2)}
""".strip()


def _extract_json_object(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("Manifest response was not a JSON object")
    return parsed


def _claude_options(options_type: type, **kwargs: Any) -> Any:
    parameters = inspect.signature(options_type).parameters
    return options_type(**{key: value for key, value in kwargs.items() if key in parameters})


def _claude_result_error_text(message: Any) -> str | None:
    if not getattr(message, "is_error", False):
        return None
    parts: list[str] = []
    result = getattr(message, "result", None)
    if result:
        parts.append(str(result))
    errors = getattr(message, "errors", None)
    if isinstance(errors, list):
        parts.extend(str(error) for error in errors if error)
    elif errors:
        parts.append(str(errors))
    api_error_status = getattr(message, "api_error_status", None)
    if api_error_status:
        parts.append(f"api_error_status={api_error_status}")
    return "; ".join(parts).strip() or "Claude Code returned an error result"


def _write_manifest_diagnostics(output_path: Path, diagnostics: dict[str, Any]) -> Path:
    diagnostics_path = output_path.with_name(f"{output_path.stem}.diagnostics.json")
    diagnostics_path.write_text(json.dumps(diagnostics, indent=2, sort_keys=False), encoding="utf-8")
    return diagnostics_path


def _is_transient_claude_error(error_text: str) -> bool:
    lowered = error_text.lower()
    return any(
        marker in lowered
        for marker in (
            "529",
            "overloaded",
            "api is at capacity",
            "temporarily unavailable",
            "rate limit",
            "rate_limit",
        )
    )


def _json_safe(value: Any, *, max_text: int = 20000) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return value if len(value) <= max_text else value[:max_text] + f"...[truncated {len(value) - max_text} chars]"
    if isinstance(value, dict):
        return {str(key): _json_safe(item, max_text=max_text) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item, max_text=max_text) for item in value]
    if hasattr(value, "model_dump"):
        try:
            return _json_safe(value.model_dump(), max_text=max_text)
        except Exception:
            pass
    return _json_safe(repr(value), max_text=max_text)


def _claude_message_diagnostic(message: Any) -> dict[str, Any]:
    diagnostic: dict[str, Any] = {
        "ts": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
        "message_class": type(message).__name__,
    }
    for attr in (
        "type",
        "subtype",
        "role",
        "is_error",
        "result",
        "errors",
        "api_error_status",
        "stop_reason",
        "usage",
        "structured_output",
    ):
        if hasattr(message, attr):
            value = getattr(message, attr)
            if attr == "structured_output":
                diagnostic["has_structured_output"] = value is not None
                if value is not None:
                    diagnostic["structured_output_preview"] = _json_safe(value, max_text=4000)
            else:
                diagnostic[attr] = _json_safe(value, max_text=4000)

    content = getattr(message, "content", None)
    if content is not None:
        blocks = content if isinstance(content, list) else [content]
        diagnostic["content"] = []
        for block in blocks:
            block_diag = {"block_class": type(block).__name__}
            for attr in ("type", "name", "id", "text", "input"):
                if hasattr(block, attr):
                    block_diag[attr] = _json_safe(getattr(block, attr), max_text=8000)
            if len(block_diag) == 1:
                block_diag["repr"] = _json_safe(repr(block), max_text=8000)
            diagnostic["content"].append(block_diag)
    else:
        diagnostic["repr"] = _json_safe(repr(message), max_text=8000)
    return diagnostic


def _append_claude_transcript(transcript_path: Path | None, event: dict[str, Any]) -> None:
    if transcript_path is None:
        return
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    with transcript_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=False, ensure_ascii=False) + "\n")


async def _query_claude_manifest(
    prompt: str,
    options: Any,
    *,
    query: Any,
    AssistantMessage: type,
    ResultMessage: type,
    TextBlock: type,
    transcript_path: Path | None = None,
    transcript_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    chunks: list[str] = []
    structured_output: Any | None = None
    result_error: str | None = None
    context = transcript_context or {}
    _append_claude_transcript(
        transcript_path,
        {
            "ts": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "event": "query_start",
            **_json_safe(context, max_text=4000),
        },
    )
    try:
        async for message in query(prompt=prompt, options=options):
            _append_claude_transcript(
                transcript_path,
                {
                    "event": "message",
                    **_json_safe(context, max_text=4000),
                    "message": _claude_message_diagnostic(message),
                },
            )
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        chunks.append(block.text)
                    elif hasattr(block, "text"):
                        chunks.append(str(block.text))
            elif isinstance(message, ResultMessage):
                result_error = _claude_result_error_text(message) or result_error
                if getattr(message, "structured_output", None) is not None:
                    structured_output = message.structured_output
                if getattr(message, "result", None) and not result_error:
                    chunks.append(str(message.result))
    except Exception as exc:
        _append_claude_transcript(
            transcript_path,
            {
                "ts": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
                "event": "query_exception",
                **_json_safe(context, max_text=4000),
                "exception_class": type(exc).__name__,
                "exception": str(exc),
                "result_error": result_error,
            },
        )
        if result_error:
            raise ClaudeManifestGenerationError(result_error) from exc
        if _is_transient_claude_error(str(exc)):
            raise ClaudeManifestGenerationError(str(exc)) from exc
        raise

    if result_error:
        raise ClaudeManifestGenerationError(result_error)
    if isinstance(structured_output, dict):
        _append_claude_transcript(
            transcript_path,
            {
                "ts": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
                "event": "query_success",
                **_json_safe(context, max_text=4000),
                "source": "structured_output",
            },
        )
        return structured_output
    raw = "\n".join(chunks).strip()
    parsed = _extract_json_object(raw)
    _append_claude_transcript(
        transcript_path,
        {
            "ts": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "event": "query_success",
            **_json_safe(context, max_text=4000),
            "source": "text_chunks",
        },
    )
    return parsed


async def _generate_manifest_claude_code_async(
    root: Path,
    output_path: Path,
    *,
    model: str,
    max_captures: int | None,
    inventory: dict[str, Any],
    auth_mode: ClaudeAuthMode,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, query

    if not inventory["pages"]:
        raise ValueError(f"No browser-rendered pages found in {root}")

    options = _claude_options(
        ClaudeAgentOptions,
        system_prompt=(
            "You are a precise website evaluation manifest generator. "
            "You inspect local reference website files and return only valid JSON."
        ),
        model=model,
        cwd=root,
        max_turns=8,
        tools=["Read", "LS", "Glob", "Grep"],
        allowed_tools=["Read", "LS", "Glob", "Grep"],
        disallowed_tools=["Bash", "Write", "Edit", "MultiEdit", "NotebookEdit"],
        setting_sources=[],
        output_format={"type": "json_schema", "schema": MANIFEST_OUTPUT_SCHEMA},
        env=_claude_subprocess_env(auth_mode),
    )

    prompt = _claude_code_prompt(inventory, max_captures=max_captures, output_path=output_path, context=context)
    max_attempts = 3
    parsed: dict[str, Any] | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            parsed = await _query_claude_manifest(
                prompt,
                options,
                query=query,
                AssistantMessage=AssistantMessage,
                ResultMessage=ResultMessage,
                TextBlock=TextBlock,
            )
            break
        except ClaudeManifestGenerationError as exc:
            error_text = str(exc)
            if attempt < max_attempts and _is_transient_claude_error(error_text):
                await asyncio.sleep(2 ** attempt)
                continue
            if _is_transient_claude_error(error_text):
                raise ClaudeManifestGenerationError(
                    f"Claude Code manifest generation failed after {max_attempts} attempts: {error_text}"
                ) from exc
            raise

    if parsed is None:
        raise RuntimeError("Claude Code manifest generation did not return a manifest")
    manifest = _sanitize_manifest_with_inventory(root, parsed, max_captures=max_captures, inventory=inventory)
    diagnostics = manifest.pop("__diagnostics", {})
    manifest["site"]["root"] = _manifest_site_root(root, output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, indent=2, sort_keys=False), encoding="utf-8")
    diagnostics_path = _write_manifest_diagnostics(output_path, diagnostics)
    logger.info(
        "manifest generated root=%s backend=claude-code raw_animations=%s kept_animations=%s diagnostics=%s",
        root,
        diagnostics.get("raw_animation_count"),
        diagnostics.get("sanitized_animation_count"),
        diagnostics_path,
    )
    return {
        "manifest": manifest,
        "output_path": str(output_path),
        "diagnostics_path": str(diagnostics_path),
        "diagnostics": diagnostics,
        "model": model,
        "backend": "claude-code",
        "auth_mode": auth_mode,
        "page_count": len(inventory["pages"]),
        "inventory_source": inventory.get("source"),
        "capture_count": len(manifest["captures"]),
        "capture_budget": max_captures,
    }


def _sanitize_manifest(root: Path, raw: dict[str, Any], *, max_captures: int | None) -> dict[str, Any]:
    return _sanitize_manifest_with_inventory(root, raw, max_captures=max_captures, inventory=None)


def _sanitize_manifest_with_inventory(
    root: Path,
    raw: dict[str, Any],
    *,
    max_captures: int | None,
    inventory: dict[str, Any] | None,
) -> dict[str, Any]:
    manifest = json.loads(json.dumps(DEFAULT_MANIFEST))
    manifest["site"]["name"] = str((raw.get("site") or {}).get("name") or root.name)
    raw_defaults = raw.get("defaults")
    if isinstance(raw_defaults, dict):
        manifest["defaults"].update({key: value for key, value in raw_defaults.items() if key != "screenshot"})
        if isinstance(raw_defaults.get("screenshot"), dict):
            manifest["defaults"]["screenshot"].update(raw_defaults["screenshot"])

    inventory_paths = _inventory_paths(inventory or {})
    inventory_selectors = _inventory_selectors_by_path(inventory or {})
    inventory_selector_counts = _inventory_selector_counts_by_path(inventory or {})
    rendered_selector_count_cache: dict[tuple[str, str], int | None] = {}

    def rendered_selector_count(path: str, selector: str) -> int | None:
        cache_key = (path, selector)
        if cache_key not in rendered_selector_count_cache:
            rendered_selector_count_cache[cache_key] = _rendered_selector_count(root, path, selector)
        return rendered_selector_count_cache[cache_key]

    def selector_status(path: str, selector: str | None) -> dict[str, Any]:
        if not selector:
            return {"ok": False, "reason": "missing_selector", "selector": selector}
        selector_count = inventory_selector_counts.get(path, {}).get(selector)
        rendered_count = None
        if selector_count is None:
            rendered_count = rendered_selector_count(path, selector)
            if rendered_count is not None:
                selector_count = rendered_count
        selector_known = (
            selector in inventory_selectors.get(path, set())
            or _selector_exists(root, path, selector)
            or (rendered_count is not None and rendered_count > 0)
        )
        selector_unique = selector_count == 1 or (selector_count is None and _selector_unique_in_source(root, path, selector))
        if not selector_known:
            return {"ok": False, "reason": "selector_not_found", "selector": selector, "selector_count": selector_count}
        if not selector_unique:
            return {"ok": False, "reason": "selector_not_unique", "selector": selector, "selector_count": selector_count}
        return {
            "ok": True,
            "selector": selector,
            "selector_count": selector_count,
            "source": "rendered_dom" if rendered_count is not None else "inventory_or_source",
        }

    captures = []
    seen_ids = set()
    rendered_path_cache: dict[str, bool] = {}
    for item in raw.get("captures") or []:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "")
        if not path.startswith("/"):
            path = "/" + path
        browser_path_known = path in inventory_paths
        file_path_known = (root / path.lstrip("/")).exists()
        rendered_path_known = False
        if not browser_path_known and not file_path_known and "#" in path:
            if path not in rendered_path_cache:
                rendered_path_cache[path] = _rendered_path_accessible(root, path)
            rendered_path_known = rendered_path_cache[path]
        if not browser_path_known and not file_path_known and not rendered_path_known:
            continue
        capture_id = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(item.get("id") or "")).strip("-")
        if not capture_id:
            page_name = Path(path).stem if Path(path).stem != "index" else "home"
            capture_id = f"{page_name}.desktop.{len(captures) + 1}"
        original_id = capture_id
        suffix = 2
        while capture_id in seen_ids:
            capture_id = f"{original_id}-{suffix}"
            suffix += 1
        seen_ids.add(capture_id)

        capture = {
            "id": capture_id,
            "weight": float(item.get("weight") if isinstance(item.get("weight"), int | float) else 1.0),
            "page": str(item.get("page") or (Path(path).stem if Path(path).stem != "index" else "home")),
            "state": str(item.get("state") or "full page"),
            "path": path,
            "viewport": item.get("viewport") if isinstance(item.get("viewport"), dict) else {"width": 1440, "height": 900},
            "screenshot": item.get("screenshot") if isinstance(item.get("screenshot"), dict) else {"fullPage": True},
        }
        if item.get("intent"):
            capture["intent"] = str(item["intent"])
        raw_actions = item.get("actions") or []
        actions = []
        raw_state_action_count = 0
        kept_state_action_count = 0
        raw_effect_action_count = 0
        kept_effect_action_count = 0
        for action in raw_actions:
            if not isinstance(action, dict) or action.get("type") not in ACTION_TYPES:
                continue
            cleaned = {key: value for key, value in action.items() if key in {"type", "selector", "value", "key", "settleMs", "state", "timeoutMs", "x", "y", "ms"}}
            if cleaned["type"] in {"hover", "click", "focus", "scroll", "waitForSelector"} and not cleaned.get("selector"):
                continue
            selector = str(cleaned.get("selector") or "")
            if cleaned["type"] not in {"wait", "press", "scrollBy"}:
                raw_state_action_count += 1
            if cleaned["type"] in {"hover", "click", "focus", "fill", "scroll", "scrollBy", "press"}:
                raw_effect_action_count += 1
            if selector:
                if not selector_status(path, selector).get("ok"):
                    continue
            if cleaned["type"] not in {"wait", "press", "scrollBy"}:
                kept_state_action_count += 1
            if cleaned["type"] in {"hover", "click", "focus", "fill", "scroll", "scrollBy", "press"}:
                kept_effect_action_count += 1
            actions.append(cleaned)
        if raw_actions and (
            not actions
            or (raw_state_action_count and not kept_state_action_count)
            or (raw_effect_action_count != kept_effect_action_count)
        ):
            continue
        if actions:
            capture["actions"] = actions
            capture["screenshot"]["fullPage"] = False
        captures.append(capture)
        if max_captures is not None and len(captures) >= max_captures:
            break

    if not captures:
        return _fallback_manifest(root, max_captures=max_captures)
    manifest["captures"] = captures
    animation_diagnostics: list[dict[str, Any]] = []
    manifest["animations"] = _sanitize_animations(
        root,
        raw.get("animations") or [],
        inventory_paths=inventory_paths,
        inventory_selectors=inventory_selectors,
        inventory_selector_counts=inventory_selector_counts,
        rendered_selector_count=rendered_selector_count,
        diagnostics=animation_diagnostics,
    )
    manifest["__diagnostics"] = {
        "raw_animation_count": len(raw.get("animations") or []) if isinstance(raw.get("animations") or [], list) else None,
        "sanitized_animation_count": len(manifest["animations"]),
        "raw_animations": raw.get("animations") if isinstance(raw.get("animations"), list) else raw.get("animations"),
        "animation_sanitize": animation_diagnostics,
    }
    return manifest


def _sanitize_animations(
    root: Path,
    raw_animations: Any,
    *,
    inventory_paths: set[str],
    inventory_selectors: dict[str, set[str]],
    inventory_selector_counts: dict[str, dict[str, int]],
    rendered_selector_count: Callable[[str, str], int | None] | None = None,
    diagnostics: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(raw_animations, list):
        if diagnostics is not None:
            diagnostics.append({"status": "skipped", "reason": "animations_not_list", "raw_type": type(raw_animations).__name__})
        return []
    animations: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    allowed_channels = {"motion", "color"}
    allowed_trigger_types = {"hover", "click", "focus", "scroll", "wait"}
    color_track_defaults = [
        "background-color",
        "color",
        "border-top-color",
        "border-right-color",
        "border-bottom-color",
        "border-left-color",
    ]
    if rendered_selector_count is None:
        rendered_selector_count_cache: dict[tuple[str, str], int | None] = {}

        def rendered_selector_count(path: str, selector: str) -> int | None:
            cache_key = (path, selector)
            if cache_key not in rendered_selector_count_cache:
                rendered_selector_count_cache[cache_key] = _rendered_selector_count(root, path, selector)
            return rendered_selector_count_cache[cache_key]

    def selector_status(path: str, selector: str | None) -> dict[str, Any]:
        if not selector:
            return {"ok": False, "reason": "missing_selector", "selector": selector}
        selector_count = inventory_selector_counts.get(path, {}).get(selector)
        rendered_count = None
        if selector_count is None:
            rendered_count = rendered_selector_count(path, selector)
            if rendered_count is not None:
                selector_count = rendered_count
        selector_known = (
            selector in inventory_selectors.get(path, set())
            or _selector_exists(root, path, selector)
            or (rendered_count is not None and rendered_count > 0)
        )
        selector_unique = selector_count == 1 or (selector_count is None and _selector_unique_in_source(root, path, selector))
        if not selector_known:
            return {"ok": False, "reason": "selector_not_found", "selector": selector, "selector_count": selector_count}
        if not selector_unique:
            return {"ok": False, "reason": "selector_not_unique", "selector": selector, "selector_count": selector_count}
        return {
            "ok": True,
            "selector": selector,
            "selector_count": selector_count,
            "source": "rendered_dom" if rendered_count is not None else "inventory_or_source",
        }

    def selector_ok(path: str, selector: str | None) -> bool:
        return bool(selector_status(path, selector).get("ok"))

    def record(status: str, item: Any, reason: str | None = None, **extra: Any) -> None:
        if diagnostics is None:
            return
        payload = {
            "status": status,
            "id": item.get("id") if isinstance(item, dict) else None,
        }
        if reason:
            payload["reason"] = reason
        payload.update(extra)
        diagnostics.append(payload)

    for item in raw_animations:
        if not isinstance(item, dict):
            record("dropped", item, "animation_not_object", raw_type=type(item).__name__)
            continue
        path = str(item.get("path") or "")
        if not path.startswith("/"):
            path = "/" + path
        browser_path_known = path in inventory_paths
        file_path_known = (root / path.lstrip("/")).exists()
        if not browser_path_known and not file_path_known:
            record("dropped", item, "path_not_found", path=path)
            continue

        animation_id = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(item.get("id") or "")).strip("-")
        if not animation_id:
            page_name = Path(path).stem if Path(path).stem != "index" else "home"
            animation_id = f"{page_name}.animation.{len(animations) + 1}"
        original_id = animation_id
        suffix = 2
        while animation_id in seen_ids:
            animation_id = f"{original_id}-{suffix}"
            suffix += 1
        seen_ids.add(animation_id)

        trigger = item.get("trigger") if isinstance(item.get("trigger"), dict) else {}
        trigger_type = str(trigger.get("type") or "click")
        if trigger_type not in allowed_trigger_types:
            trigger_type = "click"
        trigger_selector = trigger.get("selector")
        if trigger_type not in {"wait"} and trigger_selector and not selector_ok(path, str(trigger_selector)):
            record(
                "dropped",
                item,
                "trigger_selector_invalid",
                path=path,
                trigger_type=trigger_type,
                trigger_selector=str(trigger_selector),
                selector_status=selector_status(path, str(trigger_selector)),
            )
            continue
        if trigger_type not in {"wait"} and not trigger_selector:
            record("dropped", item, "trigger_selector_missing", path=path, trigger_type=trigger_type)
            continue

        timeline = item.get("timeline") if isinstance(item.get("timeline"), dict) else {}
        duration_ms = int(timeline.get("durationMs") or 0)
        raw_samples = timeline.get("samplesMs")
        samples_ms = [int(value) for value in raw_samples if isinstance(value, int | float)] if isinstance(raw_samples, list) else []
        samples_ms = sorted({sample for sample in samples_ms if sample >= 0})
        if len(samples_ms) < 2:
            duration_ms = duration_ms or 600
            samples_ms = [0, duration_ms // 3, (duration_ms * 2) // 3, duration_ms]
        if duration_ms <= 0:
            duration_ms = max(samples_ms)

        targets: list[dict[str, Any]] = []
        target_drop_reasons: list[dict[str, Any]] = []
        for raw_target in item.get("targets") or []:
            if not isinstance(raw_target, dict):
                target_drop_reasons.append({"reason": "target_not_object", "raw_type": type(raw_target).__name__})
                continue
            selector = raw_target.get("selector")
            target_selector_status = selector_status(path, str(selector) if selector else None)
            if not target_selector_status.get("ok"):
                target_drop_reasons.append(
                    {
                        "reason": "target_selector_invalid",
                        "selector": selector,
                        "selector_status": target_selector_status,
                    }
                )
                continue
            channels = [
                str(channel)
                for channel in raw_target.get("channels") or []
                if str(channel) in allowed_channels
            ]
            if not channels:
                target_drop_reasons.append(
                    {
                        "reason": "target_channels_missing_or_invalid",
                        "selector": selector,
                        "raw_channels": raw_target.get("channels"),
                    }
                )
                continue
            track = [str(prop) for prop in raw_target.get("track") or [] if isinstance(prop, str)]
            if "color" in channels and not track:
                track = color_track_defaults
            targets.append(
                {
                    "name": str(raw_target.get("name") or "animated target"),
                    "selector": str(selector),
                    "channels": channels,
                    "track": track,
                }
            )
        if not targets:
            record("dropped", item, "no_valid_targets", path=path, target_drop_reasons=target_drop_reasons)
            continue

        sanitized = {
            "id": animation_id,
            "kind": "animation",
            "weight": float(item.get("weight") if isinstance(item.get("weight"), int | float) else 1.0),
            "page": str(item.get("page") or (Path(path).stem if Path(path).stem != "index" else "home")),
            "path": path,
            "viewport": item.get("viewport") if isinstance(item.get("viewport"), dict) else {"width": 1440, "height": 900},
            "trigger": {
                "type": trigger_type,
                "selector": str(trigger_selector) if trigger_selector else None,
                "settleBeforeMs": int(trigger.get("settleBeforeMs") or 0),
                "settleMs": int(trigger.get("settleMs") or 0),
            },
            "timeline": {
                "durationMs": duration_ms,
                "samplesMs": samples_ms,
                "recordFrames": bool(timeline.get("recordFrames", True)),
                "recordBoundingBoxes": bool(timeline.get("recordBoundingBoxes", True)),
                "recordComputedStyles": bool(timeline.get("recordComputedStyles", True)),
            },
            "targets": targets,
            "enabled": bool(item.get("enabled", True)),
        }
        animations.append(sanitized)
        record(
            "kept",
            item,
            path=path,
            sanitized_id=animation_id,
            trigger=sanitized["trigger"],
            targets=[{"selector": target["selector"], "channels": target["channels"]} for target in targets],
        )
    return animations


def generate_manifest(
    reference_root: PathLike,
    output_path: PathLike,
    *,
    model: str = "opus",
    max_captures: int | None = None,
    repo_root: PathLike | None = None,
    backend: str = "claude-code",
    claude_auth: ClaudeAuthMode = "api",
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(reference_root).resolve()
    if repo_root is not None:
        _load_dotenv(Path(repo_root) / ".env")
    output = Path(output_path).resolve()
    capture_budget = _resolve_capture_budget(root, max_captures)
    inventory = _inventory_for_prompt(root)

    if backend == "claude-code":
        if claude_auth not in {"api", "subscription"}:
            raise ValueError(f"Unknown Claude auth mode: {claude_auth}")
        if claude_auth == "api":
            _normalize_anthropic_key()
        if claude_auth == "api" and not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY is required for Claude Code manifest generation")
        return asyncio.run(
            _generate_manifest_claude_code_async(
                root,
                output,
                model=model,
                max_captures=capture_budget,
                inventory=inventory,
                auth_mode=claude_auth,
                context=context,
            )
        )

    if backend != "openai":
        raise ValueError(f"Unknown manifest backend: {backend}")
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required for OpenAI manifest generation")

    from openai import OpenAI

    if not inventory["pages"]:
        raise ValueError(f"No browser-rendered pages found in {root}")

    client = OpenAI()
    response = client.responses.create(
        model=model,
        input=[
            {
                "role": "user",
                "content": [{"type": "input_text", "text": _manifest_prompt(inventory, capture_budget, context=context)}],
            }
        ],
        text={"format": {"type": "json_object"}},
    )
    raw = _extract_json_object(response.output_text)
    manifest = _sanitize_manifest_with_inventory(root, raw, max_captures=capture_budget, inventory=inventory)
    diagnostics = manifest.pop("__diagnostics", {})
    manifest["site"]["root"] = _manifest_site_root(root, output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=False), encoding="utf-8")
    diagnostics_path = _write_manifest_diagnostics(output, diagnostics)
    logger.info(
        "manifest generated root=%s backend=openai raw_animations=%s kept_animations=%s diagnostics=%s",
        root,
        diagnostics.get("raw_animation_count"),
        diagnostics.get("sanitized_animation_count"),
        diagnostics_path,
    )
    return {
        "manifest": manifest,
        "output_path": str(output),
        "diagnostics_path": str(diagnostics_path),
        "diagnostics": diagnostics,
        "model": model,
        "backend": "openai",
        "page_count": len(inventory["pages"]),
        "inventory_source": inventory.get("source"),
        "capture_count": len(manifest["captures"]),
        "capture_budget": capture_budget,
    }
