# Claude SDK Website Generator

This folder contains the first implementation of the Oracle/reference website
generation pipeline. It is intentionally confined to `Generator/` so the
existing metrics, docs, and project metadata remain untouched.

## Architecture

The pipeline is host-controlled:

```text
GenerationRequest
  -> orchestrator agent -> DatasetPlan + SiteSeed[]
  -> concept agent -> ConceptBatch
  -> critic agent -> ConceptCritique + accepted ConceptCandidate
  -> builder agent writes files directly in the site directory
  -> host lists and validates generated files
  -> deterministic verifier + verifier agent
  -> manifest agent
  -> capture replay
  -> AcceptedWebsitePackage
```

The Claude runtime lives behind `AgentRuntime`. Structured stages use
`run_json(...)`; the builder stage uses `build_site(...)` so the coding agent
actually writes files. Real calls use `ClaudeAgentRuntime`, which lazily imports
`claude_agent_sdk`. Tests and local dry runs use `FakeRuntime`, so no API key is
needed for package verification.

## Artifact Rules

- Every accepted concept must contain at least five pages.
- The builder writes files directly into the generated site directory.
- The host verifies that at least five HTML pages were written.
- `reference_spec.json` is expected inside the generated site directory.
- Screenshot manifests are written after approval as `screenshot-manifest.json`
  inside the generated site folder.
- Capture replay uses the existing root script:
  `scripts/capture-screenshots.mjs`.

## Commands

The project exposes a `website-generator` console script. During local
development, the module form is also available:

```bash
website-generator --dry-run plan --count 3 --prompt "education websites"
website-generator --dry-run generate --count 1 --prompt "education landing page"
python -m Generator.cli --dry-run plan --count 3 --prompt "education websites"
python -m Generator.cli --dry-run generate --count 1 --prompt "education landing page"
```

Real Claude execution uses the same commands without `--dry-run`, assuming the
Claude Agent SDK and Claude Code authentication are available. The default model
is `sonnet`, or `GENERATOR_CLAUDE_MODEL` when set:

```bash
python -m Generator.cli --model sonnet generate --count 5 --prompt "varied education websites"
```

## Retry Policy

- Concept generation retries up to `GenerationRequest.max_concept_rounds`.
- Builder repair retries up to `GenerationRequest.max_builder_repair_rounds`.
- Deterministic contract failures override any model approval.
- Manifest replay failures fail the pipeline for that site; they should be
  repaired before accepting the package.

## Current Boundaries

- Dataset-level diversity auditing is not implemented yet.
- OpenAI is not implemented as a runtime adapter yet.
- Browser-heavy deterministic checks are optional via `--browser-checks`;
  default generation keeps them off to avoid making every dry run slow.
- Real Claude runs require Claude Agent SDK authentication, for example via the
  environment expected by Claude Code / the Claude Agent SDK.
