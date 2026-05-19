# Harbor Packaging

## Purpose

This note records the current Harbor path for the synthetic website replication
dataset.

The main split:

- `Generator/output/harbor-dataset/` is the source dataset produced by our
  generator. It contains the oracle site, frozen reference screenshots, and the
  oracle replay manifest for each task.
- `datasets/synthetic-website-replication/` is the local Harbor task set
  generated from that source dataset. It is build output, not hand-authored
  source.
- `verifier-image/` builds one reusable evaluator image shared by every task.

## One-VM Setup

From a clean VM with this repo cloned, Docker running, Harbor installed, and
`.env` containing `OPENAI_API_KEY` plus either `ANTHROPIC_API_KEY` or
`CLAUDE_CODE_OAUTH_TOKEN`:

```bash
bash scripts/setup_harbor_vm.sh
scripts/run_harbor_full_reward.sh
```

`setup_harbor_vm.sh` does two things:

1. Builds `website-design-eval-verifier:latest`.
2. Packages all generated sites under `Generator/output/harbor-dataset/` into
   `datasets/synthetic-website-replication/`.

The default run uses:

- Harbor agent: `claude-code`
- Claude model: `claude-opus-4-7`
- Verifier metric profile: `full-vlm`
- Concurrent trials: `1` unless `WDE_HARBOR_N_CONCURRENT` is set

Useful overrides:

```bash
WDE_VERIFIER_IMAGE=registry.example.com/wde-verifier:tag
WDE_SYNTHETIC_SITE_ROOT=Generator/output/harbor-dataset
WDE_HARBOR_DATASET_DIR=datasets/synthetic-website-replication
WDE_HARBOR_DATASET_NAME=proximal/synthetic-website-replication
WDE_HARBOR_AGENT=claude-code
WDE_HARBOR_MODEL=claude-opus-4-7
WDE_HARBOR_N_CONCURRENT=4
```

## Harbor Layout

Harbor local `--path` runs look for task directories directly under the path.
That means the local synthetic dataset is laid out like this:

```text
datasets/synthetic-website-replication/
  dataset.toml
  botanical-garden-nursery/
    instruction.md
    task.toml
    environment/
    tests/
    solution/
  curling-federation/
  ...
```

The `dataset.toml` is still generated because it pins task content hashes for
publishing/syncing, but local execution does not depend on registry download
semantics:

```bash
harbor run -p datasets/synthetic-website-replication -a claude-code -m claude-opus-4-7
```

## Agent-Facing Evidence

The agent sees only:

```text
/app/reference/screenshots/001.png
/app/reference/screenshots/002.png
...
```

The prompt is intentionally simple: reproduce the website design shown in the
screenshots and write the implementation under `/app/site`.

The agent does not see:

- oracle HTML/CSS/JS source
- `screenshot-manifest.json`
- capture IDs or labels
- generator seed/spec/critic artifacts
- hidden metric config
- evaluator implementation details

The source dataset has richer files because it is our generation artifact. The
packaged Harbor task is the isolation boundary.

## Hidden Verifier Inputs

Each task packages hidden verifier assets under `tests/private/`:

```text
tests/private/
  oracle-site/
  screenshot-manifest.json
  metric-config.json
```

The verifier runs in a separate environment. Harbor copies `/app` from the
agent container to the verifier container through `artifacts = ["/app"]`, so
the verifier receives the candidate site but the agent never receives hidden
oracle files.

## Reusable Verifier Image

There is one verifier image for all tasks, not one verifier image per task.

`verifier-image/build.sh` creates `website-design-eval-verifier:latest` and
copies the current `website_design_eval/` package into `/opt/wde`. It also
installs the runtime dependencies and preloads DreamSim ensemble weights into
`/opt/wde/models/dreamsim`.

When evaluator code changes, rebuild the image:

```bash
WDE_VERIFIER_IMAGE=website-design-eval-verifier:latest bash verifier-image/build.sh
```

Then regenerate the Harbor task set so each task points at the intended image:

```bash
python scripts/package_synthetic_dataset.py \
  --source-root Generator/output/harbor-dataset \
  --dataset-dir datasets/synthetic-website-replication \
  --dataset-name proximal/synthetic-website-replication \
  --verifier-base-image website-design-eval-verifier:latest \
  --metric-profile full-vlm \
  --verifier-allow-internet \
  --force
```

For a remote VM pool, push the verifier image to a registry and pass that
registry tag as `--verifier-base-image`. For the current one-VM path, a local
Docker image is enough.

## Reward Contract

The verifier writes:

```text
/logs/verifier/reward.json
/logs/verifier/reward-details.json
/logs/verifier/metrics.json
/logs/verifier/reward-report.md
/logs/verifier/functional-report.md
/logs/verifier/candidate-capture-plan.json
```

`reward.json` is flat and numeric so Harbor can consume it directly:

```json
{
  "reward": 0.73,
  "score": 0.73,
  "manifest_coverage": 0.89,
  "screenshot_size_match": 0.94,
  "dreamsim": 0.91,
  "vlm": 0.84,
  "visual_block": 0.62
}
```

The full reward profile requires:

- OpenAI VLM scoring (`OPENAI_API_KEY`)
- DreamSim ensemble
- visual block scoring
- rendered DOM/HTML metrics
- screenshot size matching and pixel-level metrics surfaced in the report

## Packaging Script

`scripts/package_synthetic_dataset.py` is the dataset packager. For each source
site it:

1. Validates that every enabled manifest capture has a frozen PNG.
2. Copies only neutral numbered screenshots into the public workspace.
3. Copies oracle source and manifest into hidden verifier files.
4. Writes task-level metric config using `full-vlm`.
5. Runs `harbor add --scan` so `dataset.toml` has digest-pinned task refs.

The package step never regenerates screenshots. If a PNG is missing, packaging
fails because that means the source dataset is incomplete.

## Current Readiness

Current state is ready for a one-VM Harbor run over the 12 generated synthetic
sites after:

```bash
bash scripts/setup_harbor_vm.sh
```

Scale-out work still left:

- Push the verifier image to a registry for multiple VMs.
- Decide runtime concurrency from actual CPU/RAM/model/API throughput.
- Add a small runbook for publishing the generated task set if we want a remote
  Harbor dataset rather than local `--path` execution.
