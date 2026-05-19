# Claude SDK Website Generator

## Summary
Build `Generator/` as a Python package for the Oracle/reference website generation pipeline, using **Claude Agent SDK** as the default agent runtime. The current docs point to `claude-agent-sdk` with `claude_agent_sdk` imports, and support structured outputs, tools, permissions, hooks, subagents, and MCP, so the implementation should not use stale `claude-code-sdk` examples. citeturn2search1turn2search0

## Key Changes
- Add dependencies: `claude-agent-sdk`, direct `pydantic`, and test tooling if missing. Keep OpenAI as a future adapter only; v1 defaults to Claude because that is the requested preference.
- Add `Generator/` with a host-controlled pipeline:
  - Orchestrator creates dataset plan and one-line seeds.
  - Concept agent generates 5-6 typed concept candidates.
  - Critic agent picks/regenerates concepts.
  - Builder agent is a free-form coding agent: it writes website files
    directly into the site directory via Write/Edit/MultiEdit/Read/LS/Glob/Grep/Bash.
    The host does NOT collect a structured file bundle — the original plan
    called for one, but that fights how coding agents actually work.
  - Host validates path hygiene over the files the agent wrote, renders with
    Playwright, runs local checks, then calls verifier.
  - Manifest agent creates screenshot manifest only after approval.
- Use Pydantic schemas for all artifacts: request, dataset plan, concept candidates, critic report, website bundle, verifier report, repair instructions, screenshot manifest, and final package metadata.
- Integrate existing repo capabilities instead of duplicating them:
  - Reuse `scripts/capture-screenshots.mjs` for manifest replay.
  - Reuse `website_design_eval` checks for render sanity, mobile overflow, accessibility controls, WebCoderBench-style tags, and screenshot diagnostics.
  - Keep existing visual/block scoring unchanged; generator uses it as QA signal, not as a rewritten reward.
- Add CLI entrypoint, likely `website-generator`, with commands:
  - `plan`: produce dataset plan only.
  - `concepts`: generate/critique concepts only.
  - `generate`: run end-to-end site generation.
  - `verify`: rerun verification on an existing generated site.
  - `manifest`: regenerate/replay manifests for an accepted site.
- Add docs under `docs/`, extending the existing WebSight recipe notes with the concrete Claude SDK implementation flow, artifact shapes, retry budgets, and how verifier feedback maps back into builder repair.

## Test Plan
- Unit-test schema validation for valid/invalid request, concept, bundle, verifier, and manifest objects.
- Unit-test safe file writing: reject absolute paths, parent traversal, duplicate paths, missing `index.html`, missing assets, and unsupported file types.
- Unit-test pipeline control with a fake Claude runtime: concept regeneration, critic acceptance, builder repair, verifier approval/rejection, retry exhaustion.
- Smoke-test manifest replay against a tiny generated static site using the existing Playwright capture script.
- Add one integration-style dry run that uses fake agent outputs and existing local metrics, so tests do not require API keys.

## Assumptions
- Use Claude as the only real agent backend in v1; keep the runtime interface narrow enough to add OpenAI later.
- Use host-controlled orchestration rather than manager-agent autonomy, because loops, retries, artifact writing, and verification need deterministic control.
- Builder writes files directly; the host runs path-hygiene validation over
  whatever the agent produced (no abs paths, no traversal, allowed suffixes,
  index.html present).
- Default model is configurable via env/CLI, with `sonnet` as the practical Claude SDK default unless the user overrides it.
- No repo-tracked files are changed until Plan Mode ends.
