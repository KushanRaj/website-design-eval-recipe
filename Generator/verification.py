from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path
from typing import Any

from .io import list_site_files
from .models import ConceptCandidate, DeterministicCheckReport, RepairIssue, VerifierReport

logger = logging.getLogger("Generator.verification")

PLACEHOLDER_PATTERNS = [
    re.compile(r"lorem ipsum", re.IGNORECASE),
    re.compile(r"placeholder text", re.IGNORECASE),
    re.compile(r"\bTODO:", re.IGNORECASE),
]

DEFAULT_VIEWPORT = (1440, 900)
MOBILE_VIEWPORT = (390, 844)
RENDER_SANITY_THRESHOLD = 0.65


def _resolve_page_path(site_root: Path, declared: str) -> Path | None:
    """Resolve a concept's declared page path the way a static server would.

    Returns the resolved file path, or ``None`` if no candidate exists.
    The verifier no longer treats failure-to-resolve as an error — it just
    means we can't pull metrics for that declared path. The LLM verifier
    decides whether the unresolved path is a real problem (e.g. a missing
    page) or a non-issue (e.g. a route template like ``/subjects/{slug}``
    that the builder implemented as a concrete file like ``subjects/biology.html``).
    """

    cleaned = declared.strip().lstrip("/")
    if not cleaned or cleaned in {".", "./"}:
        candidates = [site_root / "index.html"]
    else:
        candidates = [
            site_root / cleaned,
            site_root / f"{cleaned}.html",
            site_root / cleaned / "index.html",
        ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _read_site_text(site_dir: Path, files: list[str]) -> str:
    chunks = []
    for file in files:
        if Path(file).suffix.lower() in {".html", ".css", ".js", ".json", ".txt", ".md", ".svg"}:
            try:
                chunks.append((site_dir / file).read_text(encoding="utf-8", errors="ignore"))
            except OSError as exc:
                logger.warning("could not read %s: %s", file, exc)
    return "\n".join(chunks)


def deterministic_verify(
    site_dir: str | Path,
    concept: ConceptCandidate,
    *,
    run_browser_checks: bool = True,
) -> DeterministicCheckReport:
    """Extract structured facts about the built site. The LLM verifier is
    the judge — this function does NOT decide approval, and its ``passed``
    field is only False for hard physical impossibilities (site missing,
    no files, no index.html).

    Concept-shape questions (did the builder implement what was declared?
    are layouts consistent? are mobile breakpoints right?) are reported as
    raw measurements in ``checks.per_page`` and left for the LLM verifier
    to weigh.
    """

    root = Path(site_dir)
    issues: list[RepairIssue] = []
    checks: dict[str, Any] = {"site_files": list_site_files(root)}

    # Hard physical-impossibility gates. Only these block.
    if not root.exists():
        return DeterministicCheckReport(
            passed=False,
            issues=[RepairIssue(type="missing_site", message=f"Site directory does not exist: {root}")],
            checks=checks,
        )

    files = checks["site_files"]
    html_files = [file for file in files if Path(file).suffix.lower() == ".html"]
    checks["html_page_count"] = len(html_files)

    if not files:
        issues.append(
            RepairIssue(
                type="empty_site",
                message=f"Builder produced no files in {root}.",
                severity="error",
            )
        )
    if "index.html" not in files:
        issues.append(
            RepairIssue(
                type="missing_index",
                message="Generated site has no index.html at the site root.",
                severity="error",
            )
        )

    # --- everything below is informational. Surfaced to the LLM, never blocks. ---

    # Per-page presence summary (resolved vs unresolved). NOT marked as an
    # error — the LLM decides if an unresolved path is meaningful (it may
    # be a route template the builder implemented under a different name).
    page_presence: dict[str, dict[str, Any]] = {}
    for page in concept.pages:
        resolved = _resolve_page_path(root, page.path)
        page_presence[page.path] = {
            "declared_path": page.path,
            "declared_id": page.id,
            "resolved_file": str(resolved.relative_to(root)) if resolved else None,
            "found": resolved is not None,
        }
    checks["page_presence"] = page_presence

    # Required-text substring check — informational only. LLM decides if
    # rephrased text still satisfies the intent.
    site_text = _read_site_text(root, files)
    missing_text = [text for text in concept.required_text if text and text not in site_text]
    checks["missing_required_text"] = missing_text

    # Placeholder content — informational warning.
    placeholder_hits = [pattern.pattern for pattern in PLACEHOLDER_PATTERNS if pattern.search(site_text)]
    checks["placeholder_hits"] = placeholder_hits

    if run_browser_checks:
        logger.info("running browser checks for %s", root)
        per_page_metrics = _browser_checks(root, concept)
        checks["per_page_metrics"] = per_page_metrics
        # Roll up a summary so the LLM (and humans) can see at-a-glance signal.
        checks["per_page_summary"] = _summarize_per_page(per_page_metrics)

    blocking = [issue for issue in issues if issue.severity == "error"]
    return DeterministicCheckReport(passed=not blocking, issues=issues, checks=checks)


def _summarize_per_page(per_page: dict[str, Any]) -> dict[str, Any]:
    """One-line-per-page summary of the metrics we extracted. Designed to be
    short enough for a verifier prompt without being lossy."""

    summary: dict[str, Any] = {}
    for path, page_data in per_page.items():
        if not isinstance(page_data, dict):
            continue
        entry: dict[str, Any] = {}
        sanity = page_data.get("render_sanity")
        if isinstance(sanity, dict):
            entry["render_sanity"] = round(sanity.get("score", 0.0), 3)
        # mobile_overflow_px / mobile_overflow_tags intentionally omitted —
        # the underlying extractor is disabled (see _browser_checks).
        # overflow = page_data.get("mobile_overflow")
        # if isinstance(overflow, dict):
        #     entry["mobile_overflow_px"] = overflow.get("horizontal_overflow_px")
        #     entry["mobile_overflow_tags"] = overflow.get("tags")
        accessibility = page_data.get("accessibility")
        if isinstance(accessibility, dict):
            entry["accessibility_tags"] = accessibility.get("tags")
        vquality = page_data.get("webcoderbench_visual_quality")
        if isinstance(vquality, dict):
            scores = vquality.get("scores", vquality)
            if isinstance(scores, dict):
                entry["component_style"] = _round_or_none(scores.get("component_style_consistency", {}).get("score"))
                entry["icon_style"] = _round_or_none(scores.get("icon_style_consistency", {}).get("score"))
                entry["layout_consistency"] = _round_or_none(scores.get("layout_consistency", {}).get("score"))
                entry["layout_sparsity"] = _round_or_none(scores.get("layout_sparsity", {}).get("score"))
        for key in (
            "render_sanity_error",
            "mobile_overflow_error",
            "accessibility_error",
            "webcoderbench_visual_quality_error",
        ):
            if page_data.get(key):
                entry.setdefault("errors", []).append({key: page_data[key]})
        summary[path] = entry
    return summary


def _round_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _browser_checks(root: Path, concept: ConceptCandidate) -> dict[str, Any]:
    """Run Playwright-backed metric extractors per declared page. Stays
    fault-tolerant per page so one failing screenshot doesn't kill the rest."""

    try:
        from website_design_eval import (
            accessibility_control_tags,
            # mobile_overflow_tags,  # disabled: noisy signal that drove the verifier to
            #                        # surface "mobile overflow" issues on every site.
            #                        # Mobile responsiveness should be judged from a real
            #                        # mobile screenshot at the manifest stage, not from
            #                        # this pixel-count heuristic.
            render_sanity_score,
            webcoderbench_visual_quality_scores,
        )
    except Exception as exc:
        return {"_error": f"website_design_eval unavailable: {type(exc).__name__}: {exc}"}

    results: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="verify-screens-") as tmp_root:
        tmp = Path(tmp_root)
        resolved_pages: dict[str, Path] = {}
        for page in concept.pages:
            resolved = _resolve_page_path(root, page.path)
            if resolved is not None:
                resolved_pages[page.path] = resolved
        screenshots = _capture_desktop_screenshots(resolved_pages, tmp)
        for page in concept.pages:
            html = resolved_pages.get(page.path)
            if html is None:
                continue
            entry: dict[str, Any] = {}
            # mobile_overflow disabled — see import block above. The verifier was
            # picking up its noise and emitting "fix mobile overflow" issues on
            # every page, which crowded out real signal. Re-enable when we have
            # a true mobile screenshot in the manifest.
            # try:
            #     entry["mobile_overflow"] = mobile_overflow_tags(html, viewport=MOBILE_VIEWPORT)
            # except Exception as exc:
            #     entry["mobile_overflow_error"] = f"{type(exc).__name__}: {exc}"
            try:
                entry["accessibility"] = accessibility_control_tags(html, viewport=DEFAULT_VIEWPORT)
            except Exception as exc:
                entry["accessibility_error"] = f"{type(exc).__name__}: {exc}"
            screenshot = screenshots.get(page.path)
            if screenshot is not None and screenshot.exists():
                try:
                    entry["render_sanity"] = render_sanity_score(screenshot, html_path=html)
                except Exception as exc:
                    entry["render_sanity_error"] = f"{type(exc).__name__}: {exc}"
                try:
                    entry["webcoderbench_visual_quality"] = webcoderbench_visual_quality_scores(
                        html, screenshot, viewport=DEFAULT_VIEWPORT
                    )
                except Exception as exc:
                    entry["webcoderbench_visual_quality_error"] = f"{type(exc).__name__}: {exc}"
            else:
                entry["render_sanity_error"] = "screenshot capture failed"
            results[page.path] = entry
    return results


def _capture_desktop_screenshots(
    resolved_pages: dict[str, Path], tmp_dir: Path
) -> dict[str, Path]:
    """Capture a single full-page desktop screenshot per declared page."""

    if not resolved_pages:
        return {}
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        logger.warning("playwright not installed for verifier screenshots: %s", exc)
        return {}

    out: dict[str, Path] = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(
                viewport={"width": DEFAULT_VIEWPORT[0], "height": DEFAULT_VIEWPORT[1]},
                device_scale_factor=1,
            )
            page = context.new_page()
            for index, (declared, html) in enumerate(resolved_pages.items()):
                slug = declared.lstrip("/").replace("/", "_") or "root"
                screenshot_path = tmp_dir / f"page-{index:02d}-{slug}.png"
                try:
                    page.goto(html.resolve().as_uri(), wait_until="networkidle", timeout=20000)
                    page.screenshot(path=str(screenshot_path), full_page=True, animations="disabled")
                    out[declared] = screenshot_path
                except Exception as exc:
                    logger.warning("screenshot failed for %s: %s", declared, exc)
            context.close()
            browser.close()
    except Exception as exc:
        logger.warning("playwright session failed: %s", exc)
    return out


def verifier_report_from_deterministic(report: DeterministicCheckReport) -> VerifierReport:
    """Synthesize a VerifierReport ONLY when the site itself is physically
    impossible (no site dir, no files, no index.html). The LLM verifier
    handles everything else — it owns the judgment.

    Callers should normally invoke the LLM verifier regardless of
    deterministic.passed. This function exists for the hard-impossibility
    short-circuit case only.
    """

    return VerifierReport(
        status="rejected" if not report.passed else "approved",
        issues=report.issues,
        scores={"contract": 0.0 if not report.passed else 1.0},
        repair_instructions=[issue.message for issue in report.issues],
        deterministic_checks=report.model_dump(),
    )
