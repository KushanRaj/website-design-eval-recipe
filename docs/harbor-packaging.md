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
- `agent-image/` builds one reusable Claude Code image shared by every task.
- `verifier-image/` builds one reusable evaluator image shared by every task.

## One-VM Setup

From a clean VM with this repo cloned, Docker running, Harbor installed, and
`.env` containing `OPENAI_API_KEY` and `ANTHROPIC_API_KEY`:

```bash
bash scripts/setup_harbor_vm.sh
scripts/run_harbor_full_reward.sh
```

`setup_harbor_vm.sh` does three things:

1. Builds `website-design-eval-agent-claude:latest` with Claude Code already
   installed.
2. Builds `website-design-eval-verifier:latest`.
3. Packages all generated sites under `Generator/output/harbor-dataset/` into
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
WDE_HARBOR_AGENT_IMPORT_PATH=harbor_preinstalled_claude:PreinstalledClaudeCode
WDE_HARBOR_MODEL=claude-opus-4-7
WDE_HARBOR_N_CONCURRENT=4
```

When scaling on Modal, use the preinstalled import path. Harbor's built-in
`claude-code` agent always runs its installer during setup, and we observed that
installer being killed with exit `137` under concurrent runs. The
preinstalled wrapper keeps the normal Claude execution path but changes setup to
`claude --version` only.

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

Task-level diversity requirements are exposed through `task.toml` metadata and
the instruction text. Current fields include:

- `has_animations`: whether the oracle manifest has enabled animation captures.
- `animation_count`: enabled animation capture count.
- `candidate_framework`: requested candidate implementation target. It defaults
  to `html`, but packaging can set `react` or `solid` even when the hidden
  oracle site itself is static HTML.

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

The hidden `screenshot-manifest.json` remains the verifier source of truth for
static captures and animation captures. Candidate-side manifest planning maps
both static capture states and animation route/trigger/target selectors onto
the submitted site before scoring.

The verifier runs in a separate environment. Harbor copies `/app` from the
agent container to the verifier container through `artifacts = ["/app"]`, so
the verifier receives the candidate site but the agent never receives hidden
oracle files.

Packaging must syntax-check the generated verifier wrapper before a dataset is
run. A broken `tests/test.sh` prevents `run_eval.py` from starting, so the
verifier exits without writing `reward.json` and Harbor reports
`RewardFileNotFoundError` even though agent generation succeeded:

```bash
find datasets/synthetic-website-replication -path '*/tests/test.sh' -print0 |
  xargs -0 -n1 bash -n
```

## Reusable Agent Image

There is one agent image for all tasks, not one agent image per task.

`agent-image/build.sh` creates `website-design-eval-agent-claude:latest` and
installs Claude Code at image-build time. Task `environment/Dockerfile` files
then inherit from this image and only copy the public screenshot workspace:

```dockerfile
FROM website-design-eval-agent-claude:latest

WORKDIR /app
COPY workspace/ /app/

RUN mkdir -p /app/site
```

At runtime, use:

```bash
WDE_HARBOR_AGENT_IMPORT_PATH=harbor_preinstalled_claude:PreinstalledClaudeCode
```

That wrapper fails loudly if `claude` is missing. It does not fall back to a
runtime install, because runtime installs are the scaling failure mode.

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
  --agent-base-image website-design-eval-agent-claude:latest \
  --verifier-base-image website-design-eval-verifier:latest \
  --metric-profile full-vlm \
  --verifier-allow-internet \
  --force
```

For Modal or a remote VM pool, push both the agent and verifier images to a
registry and pass those registry tags as `--agent-base-image` and
`--verifier-base-image`. For the current one-VM path, local Docker images are
enough.

The main screenshot/capture evaluator inside the verifier uses Python async
Playwright and evaluates captures through an `asyncio.TaskGroup`. Tune local
capture/API concurrency with:

```bash
WDE_CAPTURE_CONCURRENCY=4
WDE_VLM_CONCURRENCY=4
```

`WDE_CAPTURE_CONCURRENCY` limits concurrent browser capture jobs within one
verifier process. `WDE_VLM_CONCURRENCY` limits concurrent VLM judge calls within
that same process. DreamSim is still serialized inside a verifier process to
avoid loading/forwarding the heavy model concurrently by accident.

## Modal Scale Path

The Modal path uses one dataset plus two registry images:

```text
ghcr.io/kushanraj/wde-agent-claude:latest
ghcr.io/kushanraj/wde-verifier:latest
```

Build and optionally push both images:

```bash
WDE_IMAGE_NAMESPACE=ghcr.io/kushanraj \
WDE_DOCKER_PLATFORM=linux/amd64 \
WDE_PUSH_IMAGE=1 \
bash scripts/build_harbor_images.sh
```

Package tasks against those image tags:

```bash
python scripts/package_synthetic_dataset.py \
  --source-root Generator/output/harbor-dataset \
  --dataset-dir datasets/synthetic-website-replication \
  --dataset-name proximal/synthetic-website-replication \
  --agent-base-image ghcr.io/kushanraj/wde-agent-claude:latest \
  --verifier-base-image ghcr.io/kushanraj/wde-verifier:latest \
  --metric-profile full-vlm \
  --verifier-allow-internet \
  --force
```

Run on Modal using the preinstalled agent and the Modal secret:

```bash
WDE_HARBOR_ENV=modal \
WDE_MODAL_ENVIRONMENT=kushan-wde-evals \
WDE_MODAL_SECRET_NAME=kushan-wde-api-keys \
WDE_MODAL_REGISTRY_SECRET_NAME=ghcr-secret \
WDE_HARBOR_AGENT_IMPORT_PATH=harbor_preinstalled_claude:PreinstalledClaudeCode \
WDE_HARBOR_MODEL=claude-opus-4-7 \
WDE_HARBOR_N_CONCURRENT=2 \
scripts/run_harbor_full_reward.sh datasets/synthetic-website-replication
```

### Resource Overrides

Packaged tasks declare conservative default resources:

```toml
[environment]
cpus = 2
memory_mb = 8192

[verifier.environment]
cpus = 2
memory_mb = 8192
```

Those defaults are intentionally portable, but they are too small for stress
testing the full verifier. Visual-block extraction and matching are especially
sensitive to CPU contention because they drive Playwright screenshots,
temporary recolored renders, image diffing, block recovery, and block matching.

On a large EC2 instance, do not assume Docker is using the whole machine just
because the host has many cores. Harbor still follows the task resource config
unless overridden. In the observed scale runs, the EC2 host had `32` vCPUs and
`123 GiB` RAM, but the verifier containers were still configured as `2` CPU /
`8 GiB` tasks until we explicitly overrode them.

For experimental throughput runs, use larger resource overrides:

```bash
export WDE_HARBOR_OVERRIDE_CPUS=8
export WDE_HARBOR_OVERRIDE_MEMORY_MB=32768
export WDE_CAPTURE_CONCURRENCY=4
```

Harbor prints warnings such as:

```text
Overriding CPU count to 8 alters the task from its intended configuration.
Overriding memory to 32768 MB alters the task from its intended configuration.
```

That warning means the run is no longer using the resource contract declared in
`task.toml`; it is a benchmark reproducibility warning, not an execution error.
For our private scaling experiments, this is expected. For a public benchmark
submission, either use the declared task resources or update the task resource
contract itself and regenerate the dataset.

Recommended current experiment settings:

```bash
# EC2-local control run on a large host
export WDE_HARBOR_N_CONCURRENT=8
export WDE_HARBOR_OVERRIDE_CPUS=8
export WDE_HARBOR_OVERRIDE_MEMORY_MB=32768
export WDE_CAPTURE_CONCURRENCY=4

# Modal-backed run
export WDE_HARBOR_N_CONCURRENT=14
export WDE_HARBOR_OVERRIDE_CPUS=8
export WDE_HARBOR_OVERRIDE_MEMORY_MB=32768
export WDE_CAPTURE_CONCURRENCY=4
```

If visual-block timings are still unstable, reduce `WDE_CAPTURE_CONCURRENCY` to
`1` or `2` before reducing task concurrency. That isolates whether the slowdown
is intra-verifier contention or cross-task contention.

### Modal + Private GHCR Images

The Modal run needs two independent secret paths:

- `WDE_MODAL_SECRET_NAME=kushan-wde-api-keys` injects API keys into the Modal
  sandbox.
- `WDE_MODAL_REGISTRY_SECRET_NAME=ghcr-secret` authenticates Modal image pulls
  from private GHCR packages.

The registry secret must exist in the same Modal environment used by the run:

```bash
modal secret create ghcr-secret \
  --env kushan-wde-evals \
  REGISTRY_USERNAME=... \
  REGISTRY_PASSWORD=...
```

Important Harbor implementation detail: stock Harbor `0.7.1` does not pass
`registry_secret` into `modal.Image.from_dockerfile(...)`. For task environment
Dockerfiles like:

```dockerfile
FROM ghcr.io/kushanraj/wde-agent-claude:e18579c
```

that means Modal's build worker tries to pull the private base image
anonymously and fails with:

```text
unable to retrieve auth token: invalid username/password: unauthorized
```

This is not a general GHCR outage, and it is not a verifier/runtime failure. In
the observed EC2 failure, the verifier image path was fine, but every agent
environment build failed while pulling
`ghcr.io/kushanraj/wde-agent-claude:e18579c`.

Until Harbor ships an upstream fix, the working adapter behavior is:

1. If `registry_secret` is set and the task uses a Dockerfile, read the first
   non-comment Dockerfile line.
2. Require it to be `FROM ...`.
3. Build the Modal image from that base with
   `modal.Image.from_registry(base_image, secret=Secret.from_name(registry_secret))`.
4. Apply the remaining Dockerfile commands with `dockerfile_commands(...)`.

Check whether a VM has the patched behavior:

```bash
~/.local/share/uv/tools/harbor/bin/python - <<'PY'
import harbor
from pathlib import Path

modal_file = Path(harbor.__file__).parent / "environments" / "modal.py"
text = modal_file.read_text()
print(modal_file)
print("patched_private_from =", "Image.from_registry(" in text and "dockerfile_commands(" in text)
PY
```

If the VM is unpatched, a fresh `harbor==0.7.1` install will still call
`Image.from_dockerfile(...)` directly and private agent image pulls will fail
even when `ghcr-secret` exists.

### EC2 Controller Pattern

For long runs, run Harbor from an EC2 `tmux` session as the controller and use
Modal as the execution backend. That way the laptop can disconnect without
killing the job.

```bash
cd ~/website-design-eval-recipe

tmux kill-session -t wde-harbor 2>/dev/null || true

cat > /tmp/run_wde_harbor.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

cd ~/website-design-eval-recipe

job="ec2-harbor-modal-full-reward-12-$(date +%Y%m%d-%H%M%S)"
echo "$job" > /tmp/wde_latest_ec2_harbor_job
mkdir -p "jobs/harbor-full-reward/$job"

set -a
source .env
set +a

export WDE_HARBOR_ENV=modal
export WDE_MODAL_ENVIRONMENT=kushan-wde-evals
export WDE_MODAL_SECRET_NAME=kushan-wde-api-keys
export WDE_MODAL_REGISTRY_SECRET_NAME=ghcr-secret
export WDE_HARBOR_AGENT_IMPORT_PATH=harbor_preinstalled_claude:PreinstalledClaudeCode
export WDE_HARBOR_MODEL=claude-opus-4-7
export WDE_HARBOR_N_CONCURRENT=12
export WDE_HARBOR_JOB_NAME="$job"
export WDE_HARBOR_JOBS_DIR=jobs/harbor-full-reward
export WDE_HARBOR_TIMEOUT_MULTIPLIER=4.0
export WDE_HARBOR_AGENT_TIMEOUT_MULTIPLIER=4.0
export WDE_HARBOR_VERIFIER_TIMEOUT_MULTIPLIER=4.0
export WDE_HARBOR_ENVIRONMENT_BUILD_TIMEOUT_MULTIPLIER=4.0

start=$(date +%s)
echo "[ec2-run] job=$job n_concurrent=12 started_at=$(date -Iseconds)" | tee "jobs/harbor-full-reward/$job/controller-ec2.log"

scripts/run_harbor_full_reward.sh datasets/synthetic-website-replication --max-retries 1 2>&1 | tee -a "jobs/harbor-full-reward/$job/controller-ec2.log"

code=${PIPESTATUS[0]}
end=$(date +%s)
echo "[ec2-run] job=$job exit_code=$code elapsed_seconds=$((end-start)) finished_at=$(date -Iseconds)" | tee -a "jobs/harbor-full-reward/$job/controller-ec2.log"
exit "$code"
EOF

chmod +x /tmp/run_wde_harbor.sh
tmux new-session -d -s wde-harbor /tmp/run_wde_harbor.sh
```

Monitor it from another machine:

```bash
ssh -i ~/.ssh/kushan-harbor.pem ec2-user@13.203.76.142 \
  'tmux capture-pane -pt wde-harbor:0.0 -S -160'

ssh -i ~/.ssh/kushan-harbor.pem ec2-user@13.203.76.142 \
  'cd ~/website-design-eval-recipe && job=$(cat /tmp/wde_latest_ec2_harbor_job) && tail -120 "jobs/harbor-full-reward/$job/controller-ec2.log"'
```

Increase `WDE_HARBOR_N_CONCURRENT` after the first stable full run. The Modal
secret supplies `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` to both the agent and
separate verifier sandboxes through Harbor's Modal environment kwargs.

For resource-heavy runs, prefer naming the tmux sessions and job directories
after the resource profile, for example:

```text
wde_local_bigres_14
wde_modal_bigres_14
ec2-local-harbor-matchonly-bigres-14-YYYYMMDD-HHMMSS
ec2-modal-harbor-matchonly-bigres-14-YYYYMMDD-HHMMSS
```

This makes it possible to compare default-resource runs against big-resource
runs without guessing which artifact directory used which resource contract.

## Modal-Owned Run

The local Harbor command is useful for development, but the disconnect-safe path
is to run the Harbor controller itself inside Modal:

```bash
MODAL_ENVIRONMENT=kushan-wde-evals \
python -m modal run -d scripts/modal_harbor_runner.py::submit \
  --job-name modal-harbor-full-reward-YYYYMMDD-HHMMSS \
  --n-concurrent 12 \
  --max-retries 2
```

This submits `scripts/modal_harbor_runner.py::run_harbor` as a detached Modal
function. The laptop is then only the submitter; Harbor's controller logs and job
directory are written into the `wde-harbor-results` Modal Volume under:

```text
/runs/jobs/harbor-full-reward/<job-name>/
```

Fetch results later with:

```bash
MODAL_ENVIRONMENT=kushan-wde-evals \
python -m modal volume get wde-harbor-results \
  /jobs/harbor-full-reward/<job-name> \
  ./modal-results/<job-name>
```

The runner still asks Harbor to execute agent and verifier sandboxes on Modal.
The benefit is that the Harbor controller, job state, and artifact collection no
longer depend on the laptop staying online.

## Reward Contract

The verifier writes:

```text
/logs/verifier/reward.json
/logs/verifier/reward-details.json
/logs/verifier/metrics.json
/logs/verifier/reward-report.md
/logs/verifier/functional-report.md
/logs/verifier/candidate-capture-plan.json
/logs/verifier/test-stdout.txt
/logs/verifier/test-stderr.txt
/logs/verifier/verifier-progress.jsonl
/logs/verifier/evaluator-progress.jsonl
```

The progress logs are intentionally explicit. `verifier-progress.jsonl` marks
the verifier wrapper boundary:

```text
verifier_entry
evaluator_process_start
evaluator_process_end
```

`evaluator-progress.jsonl` marks evaluator phases and per-capture metrics:

```text
evaluator_start
candidate_manifest_generation_start/end
captures_batch_start/end
capture_start/end
reference_capture_start/end
candidate_capture_start/end
vlm_judge_start/end
dreamsim_start/end
visual_block_start/end
bbox_geometry_start/end
cssom_block_style_start/end
evaluator_end
```

If `verifier_entry` is absent, the verifier container never reached `test.sh`.
If `verifier_entry` exists but `evaluator_process_start` is absent, the wrapper
failed before invoking the evaluator. If `vlm_judge_start` exists without
`vlm_judge_end`, the VLM call for that capture is the live blocker.

When Claude Code candidate manifest planning is enabled, the evaluator also
writes these files under `/logs/verifier/eval/`:

```text
generated-candidate-manifest.prompt.txt
generated-candidate-manifest.claude-transcript.jsonl
```

The prompt file records the exact oracle/candidate planning prompt. The JSONL
transcript records Claude SDK messages and errors, which is the first place to
look if planning fails with a turn-limit error or returns an incomplete
structured output.

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
- Claude Code candidate capture planning (`ANTHROPIC_API_KEY`)
- DreamSim ensemble
- visual block scoring
- rendered DOM/HTML metrics
- screenshot size matching and pixel-level metrics surfaced in the report

## Candidate Capture Planning

For the dedicated evaluator-side contract, see
`docs/candidate-manifest-planning.md`.

The oracle manifest is frozen at dataset creation time. During evaluation, the
full reward profile now generates a candidate-side capture manifest with Claude
Code before screenshots and metrics run.

The planner receives:

- the hidden oracle manifest as state/intent guidance
- a Playwright-rendered inventory of the candidate routes, visible text,
  controls, selectors, and layout boxes

It outputs `generated-candidate-manifest.json` under the evaluator output
directory. The evaluator then replays those candidate routes/actions directly.
This is the layer that maps cases such as an oracle hover dropdown to a
candidate click dropdown, or `/audio.html` to `/talks.html`, without exposing
the oracle manifest to the coding agent.

Implementation detail: the planner inventory currently uses the shared
`_browser_inventory` helper, which is Python sync Playwright. That is separate
from evaluator replay/capture, which is Python async Playwright. The generator's
frozen reference screenshot replay is also separate: it uses
`scripts/capture-screenshots.mjs`, not the Python evaluator runtime.

`tests/private/metric-config.json` controls this with:

```json
{
  "candidate_manifest_planner": "claude-code",
  "candidate_manifest_model": "opus",
  "candidate_manifest_claude_auth": "api"
}
```

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

## Manifest Replay And Pruning

The generator is responsible for producing a replayed, internally consistent
source site before Harbor packaging starts.

Current generator behavior:

- generate the oracle manifest after verifier approval
- replay the manifest with `scripts/capture-screenshots.mjs --prune-failed`
- keep required no-action page captures strict
- drop failed optional interaction captures from the manifest
- write `_replay-report.json` under `site/screenshots/reference/`

This means Harbor packaging treats the post-pruning manifest as canonical. If a
flaky optional click/hover state fails replay, it should not remain in the
manifest and then become a hidden Harbor mismatch. Broad visual design coverage
is the goal; unreliable functional controls should be removed from the oracle
capture contract unless they are essential to the task.

The builder validation step also ignores managed `site/screenshots/` outputs.
Those files are created by the generator replay process, not by the builder, and
should not cause repair attempts to fail path/type validation.

## Current Readiness

Current state is ready for a one-VM Harbor run over the 12 generated synthetic
sites after:

```bash
bash scripts/setup_harbor_vm.sh
```

Scale-out checklist:

- Push the agent and verifier images to a registry Modal can pull.
- Package the dataset against those registry image tags.
- Run with `WDE_HARBOR_AGENT_IMPORT_PATH` so Claude Code is not reinstalled per
  trial.
- Decide runtime concurrency from actual CPU/RAM/model/API throughput.
- Add a small runbook for publishing the generated task set if we want a remote
  Harbor dataset rather than local `--path` execution.
