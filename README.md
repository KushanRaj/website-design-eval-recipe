# Website Design Eval Recipe

This repository contains a synthetic website-replication dataset generator, a
browser-state evaluator, Harbor packaging scripts, and Proximal-facing reports
for evaluating screenshot-to-code agents.

The core idea is simple: candidates receive screenshots only, build a website,
and are scored on what the browser renders. The evaluator replays hidden oracle
states, captures screenshots, rendered DOM, CSSOM, bbox geometry, animation
frames, DreamSim, VLM scores, and related metrics, then computes a scalar
reward.

## What Is In The Repo

| Path | Purpose |
| --- | --- |
| `website_design_eval/` | Evaluator, metrics, reward, manifest planning, static server. |
| `Generator/` | Synthetic oracle website generation pipeline. |
| `scripts/` | Packaging, Harbor setup, direct/local run helpers. |
| `agent-image/` | Reusable Harbor agent image with Claude Code preinstalled. |
| `verifier-image/` | Reusable evaluator image with dependencies and model cache setup. |
| `docs/` | Design notes, reward docs, Harbor docs, reports, and handoff notes. |
| `docs/reports/` | Shareable Proximal-facing PDF/HTML reports and compact data tables. |

Generated local datasets and raw run artifacts may exist under `datasets/`,
`harbor-report-data/`, `modal-results/`, and `Generator/output/`. Those are
large generated artifacts and are not all committed by default.

## Current Shareable Reports

- `docs/reports/proximal-reward-report.pdf`
- `docs/reports/task-exhibition-report.pdf`
- `docs/reports/data/react-vs-html-comparison.json`
- `docs/react-vs-html-evaluation-notes.md`

The Proximal report includes the current reward readout, animation notes, and a
React-vs-HTML comparison over four paired sites.

## Install For Local Development

Prerequisites:

- Python with `uv`
- Node.js/npm for React/Solid candidate builds
- Docker with buildx for Harbor image builds
- Harbor CLI for packaged task runs
- `.env` with `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` for full reward runs

Install Python dependencies:

```bash
uv sync
```

Run focused tests:

```bash
uv run python -m unittest \
  website_design_eval.tests.test_candidate_manifest_spa_hash \
  website_design_eval.tests.test_framework_routes \
  website_design_eval.tests.test_static_server \
  website_design_eval.tests.test_harbor_framework_packaging \
  website_design_eval.tests.test_packaged_verifier_candidate_root \
  website_design_eval.tests.test_synthetic_dataset_frameworks \
  website_design_eval.tests.test_reward
```

## Run The Evaluator Directly

Evaluate a reference site and candidate folder:

```bash
uv run website-design-eval evaluate \
  --reference-root test-site \
  --reference-manifest test-site/screenshot-manifest.json \
  --candidate-root reproductions/claude-attempt-01 \
  --profile core \
  --output-dir metrics-results/latest
```

For framework candidates, pass the framework and serve mode:

```bash
uv run website-design-eval evaluate \
  --reference-root path/to/oracle-site \
  --reference-manifest path/to/screenshot-manifest.json \
  --candidate-root path/to/react-candidate \
  --candidate-framework react \
  --candidate-serve-mode spa \
  --output-dir metrics-results/react-candidate
```

React/Solid candidates are built and evaluated from `dist/` when available. The
metrics still score browser-rendered state, not source framework internals.

## Run Pair/Directory Metrics

Run a screenshot pair:

```bash
uv run website-design-eval pair \
  test-site/screenshots/reference/home.desktop.full.png \
  reproductions/claude-attempt-01/screenshots/home.desktop.full.png
```

Run all matching PNG names in two capture directories:

```bash
uv run website-design-eval directory \
  test-site/screenshots/reference \
  reproductions/claude-attempt-01/screenshots
```

Full scoring-function documentation is in `docs/scoring-functions.md`.

## Package And Run Harbor Tasks

From a VM with Docker, Harbor, and `.env` configured:

```bash
bash scripts/setup_harbor_vm.sh
scripts/run_harbor_full_reward.sh datasets/synthetic-website-replication
```

`setup_harbor_vm.sh` builds:

- `website-design-eval-agent-claude:latest`
- `website-design-eval-verifier:latest`
- `datasets/synthetic-website-replication/`

The agent sees only numbered screenshots under `/app/reference/screenshots/`.
Hidden oracle source, screenshot manifests, and metric config live under
`tests/private/` in each packaged task.

For details on VM setup, Modal, resource overrides, GHCR issues, and verifier
artifacts, read:

- `docs/harbor-packaging.md`
- `docs/framework-aware-evaluation.md`
- `docs/candidate-manifest-planning.md`

## Reward And Metric Docs

Start here:

- `docs/evaluation-progress-report.md`
- `docs/reward-curriculum-v0.md`
- `docs/scoring-functions.md`
- `docs/animation-evaluation-design.md`
- `docs/react-vs-html-evaluation-notes.md`

Current reward components include screenshot size, rendered HTML, VLM,
pixelmatch, bbox geometry, CSSOM style, DreamSim, and animation-specific
signals. `visual_block.score` is diagnostic; visual-block matching is still used
for bbox/CSSOM where applicable.

## Documentation Map

| Doc | Read When |
| --- | --- |
| `docs/evaluation-progress-report.md` | You want the current system state. |
| `docs/harbor-packaging.md` | You want to package/run the synthetic dataset in Harbor. |
| `docs/framework-aware-evaluation.md` | You want React/Solid/HTML candidate behavior. |
| `docs/candidate-manifest-planning.md` | You want candidate manifest planning details. |
| `docs/reward-curriculum-v0.md` | You want the scalar reward formula. |
| `docs/scoring-functions.md` | You want metric definitions and CLI surfaces. |
| `docs/animation-evaluation-design.md` | You want animation scoring details. |
| `docs/reports/README.md` | You want the shareable report artifacts. |

## Notes For Sharing

For Proximal-facing sharing, the curated artifacts are the files under
`docs/reports/` plus the design notes above. Raw local run directories are useful
for debugging but are not required to understand the current report.
