from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

from website_design_eval.block_visual import _score_bbox_geometry
from website_design_eval.scoring import (
    _pick_torch_device,
    cssom_block_style_score,
    dreamsim_distance,
    extract_webcode2m_bbox_tree,
    presentation_diff_tags,
    score_screenshot_pair,
    visual_block_score,
    webcoderbench_tags,
    webcoderbench_visual_quality_scores,
    webcode2m_bbox_tree_to_html,
    webcode2m_bbox_tree_to_style_list,
    webcode2m_dom_score,
    webcode2m_text_score,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
REFERENCE_ROOT = REPO_ROOT / "test-site"
CANDIDATES = [
    REPO_ROOT / "reproductions" / "claude-attempt-01",
    REPO_ROOT / "reproductions" / "claude-attempt-02-bad",
]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def enabled_capture(capture: dict[str, Any]) -> bool:
    return capture.get("enabled", True) is not False


def output_dir(root: Path, manifest: dict[str, Any]) -> Path:
    return (root / manifest.get("outputDir", "./screenshots")).resolve()


def screenshot_path(root: Path, manifest: dict[str, Any], capture_id: str) -> Path:
    return output_dir(root, manifest) / f"{capture_id}.png"


def html_path(root: Path, capture: dict[str, Any]) -> Path:
    return (root / capture["path"].lstrip("/")).resolve()


def viewport(capture: dict[str, Any], manifest: dict[str, Any]) -> tuple[int, int]:
    raw = capture.get("viewport") or manifest.get("defaults", {}).get("viewport") or {}
    return int(raw.get("width", 1440)), int(raw.get("height", 900))


def page_map(captures: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    pages: dict[str, dict[str, Any]] = {}
    for capture in captures:
        page = capture.get("page") or capture["id"]
        if page not in pages or capture["id"].endswith(".desktop.full"):
            pages[page] = capture
    return pages


class Profiler:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.browser_launch_estimates: defaultdict[str, int] = defaultdict(int)

    def record(self, stage: str, label: str, fn: Callable[[], Any], *, browser_launches: int = 0) -> Any:
        started = time.perf_counter()
        error = None
        try:
            return fn()
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            return {"error": error}
        finally:
            elapsed = time.perf_counter() - started
            self.rows.append(
                {
                    "stage": stage,
                    "label": label,
                    "seconds": round(elapsed, 6),
                    "browser_launches_estimate": browser_launches,
                    "error": error,
                }
            )
            self.browser_launch_estimates[stage] += browser_launches
            print(f"{stage:26s} {elapsed:8.3f}s {label}", flush=True)


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["stage"]].append(row)
    summary = []
    for stage, stage_rows in sorted(grouped.items(), key=lambda item: sum(row["seconds"] for row in item[1]), reverse=True):
        seconds = sum(row["seconds"] for row in stage_rows)
        summary.append(
            {
                "stage": stage,
                "seconds": round(seconds, 3),
                "calls": len(stage_rows),
                "avg_seconds": round(seconds / len(stage_rows), 3),
                "browser_launches_estimate": sum(int(row["browser_launches_estimate"]) for row in stage_rows),
                "errors": sum(1 for row in stage_rows if row["error"]),
            }
        )
    return summary


def main() -> int:
    reference_manifest = read_json(REFERENCE_ROOT / "screenshot-manifest.json")
    reference_captures = [capture for capture in reference_manifest["captures"] if enabled_capture(capture)]
    reference_by_id = {capture["id"]: capture for capture in reference_captures}
    pages = page_map(reference_captures)
    profiler = Profiler()
    started = time.perf_counter()

    for candidate_root in CANDIDATES:
        candidate_manifest = read_json(candidate_root / "screenshot-manifest.json")
        candidate_by_id = {capture["id"]: capture for capture in candidate_manifest["captures"]}
        for capture_id, ref_capture in reference_by_id.items():
            cand_capture = candidate_by_id.get(capture_id, ref_capture)
            ref_png = screenshot_path(REFERENCE_ROOT, reference_manifest, capture_id)
            cand_png = screenshot_path(candidate_root, candidate_manifest, capture_id)
            if not ref_png.exists() or not cand_png.exists():
                profiler.rows.append(
                    {
                        "stage": "missing_capture",
                        "label": f"{candidate_root.name}/{capture_id}",
                        "seconds": 0.0,
                        "browser_launches_estimate": 0,
                        "error": "missing screenshot",
                    }
                )
                continue

            ref_html = html_path(REFERENCE_ROOT, ref_capture)
            cand_html = html_path(candidate_root, cand_capture)
            vp = viewport(ref_capture, reference_manifest)
            label = f"{candidate_root.name}/{capture_id}"

            profiler.record("screenshot_pair_with_clip", label, lambda: score_screenshot_pair(ref_png, cand_png, include_clip=True))
            profiler.record(
                "dreamsim_ensemble",
                label,
                lambda: dreamsim_distance(ref_png, cand_png, dreamsim_type="ensemble", cache_dir=REPO_ROOT / ".cache" / "dreamsim"),
            )
            profiler.record("presentation_diff", label, lambda: presentation_diff_tags(ref_png, cand_png, include_clusters=False))

            visual_block = profiler.record(
                "visual_block_plus_block_pm",
                label,
                lambda: visual_block_score(
                    ref_html,
                    cand_html,
                    ref_png,
                    cand_png,
                    device="cpu",
                    include_pairs=True,
                    include_block_pixelmatch=True,
                ),
                browser_launches=4,
            )
            if "matched_pairs" in visual_block:
                profiler.record(
                    "bbox_geometry_from_blocks",
                    label,
                    lambda vb=visual_block: _score_bbox_geometry(vb["matched_pairs"], coverage_score=float(vb["size"])),
                )
                profiler.record(
                    "cssom_block_style_reuse_blocks",
                    label,
                    lambda vb=visual_block: cssom_block_style_score(
                        ref_html,
                        cand_html,
                        ref_png,
                        cand_png,
                        device="cpu",
                        viewport=vp,
                        visual_block_result=vb,
                    ),
                    browser_launches=2,
                )

        for page, ref_capture in pages.items():
            cand_capture = candidate_by_id.get(ref_capture["id"], ref_capture)
            ref_html = html_path(REFERENCE_ROOT, ref_capture)
            cand_html = html_path(candidate_root, cand_capture)
            ref_png = screenshot_path(REFERENCE_ROOT, reference_manifest, ref_capture["id"])
            cand_png = screenshot_path(candidate_root, candidate_manifest, cand_capture["id"])
            vp = viewport(ref_capture, reference_manifest)
            label = f"{candidate_root.name}/{page}"

            profiler.record("webcode2m_text", label, lambda: webcode2m_text_score(ref_html, cand_html))
            profiler.record("webcode2m_dom", label, lambda: webcode2m_dom_score(ref_html, cand_html))

            for site, site_html in (("reference", ref_html), (candidate_root.name, cand_html)):
                profiler.record(
                    "webcode2m_bbox_tree",
                    f"{site}/{page}",
                    lambda path=site_html: (
                        lambda tree: {
                            "tree": tree,
                            "bbox_html_len": len(webcode2m_bbox_tree_to_html(tree, size=vp)),
                            "style_rows": len(webcode2m_bbox_tree_to_style_list(tree)) if tree else 0,
                        }
                    )(extract_webcode2m_bbox_tree(path, viewport=vp)),
                    browser_launches=1,
                )

            for site, site_html, site_png in (("reference", ref_html, ref_png), (candidate_root.name, cand_html, cand_png)):
                profiler.record("webcoderbench_tags", f"{site}/{page}", lambda path=site_html: webcoderbench_tags(path), browser_launches=2)
                if site_png.exists():
                    profiler.record(
                        "webcoderbench_visual_quality",
                        f"{site}/{page}",
                        lambda path=site_html, png=site_png: webcoderbench_visual_quality_scores(path, png),
                        browser_launches=2,
                    )

    elapsed = time.perf_counter() - started
    result = {
        "elapsed_seconds": round(elapsed, 3),
        "torch_device_for_dreamsim": _pick_torch_device(None),
        "summary": summarize(profiler.rows),
        "browser_launches_estimate_by_stage": dict(profiler.browser_launch_estimates),
        "rows": profiler.rows,
        "notes": {
            "visual_block_browser_launches": "Each visual_block call renders candidate twice and reference twice through html2screenshot subprocesses.",
            "cssom_browser_launches": "Each cssom_block_style call extracts one CSSOM snapshot for reference and one for candidate.",
            "diagnostic_browser_launches": "webcoderbench_tags uses accessibility + mobile overflow browser passes; visual_quality uses component + icon browser passes.",
        },
    }
    out_dir = REPO_ROOT / "metrics-results" / "2026-05-19-runtime-profile"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "runtime-profile.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")

    print("\nSUMMARY")
    for row in result["summary"]:
        print(
            f"{row['stage']:32s} {row['seconds']:8.3f}s "
            f"calls={row['calls']:3d} avg={row['avg_seconds']:6.3f}s "
            f"browser_launches~{row['browser_launches_estimate']:3d} errors={row['errors']}"
        )
    print(f"\nTOTAL {elapsed:.3f}s")
    print(out_dir / "runtime-profile.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
