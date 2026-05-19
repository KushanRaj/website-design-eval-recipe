# Harbor Packaging Plan

## Purpose

This note records how Harbor expects tasks to be packaged, how our website
replication task should map into that shape, and what we need to do next.

The main distinction:

- `Generator/` stays in this repository as the dataset/task factory.
- Harbor receives frozen task instances plus verifier code.

## What Harbor Expects

Harbor's native task unit is a directory with these conventional files:

```text
task-name/
  instruction.md
  task.toml
  environment/
    Dockerfile
  tests/
    test.sh
  solution/
    solve.sh
```

Important packaging detail: Harbor's packager collects `task.toml`,
`instruction.md`, optional `README.md`, and recursive contents of
`environment/`, `tests/`, `solution/`, and `steps/`. Arbitrary top-level
folders such as `public/`, `private/`, or `verifier/` should not be assumed to
ship unless they live under one of those recognized directories.

Runtime conventions:

- The agent works in the task environment, usually the Docker image built from
  `environment/Dockerfile`.
- `tests/` is uploaded for verification and appears at `/tests`.
- The verifier must write reward output under `/logs/verifier`.
- Harbor reads `/logs/verifier/reward.json` if present, otherwise falls back to
  `/logs/verifier/reward.txt`.
- Extra logs and diagnostics can also be written under `/logs/verifier`.

## Our Task Shape

For website replication, the agent should receive only the candidate-facing
evidence:

- task instructions
- reference screenshots

The agent should not receive:

- oracle HTML/CSS/JS source
- hidden screenshot manifest selectors/actions
- public capture labels or viewport metadata
- reusable assets, unless the disclosure mode explicitly opts into assets
- generator prompts/specs/critic artifacts
- private evaluator calibration data

Recommended Harbor layout for one task:

```text
brightpath-replication-001/
  README.md
  instruction.md
  task.toml

  environment/
    Dockerfile
    workspace/
      reference/
        screenshots/

  tests/
    Dockerfile
    test.sh
    run_eval.py
    private/
      oracle-site/
      screenshot-manifest.json
      metric-config.json
    vendor/
      website_design_eval/
      research-source-snippets/

  solution/
    solve.sh
```

`environment/workspace/` is the public side. `environment/Dockerfile` should
copy it into the agent workdir, `/app`.

`tests/private/` is the hidden verifier side. It can contain the oracle site,
manifest, and metric configuration because those files are verifier assets, not
agent-facing files.

## Separate Verifier Mode

We should use Harbor's separate verifier environment for this task family.

Reasoning:

- The verifier needs Playwright, image libraries, and possibly model packages.
- The agent should not see oracle source or hidden manifest actions.
- A separate verifier container gives us a cleaner isolation boundary.

Sketch `task.toml`:

```toml
schema_version = "1.1"
artifacts = ["/app"]

[task]
name = "proximal/brightpath-replication-001"
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
allow_internet = false
workdir = "/app"
```

The `artifacts = ["/app"]` entry is important. In separate verifier mode,
configured artifacts are copied from the agent environment into the verifier
environment at the same path. That is how the verifier sees the candidate
website.

## Verifier Contract

`tests/test.sh` should do the minimum orchestration:

1. Locate the candidate website at `/app/site`, falling back to `/app`.
2. Locate hidden oracle artifacts under `/tests/private`.
3. Run the manifest-aware evaluator.
4. Write a Harbor reward file.
5. Preserve full diagnostics.

Example output contract:

```text
/logs/verifier/reward.json
/logs/verifier/metrics.json
/logs/verifier/functional-report.md
/logs/verifier/candidate-capture-plan.json
```

`reward.json` should be small, machine-readable, and flat numeric-only. Put
nested diagnostics and skipped-metric metadata in sidecar files such as
`reward-details.json` and `metrics.json`, not in `reward.json`.

Example:

```json
{
  "reward": 0.73,
  "manifest_coverage": 0.89,
  "screenshot_size_match": 0.94,
  "dreamsim": 0.91,
  "visual_block": 0.62
}
```

The exact aggregation formula is still intentionally undecided. The evaluator
can expose sub-scores now; final reward shaping can come later.

## Current Prototype

The first concrete Harbor-style task is generated from `test-site`:

```bash
uv run python scripts/package_harbor_task.py \
  --site-dir test-site \
  --task-dir harbor-tasks/brightpath-replication-001 \
  --task-name proximal/brightpath-replication-001 \
  --force
```

Generated layout:

```text
harbor-tasks/brightpath-replication-001/
  instruction.md
  task.toml
  environment/
    Dockerfile
    workspace/reference/
      screenshots/
  tests/
    Dockerfile
    test.sh
    run_eval.py
    private/
      oracle-site/
      screenshot-manifest.json
      metric-config.json
    vendor/website_design_eval/
  solution/
    solve.sh
```

The verifier was smoke-tested locally against
`reproductions/claude-attempt-01`:

```bash
TESTS_DIR=harbor-tasks/brightpath-replication-001/tests \
LOG_DIR=metrics-results/harbor-smoke-good-app/logs \
CANDIDATE_ROOT=reproductions/claude-attempt-01 \
uv run bash harbor-tasks/brightpath-replication-001/tests/test.sh
```

Smoke output:

```json
{
  "reward": 0.141751,
  "manifest_coverage": 1.0,
  "screenshot_size_match": 0.947377,
  "pixelmatch": 0.918097,
  "html_text_bleu_1": 0.87054,
  "html_text_rouge_1_recall": 0.916375,
  "capture_count": 9,
  "covered_capture_count": 9
}
```

An exact-oracle smoke using `test-site` as the candidate also resolved all 9
captures and returned exact deterministic lightweight metrics:

```json
{
  "manifest_coverage": 1.0,
  "screenshot_size_match": 1.0,
  "pixelmatch": 1.0,
  "html_text_bleu_1": 1.0,
  "html_text_rouge_1_recall": 1.0
}
```

This is a package-plumbing smoke, not the final reward surface. The prototype
metric config disables API-backed VLM, DreamSim, and visual-block extraction by
default so the first verifier container is dependency-light. Those switches live
in `tests/private/metric-config.json` and can be enabled through environment
overrides once the verifier image vendors the required model/runtime assets.

## Hard Conformance Checks

Current prototype checks:

- `task.toml` parses as TOML.
- `schema_version = "1.1"`.
- Agent workdir is `/app`.
- Separate verifier workdir is `/app`.
- `artifacts = ["/app"]`, so the candidate workspace is transferred to the
  verifier.
- Public evidence is copied into `/app/reference` by `environment/Dockerfile`.
- Candidate output is expected at `/app/site`, with fallback to `/app`.
- Hidden oracle files live under `tests/private`, which is packaged only with
  verifier files and appears at `/tests/private`.
- `tests/test.sh` is executable and writes `/logs/verifier/reward.json`.
- `reward.json` is flat numeric-only; nested diagnostics go to
  `reward-details.json`, `metrics.json`, and Markdown reports.
- Local smoke tests pass against both `reproductions/claude-attempt-01` and
  exact oracle `test-site`.

Actual Harbor lifecycle checks:

- `harbor run --agent nop` now completes with no verifier exception and writes
  `reward.json`. It scores `0.0`, as expected, because `nop` does not create a
  candidate site.
- `harbor run --agent codex --model gpt-5.4-mini` completed a real trial:
  Harbor launched the agent, the agent wrote `/app/site`, Harbor transferred
  `/app` to the separate verifier, the verifier ran, and Harbor consumed
  `reward.json`.

Real Codex-agent Harbor output:

```json
{
  "reward": 0.137557,
  "score": 0.137557,
  "manifest_coverage": 0.860076,
  "screenshot_size_match": 0.922755,
  "pixelmatch": 0.941907,
  "html_text_bleu_1": 0.92696,
  "html_text_rouge_1_recall": 0.941878,
  "capture_count": 9,
  "covered_capture_count": 8
}
```

Real screenshot-only Codex-agent Harbor output:

```json
{
  "reward": 0.142138,
  "score": 0.142138,
  "manifest_coverage": 0.875923,
  "screenshot_size_match": 0.958246,
  "pixelmatch": 0.922549,
  "html_text_bleu_1": 0.935716,
  "html_text_rouge_1_recall": 0.964974,
  "capture_count": 9,
  "covered_capture_count": 8
}
```

Packaging fixes discovered by the actual Harbor run:

- The verifier image must install the Python `playwright` package even when
  using the Playwright base image.
- In lite mode, when DreamSim is skipped, set `dreamsim_device = "cpu"` before
  constructing the evaluator config so the evaluator does not import `torch`
  just to write metadata.
- The Codex adapter installs runtime packages during setup, so the agent
  environment currently needs `allow_internet = true`. The verifier environment
  remains `allow_internet = false`.

## What Goes Where

| Thing | Harbor location | Agent sees it? | Notes |
| --- | --- | --- | --- |
| Task instructions | `instruction.md` | Yes | Describe required output files and constraints. |
| Reference screenshots | `environment/workspace/reference/screenshots/` | Yes | Candidate-facing evidence, neutral filenames only. |
| Assets | `tests/private/oracle-site/assets/` | No | Hidden in the default screenshot-only disclosure mode. |
| Public capture metadata | Not packaged | No | Avoids leaking page/state labels. |
| Oracle site | `tests/private/oracle-site/` | No | Hidden source of truth. |
| Full screenshot manifest | `tests/private/screenshot-manifest.json` | No | Contains replay actions/selectors. |
| Evaluator package | `tests/vendor/website_design_eval/` | No | Verifier runtime dependency. |
| NaturalCC visual-block code | `tests/vendor/research-source-snippets/` | No | Only if we keep visual block enabled. |
| Candidate website | `/app` at runtime | Yes | Produced by the agent, transferred to verifier via `artifacts`. |
| Reward file | `/logs/verifier/reward.json` | No | Harbor consumes this. |
| Diagnostics | `/logs/verifier/metrics.json` etc. | No | Useful for analysis/debugging. |

## What Should Stay Out Of Harbor

Do not package the full `Generator/` folder into each Harbor task.

The generator is a task factory. It can emit task directories, but task
instances should not carry:

- Claude SDK runtime
- generator prompts
- concept/critic/verifier generation transcripts
- `.env` files or API keys
- calibration notebooks
- rejected candidate attempts
- broad research folders not needed by the runtime

## Evaluator Work Needed Before Packaging

Before creating many Harbor tasks, fix the current evaluator blockers:

1. Visual-block/CSSOM state handling
   - Stateful captures must not false-zero when live-state visual-block replay
     is unavailable.
   - Return `unsupported` until the state-aware extractor is implemented.

2. Resolver DOM mutation
   - Candidate action resolution currently injects `data-wde-node-id` into the
     live DOM before artifact capture.
   - Resolver-only mutations must be isolated or cleaned before screenshots,
     `outerHTML`, and CSSOM snapshots.

3. Control matching
   - Form controls should not pass purely because they share an input `type`.
   - Matching should use label/name/accessibility/geometry in addition to type.

4. Verifier filesystem boundary
   - Ensure candidate code cannot read oracle files or verifier outputs.
   - Keep hidden files under `/tests/private` in the verifier environment, not
     in the agent workspace.

5. External metric vendoring
   - `website_design_eval` currently depends on research-source paths for
     visual-block code.
   - For Harbor, vendor the exact runtime subset under `tests/vendor/` or
     disable visual-block in the first package.

## Immediate Implementation Order

1. Fix the evaluator blockers above.
2. Manually build one Harbor task from `test-site`.
3. Run with `harbor run --path <task> --agent oracle` or `--agent nop` to test
   packaging and verifier execution.
4. Run with a real coding agent to inspect candidate-output behavior.
5. Add a generator export command that converts each `AcceptedWebsitePackage`
   into a Harbor task directory.
6. Create a Harbor dataset manifest for the final 10+ tasks.

## Open Decisions

- Which disclosure modes become official task variants:
  - screenshot-only
  - screenshot plus visible text
  - screenshot plus state labels
  - full implementation brief
- Whether DreamSim/CLIP weights are baked into the verifier image or disabled
  for first Harbor runs.
- Whether VLM judging is diagnostic-only or part of reward. Default should be
  diagnostic-only unless Harbor provides a clear secret/API policy.
- Whether visual-block is enabled in v1 or explicitly marked unsupported until
  live-state extraction is fixed.
