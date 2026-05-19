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


def _candidate_planner_prompt(
    *,
    oracle_captures: list[dict[str, Any]],
    candidate_inventory: dict[str, Any],
    output_path: Path,
) -> str:
    return f"""
You are generating a candidate capture manifest for a website design evaluator.

The oracle manifest below is already frozen at dataset creation time. Your job is
not to make a new oracle manifest. Your job is to inspect the candidate website
inventory and produce a candidate manifest whose captures align to the oracle
captures by id.

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

Candidate browser-rendered inventory:
{json.dumps(candidate_inventory, indent=2)}
""".strip()


async def _generate_candidate_manifest_claude_code_async(
    *,
    candidate_root: Path,
    output_path: Path,
    model: str,
    oracle_captures: list[dict[str, Any]],
    candidate_inventory: dict[str, Any],
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
        max_turns=8,
        tools=["Read", "LS", "Glob", "Grep"],
        allowed_tools=["Read", "LS", "Glob", "Grep"],
        disallowed_tools=["Bash", "Write", "Edit", "MultiEdit", "NotebookEdit"],
        permission_mode="bypassPermissions",
        setting_sources=[],
        output_format={"type": "json_schema", "schema": MANIFEST_OUTPUT_SCHEMA},
        env=_claude_subprocess_env(auth_mode),
    )

    prompt = _candidate_planner_prompt(
        oracle_captures=oracle_captures,
        candidate_inventory=candidate_inventory,
        output_path=output_path,
    )
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

    manifest = dict(sanitized)
    manifest["site"] = dict(manifest.get("site") or {})
    manifest["site"]["root"] = _manifest_site_root(candidate_root, output_path)
    manifest["captures"] = aligned_captures
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
    }


def generate_candidate_manifest(
    oracle_manifest_path: PathLike,
    candidate_root: PathLike,
    output_path: PathLike,
    *,
    model: str = "opus",
    repo_root: PathLike | None = None,
    backend: str = "claude-code",
    claude_auth: ClaudeAuthMode = "api",
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
    inventory = _browser_inventory(root)
    return asyncio.run(
        _generate_candidate_manifest_claude_code_async(
            candidate_root=root,
            output_path=output,
            model=model,
            oracle_captures=oracle_captures,
            candidate_inventory=inventory,
            auth_mode=claude_auth,
        )
    )
