from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

from website_design_eval.scoring import WEB2CODE_DIMENSION_NAMES, vlm_judge_score


REPO_ROOT = Path(__file__).resolve().parents[1]


def log(message: str) -> None:
    print(f"[vlm-variance] {message}", file=sys.stderr, flush=True)


def load_dotenv(path: Path) -> None:
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


def metric_call(model: str, reference: str, candidate: str) -> dict[str, Any]:
    try:
        return vlm_judge_score(reference, candidate, model=model)
    except Exception as exc:
        return {
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(limit=8),
            }
        }


def collect_jobs(source: dict[str, Any], models: list[str], repeats: int) -> list[dict[str, Any]]:
    jobs = []
    for candidate_name, candidate in source["candidates"].items():
        for capture_id, pair in candidate["pairs"].items():
            for model in models:
                for repeat in range(1, repeats + 1):
                    jobs.append(
                        {
                            "candidate": candidate_name,
                            "capture": capture_id,
                            "model": model,
                            "repeat": repeat,
                            "reference_screenshot": pair["reference_screenshot"],
                            "candidate_screenshot": pair["candidate_screenshot"],
                        }
                    )
    return jobs


def fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return ""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value).replace("\n", " ")


def md_table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return "_No rows._\n"
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(fmt(value).replace("|", "\\|") for value in row) + " |")
    return "\n".join(lines) + "\n"


def numeric_scores(runs: list[dict[str, Any]], key: str = "overall") -> list[float]:
    scores = []
    for run in runs:
        score = run.get("result", {}).get(key)
        if isinstance(score, int | float):
            scores.append(float(score))
    return scores


def summarize(result: dict[str, Any]) -> dict[str, Any]:
    by_model_candidate_run: dict[tuple[str, str, int], list[float]] = {}
    by_model_candidate_capture: dict[tuple[str, str, str], list[dict[str, Any]]] = {}

    for run in result["runs"]:
        model = run["model"]
        candidate = run["candidate"]
        capture = run["capture"]
        repeat = int(run["repeat"])
        overall = run.get("result", {}).get("overall")
        if isinstance(overall, int | float):
            by_model_candidate_run.setdefault((model, candidate, repeat), []).append(float(overall))
        by_model_candidate_capture.setdefault((model, candidate, capture), []).append(run)

    aggregate_rows = []
    models = sorted({run["model"] for run in result["runs"]})
    candidates = sorted({run["candidate"] for run in result["runs"]})
    for model in models:
        for candidate in candidates:
            repeat_means = []
            for repeat in sorted({run["repeat"] for run in result["runs"]}):
                values = by_model_candidate_run.get((model, candidate, repeat), [])
                repeat_means.append(mean(values) if values else None)
            available = [value for value in repeat_means if value is not None]
            aggregate_rows.append(
                {
                    "model": model,
                    "candidate": candidate,
                    "repeat_means": repeat_means,
                    "mean": mean(available) if available else None,
                    "std": pstdev(available) if len(available) > 1 else 0.0 if available else None,
                    "min": min(available) if available else None,
                    "max": max(available) if available else None,
                }
            )

    capture_rows = []
    for (model, candidate, capture), runs in sorted(by_model_candidate_capture.items()):
        runs = sorted(runs, key=lambda item: item["repeat"])
        scores = numeric_scores(runs)
        dimension_stds: dict[str, float | None] = {}
        for dimension in WEB2CODE_DIMENSION_NAMES:
            values = [
                float(run["result"]["dimensions"][dimension])
                for run in runs
                if isinstance(run.get("result", {}).get("dimensions", {}).get(dimension), int | float)
            ]
            dimension_stds[dimension] = pstdev(values) if len(values) > 1 else 0.0 if values else None
        capture_rows.append(
            {
                "model": model,
                "candidate": candidate,
                "capture": capture,
                "scores": scores,
                "mean": mean(scores) if scores else None,
                "std": pstdev(scores) if len(scores) > 1 else 0.0 if scores else None,
                "min": min(scores) if scores else None,
                "max": max(scores) if scores else None,
                "dimension_stds": dimension_stds,
                "errors": [run["result"]["error"] for run in runs if "error" in run.get("result", {})],
            }
        )

    result["summary"] = {
        "aggregate_rows": aggregate_rows,
        "capture_rows": capture_rows,
        "error_count": sum(1 for run in result["runs"] if "error" in run.get("result", {})),
    }
    return result


def write_report(result: dict[str, Any], path: Path) -> None:
    aggregate_rows = [
        [
            row["model"],
            row["candidate"],
            *(row["repeat_means"] + [None, None, None])[:3],
            row["mean"],
            row["std"],
            row["min"],
            row["max"],
        ]
        for row in result["summary"]["aggregate_rows"]
    ]
    capture_rows = [
        [
            row["model"],
            row["candidate"],
            row["capture"],
            *(row["scores"] + [None, None, None])[:3],
            row["mean"],
            row["std"],
            row["min"],
            row["max"],
            len(row["errors"]),
        ]
        for row in result["summary"]["capture_rows"]
    ]
    worst_rows = sorted(
        result["summary"]["capture_rows"],
        key=lambda row: -1 if row["std"] is None else row["std"],
        reverse=True,
    )[:12]
    worst_rows_md = [
        [
            row["model"],
            row["candidate"],
            row["capture"],
            row["std"],
            row["min"],
            row["max"],
            row["scores"],
        ]
        for row in worst_rows
    ]

    lines = [
        "# VLM Judge Variability",
        "",
        f"Generated at: `{result['metadata']['generated_at']}`",
        "",
        f"Source metrics: `{result['metadata']['source']}`",
        "",
        "Scores are the Web2Code-style VLM overall values on a 0-1 scale.",
        "",
        "## Aggregate By Candidate",
        "",
        md_table(["Model", "Candidate", "Run 1", "Run 2", "Run 3", "Mean", "Std", "Min", "Max"], aggregate_rows),
        "## Highest Per-Capture Variation",
        "",
        md_table(["Model", "Candidate", "Capture", "Std", "Min", "Max", "Runs"], worst_rows_md),
        "## Per-Capture Overall Scores",
        "",
        md_table(
            ["Model", "Candidate", "Capture", "Run 1", "Run 2", "Run 3", "Mean", "Std", "Min", "Max", "Errors"],
            capture_rows,
        ),
        "## Runtime",
        "",
        md_table(
            ["Key", "Value"],
            [
                ["Models", result["metadata"]["models"]],
                ["Repeats", result["metadata"]["repeats"]],
                ["Workers", result["metadata"]["workers"]],
                ["Elapsed seconds", result["metadata"]["elapsed_seconds"]],
                ["Total calls", len(result["runs"])],
                ["Errors", result["summary"]["error_count"]],
            ],
        ),
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rerun VLM judge and measure reproducibility.")
    parser.add_argument("--source", default="metrics-results/2026-05-19-full-rerun/full-metrics.json")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--model", action="append", default=None)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--workers", type=int, default=4)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.model is None:
        args.model = ["gpt-5.4-mini", "gpt-5.5"]
    load_dotenv(REPO_ROOT / ".env")
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set")

    source_path = (REPO_ROOT / args.source).resolve() if not Path(args.source).is_absolute() else Path(args.source)
    source = json.loads(source_path.read_text(encoding="utf-8"))
    output_dir = (
        Path(args.output_dir).resolve()
        if args.output_dir
        else REPO_ROOT / "metrics-results" / f"{datetime.now().strftime('%Y-%m-%d-%H%M%S')}-vlm-variability"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    jobs = collect_jobs(source, args.model, args.repeats)
    started = time.time()
    result = {
        "metadata": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "source": str(source_path),
            "models": args.model,
            "repeats": args.repeats,
            "workers": args.workers,
        },
        "runs": [],
    }

    log(f"running {len(jobs)} VLM calls")
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_map = {
            executor.submit(metric_call, job["model"], job["reference_screenshot"], job["candidate_screenshot"]): job
            for job in jobs
        }
        done = 0
        for future in as_completed(future_map):
            job = future_map[future]
            done += 1
            result["runs"].append({**job, "result": future.result()})
            log(f"{done}/{len(jobs)} {job['model']} {job['candidate']} {job['capture']} repeat={job['repeat']}")

    result["metadata"]["elapsed_seconds"] = round(time.time() - started, 3)
    summarize(result)
    raw_path = output_dir / "vlm-variability.json"
    report_path = output_dir / "report.md"
    raw_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    write_report(result, report_path)
    print(json.dumps({"raw": str(raw_path), "report": str(report_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
