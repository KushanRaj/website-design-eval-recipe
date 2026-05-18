from __future__ import annotations

import subprocess
from pathlib import Path

from .models import CaptureSpec, ConceptCandidate, ScreenshotManifest


def manifest_from_concept(concept: ConceptCandidate, *, site_name: str) -> ScreenshotManifest:
    captures: list[CaptureSpec] = []
    for page in concept.pages:
        path = page.path if page.path.startswith("/") else f"/{page.path}"
        captures.append(
            CaptureSpec(
                id=f"{page.id}.desktop.full",
                page=page.id,
                state="full page",
                path=path,
                viewport={"width": 1440, "height": 900},
                screenshot={"fullPage": True},
            )
        )
        if "mobile" in concept.mobile_behavior.lower():
            captures.append(
                CaptureSpec(
                    id=f"{page.id}.mobile.viewport",
                    page=page.id,
                    state="mobile viewport",
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
        defaults={
            "viewport": {"width": 1440, "height": 900},
            "deviceScaleFactor": 1,
            "waitUntil": "networkidle",
            "afterLoadWaitMs": 100,
            "timeoutMs": 30000,
            "screenshot": {"fullPage": False, "animations": "disabled", "caret": "hide"},
        },
        captures=captures,
    )


def write_manifest(site_dir: str | Path, manifest: ScreenshotManifest) -> Path:
    path = Path(site_dir) / "screenshot-manifest.json"
    path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return path


def run_manifest_capture(
    manifest_path: str | Path,
    *,
    repo_root: str | Path | None = None,
    output_dir: str | Path | None = None,
    timeout_seconds: int = 120,
) -> subprocess.CompletedProcess[str]:
    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[1]
    script = root / "scripts" / "capture-screenshots.mjs"
    if not script.exists():
        raise FileNotFoundError(f"capture script not found: {script}")
    command = ["node", str(script), str(Path(manifest_path))]
    if output_dir is not None:
        command.extend(["--out", str(output_dir)])
    return subprocess.run(
        command,
        cwd=root,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=True,
    )
