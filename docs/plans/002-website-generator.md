# Claude SDK Website Generator

## Status Update - 2026-05-20

The generator is no longer only a plan. The current implementation lives under
`Generator/` and has the main host-controlled loop in place:

```text
dataset plan
  -> concept candidates
  -> critic selection/regeneration
  -> builder writes site files
  -> host validates files and runs browser checks
  -> verifier approves or requests repair
  -> manifest agent generates screenshot manifest
  -> replay screenshots
  -> package metadata
```

Important implementation decisions now reflected in code:

- The builder writes directly into the site directory. The host validates path
  hygiene afterward instead of asking the builder for a structured file bundle.
- Managed screenshot output under `site/screenshots/` is ignored during builder
  file validation, so repair loops do not fail because a previous replay created
  PNG files.
- The screenshot manifest is generated after the site passes verification.
- Manifest replay runs with pruning in the generator path. Failed optional
  interaction captures are dropped from the manifest; required no-action captures
  still fail the seed.
- Harbor packaging only copies already-captured screenshots. It does not
  regenerate or repair incomplete screenshots.
- Concept and manifest schemas now include V1 animation intent/captures, but
  animation remains an early track separate from the static reward curriculum.

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
  - Manifest replay prunes failed optional interaction captures and keeps the
    successfully captured high-information states.
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
- Unit-test that managed `screenshots/` outputs are ignored during builder file
  validation.
- Unit-test that failed optional replay captures can be pruned from the manifest.
- Add one integration-style dry run that uses fake agent outputs and existing local metrics, so tests do not require API keys.

## Assumptions
- Use Claude as the only real agent backend in v1; keep the runtime interface narrow enough to add OpenAI later.
- Use host-controlled orchestration rather than manager-agent autonomy, because loops, retries, artifact writing, and verification need deterministic control.
- Builder writes files directly; the host runs path-hygiene validation over
  whatever the agent produced (no abs paths, no traversal, allowed suffixes,
  index.html present).
- Default model is configurable via env/CLI, with `sonnet` as the practical Claude SDK default unless the user overrides it.
- Generated run outputs under `Generator/output/` are artifacts, not hand-authored
  source. Commit policy should keep code/docs/tests separate from large generated
  site runs unless a run is intentionally promoted into the dataset.
