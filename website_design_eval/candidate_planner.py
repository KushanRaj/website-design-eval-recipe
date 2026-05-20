from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from .manifest_generator import (
    ClaudeAuthMode,
    ClaudeManifestGenerationError,
    MANIFEST_OUTPUT_SCHEMA,
    _browser_inventory,
    _claude_options,
    _claude_subprocess_env,
    _is_transient_claude_error,
    _load_dotenv,
    _manifest_site_root,
    _normalize_anthropic_key,
    _query_claude_manifest,
    _sanitize_manifest_with_inventory,
)

PathLike = str | os.PathLike[str]


def _enabled_capture(capture: dict[str, Any]) -> bool:
    return capture.get("enabled", True) is not False


def _oracle_capture_prior(reference_manifest: dict[str, Any]) -> list[dict[str, Any]]:
    captures = []
    for capture in reference_manifest.get("captures") or []:
        if not isinstance(capture, dict) or not _enabled_capture(capture):
            continue
        captures.append(
            {
                key: capture[key]
                for key in ("id", "weight", "page", "state", "intent", "path", "viewport", "actions", "screenshot")
                if key in capture
            }
        )
    return captures


def _oracle_animation_prior(reference_manifest: dict[str, Any]) -> list[dict[str, Any]]:
    animations = []
    for animation in reference_manifest.get("animations") or []:
        if not isinstance(animation, dict) or not _enabled_capture(animation):
            continue
        animations.append(
            {
                key: animation[key]
                for key in ("id", "kind", "weight", "page", "path", "viewport", "trigger", "timeline", "targets")
                if key in animation
            }
        )
    return animations


def _reference_animation_evidence(
    oracle_animations: list[dict[str, Any]],
    reference_inventory: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not reference_inventory:
        return []
    pages_by_path = {
        page.get("path"): page
        for page in reference_inventory.get("pages") or []
        if isinstance(page, dict) and page.get("path")
    }
    evidence = []
    for animation in oracle_animations:
        page = pages_by_path.get(animation.get("path"))
        if not page:
            continue
        elements = []
        for group in ("controls", "interaction_candidates", "sections"):
            for element in page.get(group) or []:
                if isinstance(element, dict):
                    compact = {
                        key: element.get(key)
                        for key in (
                            "selector",
                            "tag",
                            "role",
                            "class_name",
                            "text",
                            "accessible_name",
                            "bbox_px",
                        )
                        if element.get(key) not in (None, "")
                    }
                    compact["source_group"] = group
                    elements.append(compact)

        selectors = set()
        trigger = animation.get("trigger") or {}
        if trigger.get("selector"):
            selectors.add(str(trigger["selector"]))
        for target in animation.get("targets") or []:
            if isinstance(target, dict) and target.get("selector"):
                selectors.add(str(target["selector"]))

        matches = []
        seen = set()
        for element in elements:
            selector = element.get("selector")
            if selector in selectors and selector not in seen:
                matches.append(element)
                seen.add(selector)

        evidence.append(
            {
                "id": animation.get("id"),
                "path": animation.get("path"),
                "trigger_selector": trigger.get("selector"),
                "target_selectors": [
                    target.get("selector")
                    for target in animation.get("targets") or []
                    if isinstance(target, dict) and target.get("selector")
                ],
                "matched_reference_elements": matches,
            }
        )
    return evidence


def _html_path_to_spa_probe(path: str) -> str | None:
    if not path:
        return None
    path = path if path.startswith("/") else f"/{path}"
    if path in {"/", "/index.html"}:
        return "/"
    if path.endswith(".html"):
        return path[:-5] or "/"
    return path


def _candidate_route_probes(
    oracle_captures: list[dict[str, Any]],
    oracle_animations: list[dict[str, Any]],
) -> list[str]:
    probes: list[str] = ["/", "/index.html"]
    for item in [*oracle_captures, *oracle_animations]:
        path = item.get("path") or item.get("urlPath")
        if not isinstance(path, str) or not path:
            continue
        normalized = path if path.startswith("/") else f"/{path}"
        probes.append(normalized)
        spa_probe = _html_path_to_spa_probe(normalized)
        if spa_probe:
            probes.append(spa_probe)
    seen: set[str] = set()
    unique: list[str] = []
    for probe in probes:
        if probe not in seen:
            seen.add(probe)
            unique.append(probe)
    return unique


def _candidate_planner_prompt(
    *,
    oracle_captures: list[dict[str, Any]],
    oracle_animations: list[dict[str, Any]],
    oracle_animation_evidence: list[dict[str, Any]],
    candidate_inventory: dict[str, Any],
    candidate_framework: str,
    candidate_serve_mode: str,
    output_path: Path,
) -> str:
    return f"""
You are generating a candidate capture manifest for a website design evaluator.

The oracle manifest below is already frozen at dataset creation time. Your job is
not to make a new oracle manifest. Your job is to inspect the candidate website
inventory and produce a candidate manifest whose captures align to the oracle
captures by id.

Candidate framework: {candidate_framework}
Candidate serve mode: {candidate_serve_mode}

If the candidate serve mode is "spa", candidate routes may be idiomatic client
routes such as /minerals instead of /minerals.html. Use browser-rendered route
inventory and oracle-path probes to choose the candidate path that renders the
same page/state. Do not require the candidate to mimic static .html filenames.

For each oracle capture:
- Preserve the oracle capture id exactly.
- Preserve the oracle-visible intent/state, not the oracle route name, exact
  selector, or exact interaction.
- Choose the candidate route/path that best reaches the same visible page/state.
- Choose the candidate actions that actually reproduce that visible state.
- If the oracle used hover but the candidate uses click, use click.
- If the oracle used click but the candidate uses a tab, summary, accordion, or
  menu button to reach the same visible state, use that action.
- If the visible state cannot be reproduced from the candidate inventory, omit
  that capture. The evaluator will score it as missing coverage.

For each oracle animation:
- Preserve the oracle animation id exactly.
- Preserve the oracle animation intent, channels, timeline, and viewport.
- Choose the candidate route/path, trigger selector/action, and target
  selector(s) that best reproduce the same animated element/state.
- The trigger selector and target selector may be different elements.
- Use the oracle animation evidence to distinguish similarly named elements.
  For example, if the oracle target evidence is a large card and the trigger is
  a map marker, choose the candidate card as the target even when the marker is
  also clickable.
- If the corresponding candidate animation cannot be identified from the
  candidate browser inventory and source files, omit that animation. The
  evaluator will score it as missing animation coverage.

Do not invent routes or selectors. Use only paths and selector_candidates shown
in the candidate browser inventory. Prefer selector_candidates with count=1.
Prefer data_attr, id, name, aria_label, and semantic selectors over nth_path.
Use waitForSelector after a reveal action when the revealed state has a clear
candidate selector.

The final answer must be one JSON object only and must follow this schema:
{json.dumps(MANIFEST_OUTPUT_SCHEMA, indent=2)}

The caller will write the output to:
{output_path}

Oracle captures to align:
{json.dumps(oracle_captures, indent=2)}

Oracle animations to align:
{json.dumps(oracle_animations, indent=2)}

Oracle animation target/trigger evidence:
{json.dumps(oracle_animation_evidence, indent=2)}

Candidate browser-rendered inventory:
{json.dumps(candidate_inventory, indent=2)}
""".strip()


async def _generate_candidate_manifest_claude_code_async(
    *,
    candidate_root: Path,
    output_path: Path,
    model: str,
    oracle_captures: list[dict[str, Any]],
    oracle_animations: list[dict[str, Any]],
    oracle_animation_evidence: list[dict[str, Any]],
    candidate_inventory: dict[str, Any],
    candidate_framework: str,
    candidate_serve_mode: str,
    auth_mode: ClaudeAuthMode,
) -> dict[str, Any]:
    from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, query

    if not candidate_inventory.get("pages"):
        raise ValueError(f"No browser-rendered pages found in {candidate_root}")

    options = _claude_options(
        ClaudeAgentOptions,
        system_prompt=(
            "You are a precise candidate capture planner for website design evaluation. "
            "Return only valid JSON."
        ),
        model=model,
        cwd=candidate_root,
        max_turns=16,
        tools=["Read", "LS", "Glob", "Grep"],
        allowed_tools=["Read", "LS", "Glob", "Grep"],
        disallowed_tools=["Bash", "Write", "Edit", "MultiEdit", "NotebookEdit"],
        setting_sources=[],
        output_format={"type": "json_schema", "schema": MANIFEST_OUTPUT_SCHEMA},
        env=_claude_subprocess_env(auth_mode),
    )

    prompt = _candidate_planner_prompt(
        oracle_captures=oracle_captures,
        oracle_animations=oracle_animations,
        oracle_animation_evidence=oracle_animation_evidence,
        candidate_inventory=candidate_inventory,
        candidate_framework=candidate_framework,
        candidate_serve_mode=candidate_serve_mode,
        output_path=output_path,
    )
    prompt_path = output_path.with_name(f"{output_path.stem}.prompt.txt")
    transcript_path = output_path.with_name(f"{output_path.stem}.claude-transcript.jsonl")
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(prompt, encoding="utf-8")
    if transcript_path.exists():
        transcript_path.unlink()
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
                transcript_path=transcript_path,
                transcript_context={
                    "planner": "candidate_manifest",
                    "attempt": attempt,
                    "model": model,
                    "max_turns": 16,
                    "candidate_root": str(candidate_root),
                    "output_path": str(output_path),
                    "candidate_framework": candidate_framework,
                    "candidate_serve_mode": candidate_serve_mode,
                },
            )
            break
        except ClaudeManifestGenerationError as exc:
            error_text = str(exc)
            if attempt < max_attempts and _is_transient_claude_error(error_text):
                await asyncio.sleep(2**attempt)
                continue
            if _is_transient_claude_error(error_text):
                raise ClaudeManifestGenerationError(
                    f"Claude Code candidate planning failed after {max_attempts} attempts: {error_text}"
                ) from exc
            raise

    if parsed is None:
        raise RuntimeError("Claude Code candidate planning did not return a manifest")

    sanitized = _sanitize_manifest_with_inventory(
        candidate_root,
        parsed,
        max_captures=None,
        inventory=candidate_inventory,
    )
    oracle_by_id = {str(capture["id"]): capture for capture in oracle_captures if capture.get("id")}
    candidate_by_id = {str(capture["id"]): capture for capture in sanitized.get("captures") or []}
    aligned_captures = []
    for capture_id, oracle_capture in oracle_by_id.items():
        candidate_capture = candidate_by_id.get(capture_id)
        if not candidate_capture:
            continue
        merged = dict(candidate_capture)
        for key in ("id", "weight", "state", "intent", "viewport", "screenshot"):
            if key in oracle_capture:
                merged[key] = oracle_capture[key]
        merged["oracle_path"] = oracle_capture.get("path")
        merged["candidate_path"] = candidate_capture.get("path")
        aligned_captures.append(merged)

    oracle_animations_by_id = {
        str(animation["id"]): animation for animation in oracle_animations if animation.get("id")
    }
    candidate_animations_by_id = {
        str(animation["id"]): animation
        for animation in sanitized.get("animations") or []
        if isinstance(animation, dict) and animation.get("id")
    }
    aligned_animations = []
    for animation_id, oracle_animation in oracle_animations_by_id.items():
        candidate_animation = candidate_animations_by_id.get(animation_id)
        if not candidate_animation:
            continue
        merged = dict(candidate_animation)
        for key in ("id", "kind", "weight", "page", "viewport", "timeline", "enabled"):
            if key in oracle_animation:
                merged[key] = oracle_animation[key]
        merged["oracle_path"] = oracle_animation.get("path")
        merged["candidate_path"] = candidate_animation.get("path")

        oracle_targets = oracle_animation.get("targets") or []
        candidate_targets = candidate_animation.get("targets") or []
        merged_targets = []
        for index, candidate_target in enumerate(candidate_targets):
            oracle_target = oracle_targets[index] if index < len(oracle_targets) else {}
            merged_target = dict(candidate_target)
            for key in ("name", "channels", "track"):
                if key in oracle_target:
                    merged_target[key] = oracle_target[key]
            merged_targets.append(merged_target)
        if merged_targets:
            merged["targets"] = merged_targets
        aligned_animations.append(merged)

    manifest = dict(sanitized)
    manifest["site"] = dict(manifest.get("site") or {})
    manifest["site"]["root"] = _manifest_site_root(candidate_root, output_path)
    manifest["captures"] = aligned_captures
    manifest["animations"] = aligned_animations
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, indent=2, sort_keys=False), encoding="utf-8")
    return {
        "manifest": manifest,
        "output_path": str(output_path),
        "model": model,
        "backend": "claude-code",
        "auth_mode": auth_mode,
        "page_count": len(candidate_inventory.get("pages") or []),
        "inventory_source": candidate_inventory.get("source"),
        "oracle_capture_count": len(oracle_captures),
        "capture_count": len(aligned_captures),
        "missing_capture_ids": [capture_id for capture_id in oracle_by_id if capture_id not in candidate_by_id],
        "oracle_animation_count": len(oracle_animations),
        "animation_count": len(aligned_animations),
        "missing_animation_ids": [
            animation_id for animation_id in oracle_animations_by_id if animation_id not in candidate_animations_by_id
        ],
    }


def generate_candidate_manifest(
    oracle_manifest_path: PathLike,
    candidate_root: PathLike,
    output_path: PathLike,
    *,
    model: str = "opus",
    repo_root: PathLike | None = None,
    reference_root: PathLike | None = None,
    backend: str = "claude-code",
    claude_auth: ClaudeAuthMode = "api",
    candidate_framework: str = "html",
    candidate_serve_mode: str = "static",
) -> dict[str, Any]:
    if backend != "claude-code":
        raise ValueError(f"Unknown candidate planner backend: {backend}")
    if claude_auth not in {"api", "subscription"}:
        raise ValueError(f"Unknown Claude auth mode: {claude_auth}")
    if repo_root is not None:
        _load_dotenv(Path(repo_root) / ".env")
    if claude_auth == "api":
        _normalize_anthropic_key()
    if claude_auth == "api" and not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is required for Claude Code candidate manifest planning")

    root = Path(candidate_root).resolve()
    output = Path(output_path).resolve()
    reference_manifest = json.loads(Path(oracle_manifest_path).read_text(encoding="utf-8"))
    oracle_captures = _oracle_capture_prior(reference_manifest)
    oracle_animations = _oracle_animation_prior(reference_manifest)
    reference_inventory = _browser_inventory(Path(reference_root).resolve()) if reference_root else None
    oracle_animation_evidence = _reference_animation_evidence(oracle_animations, reference_inventory)
    route_probes = _candidate_route_probes(oracle_captures, oracle_animations)
    inventory = _browser_inventory(root, serve_mode=candidate_serve_mode, route_paths=route_probes)
    inventory["candidate_framework"] = candidate_framework
    inventory["oracle_path_probes"] = route_probes
    return asyncio.run(
        _generate_candidate_manifest_claude_code_async(
            candidate_root=root,
            output_path=output,
            model=model,
            oracle_captures=oracle_captures,
            oracle_animations=oracle_animations,
            oracle_animation_evidence=oracle_animation_evidence,
            candidate_inventory=inventory,
            candidate_framework=candidate_framework,
            candidate_serve_mode=candidate_serve_mode,
            auth_mode=claude_auth,
        )
    )
