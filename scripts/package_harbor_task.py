from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _copytree(src: Path, dst: Path, *, ignore_extra: set[str] | None = None) -> None:
    ignore_names = {
        ".DS_Store",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        "*.pyc",
    }
    if ignore_extra:
        ignore_names.update(ignore_extra)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(*sorted(ignore_names)))


def _enabled(capture: dict[str, Any]) -> bool:
    return capture.get("enabled", True) is not False


def _copy_public_screenshots(site_dir: Path, manifest: dict[str, Any], output_dir: Path) -> None:
    source_dir = Path(manifest.get("outputDir") or "./screenshots/reference")
    if not source_dir.is_absolute():
        source_dir = site_dir / source_dir
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    screenshot_index = 1
    for capture in manifest.get("captures", []):
        if not _enabled(capture):
            continue
        source = source_dir / f"{capture['id']}.png"
        if source.exists():
            shutil.copyfile(source, output_dir / f"{screenshot_index:03d}.png")
            screenshot_index += 1


def _write_text(path: Path, text: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")
    if executable:
        path.chmod(0o755)


def _task_toml(task_name: str, *, verifier_allow_internet: bool = False) -> str:
    verifier_internet = "true" if verifier_allow_internet else "false"
    return f"""
schema_version = "1.1"
artifacts = ["/app"]

[task]
name = "{task_name}"
description = "Replicate a multi-page website design from screenshots."
authors = []
keywords = ["web", "design-replication", "html", "css", "visual-evaluation", "screenshot-only"]

[metadata]
category = "software_engineering"
difficulty = "medium"
tags = ["website", "visual", "html-css"]

[agent]
timeout_sec = 1800

[environment]
build_timeout_sec = 600
os = "linux"
cpus = 2
memory_mb = 4096
storage_mb = 10240
allow_internet = true
workdir = "/app"

[verifier]
timeout_sec = 1800
environment_mode = "separate"

[verifier.environment]
build_timeout_sec = 1200
os = "linux"
cpus = 2
memory_mb = 8192
storage_mb = 20480
allow_internet = {verifier_internet}
workdir = "/app"
"""


def _instruction_md() -> str:
    return """
# Website Replication

Recreate the website design shown in the reference screenshots.

The only reference materials are the screenshots under `/app/reference/screenshots/`.

Build your implementation under `/app/site`. Use local files only. The
main entry point should be `/app/site/index.html`; additional pages may be
created as separate HTML files when the screenshots imply multiple routes.
"""


def _readme_md(task_name: str, *, metric_profile: str, verifier_base_image: str | None) -> str:
    verifier_line = (
        f"`tests/Dockerfile` uses the reusable verifier image `{verifier_base_image}`."
        if verifier_base_image
        else "`tests/Dockerfile` installs the lightweight verifier dependencies directly."
    )
    return f"""
# {task_name}

This is a Harbor-style website replication task instance generated from a local
oracle site.

- Public candidate inputs live in `environment/workspace/reference/screenshots/`.
- Hidden verifier inputs live in `tests/private/`.
- The verifier writes `reward.json`, `metrics.json`, and Markdown diagnostics
  under `/logs/verifier`.

Metric profile: `{metric_profile}`.

{verifier_line}

Metric switches are in `tests/private/metric-config.json` and can be overridden
with `WDE_*` environment variables when running the verifier.
"""


def _environment_dockerfile() -> str:
    return """
FROM mcr.microsoft.com/playwright/python:v1.60.0-noble

WORKDIR /app
COPY workspace/ /app/

RUN mkdir -p /app/site
"""


def _tests_dockerfile(verifier_base_image: str | None = None) -> str:
    if verifier_base_image:
        return f"""
FROM {verifier_base_image}

RUN mkdir -p /app /logs/verifier
WORKDIR /app
COPY . /tests
RUN chmod +x /tests/test.sh
"""

    return """
FROM mcr.microsoft.com/playwright/python:v1.60.0-noble

RUN python -m pip install --no-cache-dir \\
    beautifulsoup4 \\
    lxml \\
    nltk \\
    numpy \\
    opencv-python-headless \\
    pillow \\
    playwright \\
    pydantic \\
    rouge \\
    scikit-image

RUN mkdir -p /app /logs/verifier
WORKDIR /app
COPY . /tests
RUN chmod +x /tests/test.sh
"""


def _run_eval_py() -> str:
    return r'''
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _capture_metric_value(metrics: dict[str, Any], capture_id: str, path: list[str]) -> Any:
    capture = (metrics.get("captures") or {}).get(capture_id) or {}
    current: Any = capture.get("metrics") or {}
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _require_capture_metric(metrics: dict[str, Any], path: list[str], label: str) -> None:
    missing: list[str] = []
    for capture_id, capture in (metrics.get("captures") or {}).items():
        coverage = ((capture.get("coverage") or {}).get("score") or 0)
        if not isinstance(coverage, (int, float)) or coverage <= 0:
            continue
        capture_metrics = capture.get("metrics") or {}
        if not isinstance(capture_metrics, dict) or capture_metrics.get("status") == "unsupported":
            continue
        value = _capture_metric_value(metrics, capture_id, path)
        if not isinstance(value, (int, float)):
            missing.append(capture_id)
    if missing:
        raise RuntimeError(f"Required metric {label} is missing for captures: {missing}")


def _candidate_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    site = Path("/app/site")
    if (site / "index.html").exists():
        return site
    return Path("/app").resolve()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tests-dir", default=os.environ.get("TESTS_DIR", "/tests"))
    parser.add_argument("--logs-dir", default=os.environ.get("LOG_DIR", "/logs/verifier"))
    parser.add_argument("--candidate-root", default=os.environ.get("CANDIDATE_ROOT"))
    args = parser.parse_args(argv)

    tests_dir = Path(args.tests_dir).resolve()
    logs_dir = Path(args.logs_dir).resolve()
    candidate_root = _candidate_root(args.candidate_root)
    private_dir = tests_dir / "private"
    vendor_dir = tests_dir / "vendor"
    image_repo_root = Path(os.environ.get("WDE_REPO_ROOT", "/opt/wde"))
    if vendor_dir.exists():
        sys.path.insert(0, str(vendor_dir))
    if image_repo_root.exists():
        sys.path.insert(0, str(image_repo_root))

    from website_design_eval.evaluator import EvaluateConfig, evaluate
    from website_design_eval.reward import build_reward_markdown, compute_reward

    metric_config = _read_json(private_dir / "metric-config.json")
    eval_dir = logs_dir / "eval"
    eval_dir.mkdir(parents=True, exist_ok=True)

    capture_filter_raw = os.environ.get("WDE_CAPTURE_FILTER", "").strip()
    capture_filter = {part.strip() for part in capture_filter_raw.split(",") if part.strip()} or None

    skip_vlm = _bool_env("WDE_SKIP_VLM", bool(metric_config.get("skip_vlm", True)))
    skip_dreamsim = _bool_env("WDE_SKIP_DREAMSIM", bool(metric_config.get("skip_dreamsim", True)))
    dreamsim_device = os.environ.get("WDE_DREAMSIM_DEVICE") or metric_config.get("dreamsim_device")
    if skip_dreamsim and not dreamsim_device:
        dreamsim_device = "cpu"
    include_visual_block = _bool_env(
        "WDE_INCLUDE_VISUAL_BLOCK",
        bool(metric_config.get("include_visual_block", False)),
    )
    require_vlm = bool(metric_config.get("require_vlm", not skip_vlm))
    require_dreamsim = bool(metric_config.get("require_dreamsim", not skip_dreamsim))
    require_visual_block = bool(metric_config.get("require_visual_block", include_visual_block))

    if require_vlm and skip_vlm:
        raise RuntimeError("Full reward requires VLM, but WDE_SKIP_VLM/metric config disabled it.")
    if require_vlm and not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("Full reward requires OPENAI_API_KEY in the verifier environment.")
    if require_dreamsim and skip_dreamsim:
        raise RuntimeError("Full reward requires DreamSim, but WDE_SKIP_DREAMSIM/metric config disabled it.")
    if require_visual_block and not include_visual_block:
        raise RuntimeError("Full reward requires visual block, but WDE_INCLUDE_VISUAL_BLOCK/metric config disabled it.")

    repo_root = Path(os.environ.get("WDE_REPO_ROOT") or (image_repo_root if image_repo_root.exists() else vendor_dir)).resolve()

    metrics = evaluate(
        EvaluateConfig(
            reference_root=(private_dir / "oracle-site").resolve(),
            reference_manifest=(private_dir / "screenshot-manifest.json").resolve(),
            candidate_root=candidate_root,
            output_dir=eval_dir,
            repo_root=repo_root,
            skip_vlm=skip_vlm,
            skip_dreamsim=skip_dreamsim,
            vlm_model=os.environ.get("WDE_VLM_MODEL", metric_config.get("vlm_model", "gpt-5.4-mini")),
            dreamsim_type=metric_config.get("dreamsim_type", "ensemble"),
            dreamsim_device=dreamsim_device,
            dreamsim_cache_dir=os.environ.get("WDE_DREAMSIM_CACHE_DIR") or metric_config.get("dreamsim_cache_dir"),
            visual_block_device=os.environ.get("WDE_VISUAL_BLOCK_DEVICE", metric_config.get("visual_block_device", "cpu")),
            include_visual_block=include_visual_block,
            capture_filter=capture_filter,
        )
    )

    if require_vlm:
        _require_capture_metric(metrics, ["vlm_judge", "overall"], "vlm_judge.overall")
    if require_dreamsim:
        _require_capture_metric(metrics, ["dreamsim", "score"], "dreamsim.score")
    if require_visual_block:
        _require_capture_metric(metrics, ["visual_block", "score"], "visual_block.score")

    weight_mode = os.environ.get("WDE_WEIGHT_MODE", metric_config.get("weight_mode", "manifest"))
    reward = compute_reward(metrics, weight_mode=weight_mode)

    logs_dir.mkdir(parents=True, exist_ok=True)
    _write_json(logs_dir / "metrics.json", metrics)
    _write_json(logs_dir / "reward-details.json", reward)
    (logs_dir / "reward-report.md").write_text(build_reward_markdown(reward), encoding="utf-8")

    plan_path = eval_dir / "candidate-capture-plan.json"
    if plan_path.exists():
        shutil.copyfile(plan_path, logs_dir / "candidate-capture-plan.json")
    report_path = eval_dir / "functional-report.md"
    if report_path.exists():
        shutil.copyfile(report_path, logs_dir / "functional-report.md")

    summary = metrics.get("summary", {})
    reward_summary = reward.get("summary", {})
    reward_payload: dict[str, int | float] = {
        "reward": reward_summary.get("score", 0.0),
        "score": reward_summary.get("score", 0.0),
    }
    optional_numeric_fields = {
        "manifest_coverage": summary.get("manifest_coverage_score"),
        "screenshot_size_match": summary.get("mean_screenshot_size_match"),
        "pixelmatch": summary.get("mean_pixelmatch"),
        "dreamsim": summary.get("mean_dreamsim_score"),
        "vlm": summary.get("mean_vlm_overall"),
        "html_text_bleu_1": summary.get("mean_html_text_bleu_1"),
        "html_text_rouge_1_recall": summary.get("mean_html_text_rouge_1_recall"),
        "visual_block": summary.get("mean_visual_block_score"),
        "capture_count": summary.get("capture_count"),
        "covered_capture_count": summary.get("covered_capture_count"),
    }
    for key, value in optional_numeric_fields.items():
        if isinstance(value, (int, float)):
            reward_payload[key] = value
    _write_json(logs_dir / "reward.json", reward_payload)
    print(json.dumps(reward_payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _test_sh() -> str:
    return """
#!/usr/bin/env bash
set -euo pipefail

TESTS_DIR="${TESTS_DIR:-/tests}"
LOG_DIR="${LOG_DIR:-/logs/verifier}"
CANDIDATE_ROOT="${CANDIDATE_ROOT:-}"

args=(--tests-dir "$TESTS_DIR" --logs-dir "$LOG_DIR")
if [[ -n "$CANDIDATE_ROOT" ]]; then
  args+=(--candidate-root "$CANDIDATE_ROOT")
fi

python "$TESTS_DIR/run_eval.py" "${args[@]}"
"""


def _solve_sh() -> str:
    return """
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORACLE_SITE="$SCRIPT_DIR/oracle-site"

rm -rf /app/site
mkdir -p /app/site

cp "$ORACLE_SITE"/*.html /app/site/
cp "$ORACLE_SITE"/*.css /app/site/
if [[ -d "$ORACLE_SITE/assets" ]]; then
  cp -R "$ORACLE_SITE/assets" /app/site/assets
fi
"""


def _metric_config(metric_profile: str) -> dict[str, Any]:
    if metric_profile == "lite":
        return {
            "profile": "harbor-phase1-lite",
            "skip_vlm": True,
            "skip_dreamsim": True,
            "include_visual_block": False,
            "vlm_model": "gpt-5.4-mini",
            "dreamsim_type": "ensemble",
            "dreamsim_device": None,
            "dreamsim_cache_dir": None,
            "visual_block_device": "cpu",
            "weight_mode": "manifest",
            "notes": [
                "Dependency-light development smoke mode only. Do not use for actual reward runs.",
                "Use --metric-profile full-vlm with a reusable verifier image for actual reward runs.",
            ],
        }
    if metric_profile == "full-local":
        return {
            "profile": "harbor-full-local",
            "skip_vlm": True,
            "skip_dreamsim": False,
            "include_visual_block": True,
            "require_vlm": False,
            "require_dreamsim": True,
            "require_visual_block": True,
            "vlm_model": "gpt-5.4-mini",
            "dreamsim_type": "ensemble",
            "dreamsim_device": "cpu",
            "dreamsim_cache_dir": "/opt/wde/models/dreamsim",
            "visual_block_device": "cpu",
            "weight_mode": "manifest",
            "notes": [
                "Local-only development profile. Do not use for actual reward runs.",
                "Use --metric-profile full-vlm for the actual reward.",
            ],
        }
    if metric_profile == "full-vlm":
        return {
            "profile": "harbor-full-vlm",
            "skip_vlm": False,
            "skip_dreamsim": False,
            "include_visual_block": True,
            "require_vlm": True,
            "require_dreamsim": True,
            "require_visual_block": True,
            "vlm_model": "gpt-5.4-mini",
            "dreamsim_type": "ensemble",
            "dreamsim_device": "cpu",
            "dreamsim_cache_dir": "/opt/wde/models/dreamsim",
            "visual_block_device": "cpu",
            "weight_mode": "manifest",
            "notes": [
                "Actual reward profile: API-backed VLM, DreamSim, and visual-block are all required.",
                "Requires OPENAI_API_KEY and verifier network access.",
            ],
        }
    raise ValueError(f"Unknown metric profile: {metric_profile}")


def package_task(
    site_dir: Path,
    task_dir: Path,
    *,
    task_name: str,
    force: bool,
    verifier_base_image: str | None = None,
    metric_profile: str = "lite",
    vendor_evaluator: bool | None = None,
    verifier_allow_internet: bool = False,
) -> None:
    site_dir = site_dir.resolve()
    task_dir = task_dir.resolve()
    manifest_path = site_dir / "screenshot-manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing manifest: {manifest_path}")
    if task_dir.exists():
        if not force:
            raise FileExistsError(f"Task directory exists; pass --force: {task_dir}")
        shutil.rmtree(task_dir)

    manifest = _read_json(manifest_path)

    # Invariant: Harbor packaging only copies frozen screenshots — it never
    # regenerates them. If the manifest references captures whose PNGs are
    # missing from site/screenshots/reference/, the generator pipeline did
    # not finalize this seed correctly. Fail loudly here rather than ship
    # an incomplete reference set.
    screenshots_dir = site_dir / "screenshots" / "reference"
    missing_pngs = [
        capture["id"]
        for capture in manifest.get("captures", [])
        if capture.get("enabled", True)
        and not (screenshots_dir / f"{capture['id']}.png").exists()
    ]
    if missing_pngs:
        raise FileNotFoundError(
            f"Manifest is missing frozen PNGs for {len(missing_pngs)} enabled captures: "
            f"{missing_pngs}. Harbor packaging only copies — never regenerates — screenshots. "
            f"Re-replay the manifest at {manifest_path} or mark those captures enabled=false."
        )

    if vendor_evaluator is None:
        vendor_evaluator = verifier_base_image is None

    _write_text(task_dir / "README.md", _readme_md(task_name, metric_profile=metric_profile, verifier_base_image=verifier_base_image))
    _write_text(task_dir / "instruction.md", _instruction_md())
    _write_text(task_dir / "task.toml", _task_toml(task_name, verifier_allow_internet=verifier_allow_internet))
    _write_text(task_dir / "environment" / "Dockerfile", _environment_dockerfile())
    _write_text(task_dir / "tests" / "Dockerfile", _tests_dockerfile(verifier_base_image))
    _write_text(task_dir / "tests" / "run_eval.py", _run_eval_py())
    _write_text(task_dir / "tests" / "test.sh", _test_sh(), executable=True)
    _write_text(task_dir / "solution" / "solve.sh", _solve_sh(), executable=True)

    public_reference = task_dir / "environment" / "workspace" / "reference"
    public_reference.mkdir(parents=True, exist_ok=True)

    _copy_public_screenshots(site_dir, manifest, public_reference / "screenshots")

    private_dir = task_dir / "tests" / "private"
    _copytree(site_dir, private_dir / "oracle-site", ignore_extra={"screenshots"})
    shutil.copyfile(manifest_path, private_dir / "screenshot-manifest.json")
    _write_json(private_dir / "metric-config.json", _metric_config(metric_profile))

    _copytree(site_dir, task_dir / "solution" / "oracle-site", ignore_extra={"screenshots", "screenshot-manifest.json"})

    if vendor_evaluator:
        vendor_dir = task_dir / "tests" / "vendor"
        _copytree(PROJECT_ROOT / "website_design_eval", vendor_dir / "website_design_eval")


def main() -> int:
    parser = argparse.ArgumentParser(description="Package a local oracle site as a Harbor website-replication task.")
    parser.add_argument("--site-dir", default="test-site")
    parser.add_argument("--task-dir", default="harbor-tasks/brightpath-replication-001")
    parser.add_argument("--task-name", default="proximal/brightpath-replication-001")
    parser.add_argument(
        "--verifier-base-image",
        default=None,
        help="Reusable verifier Docker image to use as tests/Dockerfile base.",
    )
    parser.add_argument(
        "--metric-profile",
        choices=["lite", "full-local", "full-vlm"],
        default="full-vlm",
        help="Metric config to write into tests/private/metric-config.json.",
    )
    parser.add_argument(
        "--vendor-evaluator",
        action="store_true",
        help="Copy website_design_eval into tests/vendor even when using a reusable verifier image.",
    )
    parser.add_argument(
        "--no-vendor-evaluator",
        action="store_true",
        help="Do not copy website_design_eval into tests/vendor.",
    )
    parser.add_argument(
        "--verifier-allow-internet",
        action="store_true",
        help="Set verifier.environment.allow_internet=true, required for API-backed VLM calls.",
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    vendor_evaluator: bool | None = None
    if args.vendor_evaluator and args.no_vendor_evaluator:
        parser.error("Pass only one of --vendor-evaluator or --no-vendor-evaluator.")
    if args.vendor_evaluator:
        vendor_evaluator = True
    elif args.no_vendor_evaluator:
        vendor_evaluator = False

    package_task(
        PROJECT_ROOT / args.site_dir,
        PROJECT_ROOT / args.task_dir,
        task_name=args.task_name,
        force=args.force,
        verifier_base_image=args.verifier_base_image,
        metric_profile=args.metric_profile,
        vendor_evaluator=vendor_evaluator,
        verifier_allow_internet=args.verifier_allow_internet,
    )
    print(json.dumps({"task_dir": str((PROJECT_ROOT / args.task_dir).resolve()), "task_name": args.task_name}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
