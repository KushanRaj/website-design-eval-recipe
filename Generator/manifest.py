from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

from .models import CaptureSpec, ConceptCandidate, ScreenshotManifest, VerifierReport


logger = logging.getLogger("Generator.manifest")


def _manifest_defaults() -> dict[str, Any]:
    return {
        "viewport": {"width": 1440, "height": 900},
        "deviceScaleFactor": 1,
        "waitUntil": "networkidle",
        "afterLoadWaitMs": 100,
        "timeoutMs": 30000,
        "screenshot": {"fullPage": False, "animations": "disabled", "caret": "hide"},
    }


def manifest_from_concept(concept: ConceptCandidate, *, site_name: str) -> ScreenshotManifest:
    captures: list[CaptureSpec] = []
    for page in concept.pages:
        path = page.path if page.path.startswith("/") else f"/{page.path}"
        captures.append(
            CaptureSpec(
                id=f"{page.id}.desktop.full",
                weight=1.0,
                page=page.id,
                state="full page",
                intent=f"Capture the full {page.id} page.",
                path=path,
                viewport={"width": 1440, "height": 900},
                screenshot={"fullPage": True},
            )
        )
        if "mobile" in concept.mobile_behavior.lower():
            captures.append(
                CaptureSpec(
                    id=f"{page.id}.mobile.viewport",
                    weight=0.5,
                    page=page.id,
                    state="mobile viewport",
                    intent=f"Capture the mobile viewport for the {page.id} page.",
                    path=path,
                    viewport={"width": 390, "height": 844},
                    screenshot={"fullPage": False},
                )
            )
    return ScreenshotManifest(
        schemaVersion=1,
        site={"name": site_name, "root": "."},
        outputDir="./screenshots/reference",
        cleanOutputDir=True,
        defaults=_manifest_defaults(),
        captures=captures,
        animations=[],
    )


def _page_name_for_path(path: str) -> str:
    stem = Path(path).stem
    if not stem or stem == "index":
        return "home"
    return stem


def _selector_for_element(element: dict[str, Any]) -> str | None:
    for candidate in element.get("selector_candidates") or []:
        if isinstance(candidate, dict) and candidate.get("count") == 1 and candidate.get("selector"):
            return str(candidate["selector"])
    selector = element.get("selector")
    if isinstance(selector, str) and selector:
        return selector
    element_id = element.get("id")
    if isinstance(element_id, str) and element_id:
        return f"#{element_id}"
    tag = element.get("tag")
    name = element.get("name")
    if isinstance(tag, str) and isinstance(name, str) and name:
        return f'{tag}[name="{name}"]'
    return None


def manifest_from_browser_inventory(
    site_dir: str | Path,
    *,
    site_name: str,
    max_captures: int | None = None,
) -> ScreenshotManifest:
    """Deterministic fallback built from Playwright-rendered page inventory.

    This is intentionally simpler than the Claude-authored manifest, but it
    still uses rendered routes/selectors instead of concept-only page specs.
    """

    from website_design_eval.manifest_generator import _inventory_for_prompt, _resolve_capture_budget

    root = Path(site_dir).resolve()
    budget = max_captures if max_captures is not None else _resolve_capture_budget(root, None)
    inventory = _inventory_for_prompt(root)
    pages = [page for page in inventory.get("pages", []) if page.get("status") == "ok"]
    captures: list[CaptureSpec] = []

    for page in pages:
        if budget is not None and len(captures) >= budget:
            break
        path = str(page["path"])
        page_name = str(page.get("page") or _page_name_for_path(path))
        captures.append(
            CaptureSpec(
                id=f"{page_name}.desktop.full",
                weight=1.0,
                page=page_name,
                state="full page",
                intent=f"Capture the full rendered {page_name} page.",
                path=path,
                viewport={"width": 1440, "height": 900},
                screenshot={"fullPage": True},
            )
        )

    def add_capture(capture: CaptureSpec) -> None:
        if budget is not None and len(captures) >= budget:
            return
        if any(existing.id == capture.id for existing in captures):
            return
        captures.append(capture)

    for page in pages:
        path = str(page["path"])
        page_name = str(page.get("page") or _page_name_for_path(path))
        candidates = page.get("interaction_candidates") or []
        dropdown = next(
            (
                element
                for element in candidates
                if any(
                    token in f"{element.get('id', '')} {element.get('class_name', '')} {element.get('text', '')} {element.get('accessible_name', '')}".lower()
                    for token in ("dropdown", "menu", "work")
                )
            ),
            None,
        )
        selector = _selector_for_element(dropdown) if isinstance(dropdown, dict) else None
        if selector:
            add_capture(
                CaptureSpec(
                    id=f"{page_name}.desktop.dropdown-hover",
                    weight=0.25,
                    page=page_name,
                    state="dropdown hover",
                    intent="Reveal a dropdown or menu state in the rendered page.",
                    path=path,
                    viewport={"width": 1440, "height": 900},
                    actions=[{"type": "hover", "selector": selector, "settleMs": 250}],
                    screenshot={"fullPage": False},
                )
            )

        input_control = next(
            (
                element
                for element in page.get("controls") or []
                if element.get("tag") in {"input", "textarea"} and _selector_for_element(element)
            ),
            None,
        )
        selector = _selector_for_element(input_control) if isinstance(input_control, dict) else None
        if selector:
            add_capture(
                CaptureSpec(
                    id=f"{page_name}.desktop.input-focused",
                    weight=0.5,
                    page=page_name,
                    state="input focused",
                    intent="Focus a rendered form input to capture focus styling.",
                    path=path,
                    viewport={"width": 1440, "height": 900},
                    actions=[{"type": "focus", "selector": selector, "settleMs": 150}],
                    screenshot={"fullPage": False},
                )
            )

        section = next(
            (
                element
                for element in page.get("sections") or []
                if element.get("id") and element.get("tag") in {"section", "main", "article", "form"}
            ),
            None,
        )
        selector = _selector_for_element(section) if isinstance(section, dict) else None
        if selector:
            add_capture(
                CaptureSpec(
                    id=f"{page_name}.desktop.section-scroll",
                    weight=0.5,
                    page=page_name,
                    state="section scrolled",
                    intent="Scroll to a meaningful rendered section.",
                    path=path,
                    viewport={"width": 1440, "height": 900},
                    actions=[{"type": "scroll", "selector": selector, "settleMs": 150}],
                    screenshot={"fullPage": False},
                )
            )

    if len(captures) < 5:
        raise ValueError(f"Rendered browser inventory produced only {len(captures)} captures for {root}")

    return ScreenshotManifest(
        schemaVersion=1,
        site={"name": site_name, "root": "."},
        outputDir="./screenshots/reference",
        cleanOutputDir=True,
        defaults=_manifest_defaults(),
        captures=captures[:budget] if budget is not None else captures,
        animations=[],
    )


def _model_context(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return value


def generate_oracle_manifest(
    site_dir: str | Path,
    *,
    site_name: str,
    concept: ConceptCandidate | None = None,
    verifier_report: VerifierReport | None = None,
    model: str = "opus",
    backend: str = "claude-code",
    max_captures: int | None = None,
    repo_root: str | Path | None = None,
    allow_fallback: bool = True,
) -> ScreenshotManifest:
    """Generate the oracle manifest from rendered browser state.

    The Claude path uses website_design_eval's browser-state manifest
    generator, passing concept/verifier information only as intent context.
    """

    root = Path(site_dir).resolve()
    resolved_repo_root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[1]
    output_path = root / "screenshot-manifest.json"
    context = {
        "site_name": site_name,
        "accepted_concept": _model_context(concept),
        "verifier_report": _model_context(verifier_report),
        "instruction": (
            "Generate the oracle screenshot manifest from the rendered browser "
            "inventory. Preserve important route coverage and interaction "
            "intent so a candidate evaluator can later resolve equivalent "
            "states even if selectors differ."
        ),
    }

    try:
        from website_design_eval.manifest_generator import generate_manifest

        result = generate_manifest(
            root,
            output_path,
            model=model,
            max_captures=max_captures,
            backend=backend,
            context=context,
            repo_root=resolved_repo_root,
        )
        return ScreenshotManifest.model_validate(result["manifest"])
    except Exception:
        if not allow_fallback:
            raise
        logger.warning(
            "browser-state Claude manifest generation failed for %s; falling back to deterministic browser inventory",
            root,
            exc_info=True,
        )
        return manifest_from_browser_inventory(root, site_name=site_name, max_captures=max_captures)


def write_manifest(site_dir: str | Path, manifest: ScreenshotManifest) -> Path:
    path = Path(site_dir) / "screenshot-manifest.json"
    path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return path


def run_manifest_capture(
    manifest_path: str | Path,
    *,
    repo_root: str | Path | None = None,
    output_dir: str | Path | None = None,
    prune_failed: bool = False,
    timeout_seconds: int = 120,
) -> subprocess.CompletedProcess[str]:
    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[1]
    script = root / "scripts" / "capture-screenshots.mjs"
    if not script.exists():
        raise FileNotFoundError(f"capture script not found: {script}")
    command = ["node", str(script), str(Path(manifest_path))]
    if output_dir is not None:
        command.extend(["--out", str(output_dir)])
    if prune_failed:
        command.append("--prune-failed")
    return subprocess.run(
        command,
        cwd=root,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=True,
    )
