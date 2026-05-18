from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .io import list_site_files
from .models import ConceptCandidate, DeterministicCheckReport, RepairIssue, VerifierReport

PLACEHOLDER_PATTERNS = [
    re.compile(r"lorem ipsum", re.IGNORECASE),
    re.compile(r"placeholder text", re.IGNORECASE),
    re.compile(r"TODO:", re.IGNORECASE),
]


def _read_site_text(site_dir: Path, files: list[str]) -> str:
    chunks = []
    for file in files:
        if Path(file).suffix.lower() in {".html", ".css", ".js", ".json", ".txt", ".md", ".svg"}:
            chunks.append((site_dir / file).read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(chunks)


def deterministic_verify(
    site_dir: str | Path,
    concept: ConceptCandidate,
    *,
    run_browser_checks: bool = True,
) -> DeterministicCheckReport:
    root = Path(site_dir)
    issues: list[RepairIssue] = []
    checks: dict[str, Any] = {"site_files": list_site_files(root)}

    if not root.exists():
        return DeterministicCheckReport(
            passed=False,
            issues=[RepairIssue(type="missing_site", message=f"Site directory does not exist: {root}")],
            checks=checks,
        )

    html_files = [file for file in checks["site_files"] if Path(file).suffix.lower() == ".html"]
    checks["html_page_count"] = len(html_files)
    if len(html_files) < 5:
        issues.append(
            RepairIssue(
                type="insufficient_page_count",
                message=f"Generated site has {len(html_files)} HTML pages; expected at least 5.",
            )
        )

    for page in concept.pages:
        page_path = root / page.path.lstrip("/")
        if not page_path.exists():
            issues.append(
                RepairIssue(
                    type="missing_page",
                    message=f"Declared page is missing: {page.path}",
                    path=page.path,
                )
            )

    site_text = _read_site_text(root, checks["site_files"])
    missing_text = [text for text in concept.required_text if text and text not in site_text]
    checks["missing_required_text"] = missing_text
    for text in missing_text:
        issues.append(
            RepairIssue(
                type="missing_required_text",
                message=f"Required text not found in generated site: {text}",
            )
        )

    placeholder_hits = [pattern.pattern for pattern in PLACEHOLDER_PATTERNS if pattern.search(site_text)]
    checks["placeholder_hits"] = placeholder_hits
    for pattern in placeholder_hits:
        issues.append(
            RepairIssue(
                type="placeholder_content",
                message=f"Generated site contains placeholder marker matching {pattern}",
            )
        )

    if run_browser_checks:
        checks["browser_metrics"] = _browser_checks(root, concept)
        for page, page_checks in checks["browser_metrics"].items():
            if isinstance(page_checks, dict) and page_checks.get("error"):
                issues.append(
                    RepairIssue(
                        type="browser_check_error",
                        message=f"Browser check failed for {page}: {page_checks['error']}",
                        severity="warning",
                        path=page,
                    )
                )
            overflow = page_checks.get("mobile_overflow") if isinstance(page_checks, dict) else None
            if isinstance(overflow, dict) and overflow.get("tags"):
                issues.append(
                    RepairIssue(
                        type="mobile_overflow",
                        message=f"Mobile overflow tags for {page}: {overflow.get('tags')}",
                        severity="warning",
                        path=page,
                    )
                )

    return DeterministicCheckReport(passed=not issues, issues=issues, checks=checks)


def _browser_checks(root: Path, concept: ConceptCandidate) -> dict[str, Any]:
    try:
        from website_design_eval import accessibility_control_tags, mobile_overflow_tags, webcoderbench_tags
    except Exception as exc:
        return {"error": f"website_design_eval unavailable: {type(exc).__name__}: {exc}"}

    results: dict[str, Any] = {}
    for page in concept.pages:
        html = root / page.path.lstrip("/")
        if not html.exists():
            continue
        try:
            results[page.path] = {
                "mobile_overflow": mobile_overflow_tags(html),
                "accessibility": accessibility_control_tags(html),
                "webcoderbench": webcoderbench_tags(html),
            }
        except Exception as exc:
            results[page.path] = {"error": f"{type(exc).__name__}: {exc}"}
    return results


def verifier_report_from_deterministic(report: DeterministicCheckReport) -> VerifierReport:
    if report.passed:
        return VerifierReport(
            status="approved",
            issues=[],
            scores={"contract": 1.0, "render_quality": 1.0},
            deterministic_checks=report.model_dump(),
        )
    return VerifierReport(
        status="needs_repair",
        issues=report.issues,
        scores={"contract": 0.0, "render_quality": 0.0},
        repair_instructions=[issue.message for issue in report.issues],
        deterministic_checks=report.model_dump(),
    )
