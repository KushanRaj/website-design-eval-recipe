from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from .fake_runtime import FakeRuntime
from .io import list_site_files, write_json
from .manifest import manifest_from_concept, run_manifest_capture, write_manifest
from .models import ConceptCandidate, GenerationRequest, SiteSeed
from .pipeline import GeneratorPipeline
from .runtime import ClaudeAgentRuntime
from .verification import deterministic_verify


def _runtime(args: argparse.Namespace):
    if getattr(args, "dry_run", False):
        return FakeRuntime()
    return ClaudeAgentRuntime(model=getattr(args, "model", None), cwd=Path.cwd())


def _metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    return json.loads(raw)


def _print_model(model: Any) -> None:
    if hasattr(model, "model_dump_json"):
        print(model.model_dump_json(indent=2))
    else:
        print(json.dumps(model, indent=2, sort_keys=True))


async def cmd_plan(args: argparse.Namespace) -> int:
    request = GenerationRequest(
        count=args.count,
        prompt=args.prompt,
        metadata=_metadata(args.metadata_json),
        output_root=args.output_root,
        model=args.model,
        replay_manifest=not args.no_replay,
    )
    pipeline = GeneratorPipeline(_runtime(args), output_root=request.output_root)
    plan = await pipeline.create_plan(request)
    if args.out:
        write_json(args.out, plan)
    _print_model(plan)
    return 0


async def cmd_concepts(args: argparse.Namespace) -> int:
    request = GenerationRequest(
        count=1,
        prompt=args.prompt,
        metadata=_metadata(args.metadata_json),
        output_root=args.output_root,
        model=args.model,
        replay_manifest=False,
    )
    seed = SiteSeed(id=args.seed_id, one_liner=args.one_liner, metadata=request.metadata)
    pipeline = GeneratorPipeline(_runtime(args), output_root=request.output_root)
    concept, critique = await pipeline.create_concept(seed, request)
    payload = {"concept": concept.model_dump(), "critique": critique.model_dump()}
    if args.out:
        write_json(args.out, payload)
    _print_model(payload)
    return 0


async def cmd_generate(args: argparse.Namespace) -> int:
    request = GenerationRequest(
        count=args.count,
        prompt=args.prompt,
        metadata=_metadata(args.metadata_json),
        output_root=args.output_root,
        max_concept_rounds=args.max_concept_rounds,
        max_builder_repair_rounds=args.max_builder_repair_rounds,
        replay_manifest=not args.no_replay,
        model=args.model,
    )
    pipeline = GeneratorPipeline(
        _runtime(args),
        output_root=request.output_root,
        run_browser_checks=args.browser_checks,
    )
    result = await pipeline.generate(request)
    _print_model(result)
    return 0


async def cmd_verify(args: argparse.Namespace) -> int:
    concept = ConceptCandidate.model_validate_json(Path(args.concept).read_text(encoding="utf-8"))
    report = deterministic_verify(args.site_dir, concept, run_browser_checks=args.browser_checks)
    if args.out:
        write_json(args.out, report)
    _print_model(report)
    return 0 if report.passed else 1


async def cmd_manifest(args: argparse.Namespace) -> int:
    concept = ConceptCandidate.model_validate_json(Path(args.concept).read_text(encoding="utf-8"))
    manifest = manifest_from_concept(concept, site_name=args.site_name)
    manifest_path = write_manifest(args.site_dir, manifest)
    if args.replay:
        run_manifest_capture(manifest_path)
    payload = {
        "manifest_path": str(manifest_path),
        "site_files": list_site_files(args.site_dir),
        "manifest": manifest.model_dump(),
    }
    if args.out:
        write_json(args.out, payload)
    _print_model(payload)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="website-generator")
    parser.add_argument("--dry-run", action="store_true", help="Use deterministic fake agent outputs")
    parser.add_argument("--model", default=None, help="Claude model alias or ID; defaults to sonnet")
    parser.add_argument("--output-root", default="Generator/output")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan", help="Create only the dataset plan")
    plan.add_argument("--count", type=int, required=True)
    plan.add_argument("--prompt", required=True)
    plan.add_argument("--metadata-json")
    plan.add_argument("--out")
    plan.add_argument("--no-replay", action="store_true")

    concepts = subparsers.add_parser("concepts", help="Generate and critique concepts for one seed")
    concepts.add_argument("--seed-id", default="site-001")
    concepts.add_argument("--one-liner", required=True)
    concepts.add_argument("--prompt", default="Generate a reference website.")
    concepts.add_argument("--metadata-json")
    concepts.add_argument("--out")

    generate = subparsers.add_parser("generate", help="Run the full generation pipeline")
    generate.add_argument("--count", type=int, required=True)
    generate.add_argument("--prompt", required=True)
    generate.add_argument("--metadata-json")
    generate.add_argument("--max-concept-rounds", type=int, default=2)
    generate.add_argument("--max-builder-repair-rounds", type=int, default=2)
    generate.add_argument("--no-replay", action="store_true")
    generate.add_argument("--browser-checks", action="store_true")

    verify = subparsers.add_parser("verify", help="Run deterministic verification on a generated site")
    verify.add_argument("site_dir")
    verify.add_argument("--concept", required=True)
    verify.add_argument("--browser-checks", action="store_true")
    verify.add_argument("--out")

    manifest = subparsers.add_parser("manifest", help="Create/replay a fallback manifest for a site")
    manifest.add_argument("site_dir")
    manifest.add_argument("--concept", required=True)
    manifest.add_argument("--site-name", default="generated-site")
    manifest.add_argument("--replay", action="store_true")
    manifest.add_argument("--out")
    return parser


async def async_main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "plan":
        return await cmd_plan(args)
    if args.command == "concepts":
        return await cmd_concepts(args)
    if args.command == "generate":
        return await cmd_generate(args)
    if args.command == "verify":
        return await cmd_verify(args)
    if args.command == "manifest":
        return await cmd_manifest(args)
    parser.error(f"unknown command: {args.command}")
    return 2


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
