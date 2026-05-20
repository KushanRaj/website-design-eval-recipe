# Harbor / Modal Scale Handoff - 2026-05-20

## Current State

The repository now has the synthetic website replication dataset path, Harbor task packaging, reusable agent/verifier images, and a full evaluator reward path wired far enough to run real Harbor jobs.

The active branch on the Mac is:

```bash
codex/animation-vm-sync
```

As of the last safe EC2 check, there were no active `tmux` sessions on the EC2 host. The latest Modal-backed job pointer on EC2 was:

```text
ec2-harbor-modal-full-reward-12-20260520-120247
```

That job should be treated as stranded/incomplete, not as an active run.

## Important Files

- `scripts/package_harbor_task.py`
  - Generates Harbor task folders under `datasets/synthetic-website-replication/`.
  - Generates each task's verifier wrapper scripts.
  - Recent fix: `_test_sh()` must return a raw triple-quoted string. Without that, shell escaping in generated `tests/test.sh` is corrupted.

- `docs/harbor-packaging.md`
  - Records the Harbor layout, hidden verifier inputs, agent/verifier images, Modal registry secret issue, and EC2 controller pattern.

- `website_design_eval/evaluator.py`
  - Main evaluator runtime.
  - Candidate manifest planning uses Claude Code in evaluation, not only deterministic path matching.
  - Uses async Playwright for capture/replay.

- `website_design_eval/reward.py`
  - Builds the final reward object and Markdown report.
  - Current likely bug: Markdown report generation can crash on missing row fields after metrics complete.

- `website_design_eval/block_visual.py`
  - Visual block extraction/scoring.
  - Current bottleneck: block matching and per-block pixelmatch can be extremely slow on high-block-count captures.

## Harbor Task Contract

The agent should see only screenshots:

```text
/app/reference/screenshots/001.png
/app/reference/screenshots/002.png
...
```

The agent should not see:

- oracle HTML/CSS/JS
- `screenshot-manifest.json`
- capture IDs or labels
- generator concepts/specs
- evaluator implementation details

Hidden verifier inputs live under each task:

```text
tests/private/
  oracle-site/
  screenshot-manifest.json
  metric-config.json
```

The verifier receives the candidate site through Harbor artifacts from `/app`.

## Modal / GHCR Issue

There are two different secrets:

- `kushan-wde-api-keys`
  - Supplies `OPENAI_API_KEY` and `ANTHROPIC_API_KEY`.

- `ghcr-secret`
  - Supplies `REGISTRY_USERNAME` and `REGISTRY_PASSWORD` for private GHCR image pulls.

The repeated error:

```text
FROM ghcr.io/kushanraj/wde-agent-claude:e18579c
unable to retrieve auth token: invalid username/password: unauthorized
```

was not a verifier issue and not a general Modal failure. It happened because stock Harbor `0.7.1` calls `modal.Image.from_dockerfile(...)` for task Dockerfiles and does not pass `registry_secret` into the Dockerfile `FROM` pull.

The working patch is in Harbor's Modal adapter, not in this repo:

```text
~/.local/share/uv/tools/harbor/lib/python3.13/site-packages/harbor/environments/modal.py
```

Expected patched behavior:

1. Parse the first Dockerfile line.
2. Require `FROM <private-image>`.
3. Build the Modal image with:

```python
modal.Image.from_registry(base_image, secret=modal.Secret.from_name(registry_secret))
```

4. Apply remaining Dockerfile commands with `dockerfile_commands(...)`.

Check if a VM has the patch:

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

## EC2 Controller Pattern

The reason to run Harbor from EC2 is simple: if the laptop disconnects, the controller should keep running.

Known EC2 host:

```bash
ssh -i ~/.ssh/kushan-harbor.pem ec2-user@13.203.76.142
```

Use `tmux` for long runs. Do not run Harbor directly in an SSH foreground session.

The intended Modal-backed run shape:

```bash
export WDE_HARBOR_ENV=modal
export WDE_MODAL_ENVIRONMENT=kushan-wde-evals
export WDE_MODAL_SECRET_NAME=kushan-wde-api-keys
export WDE_MODAL_REGISTRY_SECRET_NAME=ghcr-secret
export WDE_HARBOR_AGENT_IMPORT_PATH=harbor_preinstalled_claude:PreinstalledClaudeCode
export WDE_HARBOR_MODEL=claude-opus-4-7
export WDE_HARBOR_N_CONCURRENT=12
scripts/run_harbor_full_reward.sh datasets/synthetic-website-replication --max-retries 1
```

## Fixed Packaging Bug

The generated verifier shell wrapper previously had broken quoting:

```bash
value="${value//"/\"}"
```

That caused verifier startup to fail before `run_eval.py` started. Harbor then reported:

```text
RewardFileNotFoundError
```

even though the candidate site had been generated.

The fix is in `scripts/package_harbor_task.py`:

```python
def _test_sh() -> str:
    return r"""
```

After regenerating packaged tasks, verify:

```bash
find datasets/synthetic-website-replication -path '*/tests/test.sh' -print0 |
  xargs -0 -n1 bash -n
```

## Reward Markdown Crash

This is the easiest current functional bug to explain.

The evaluator can finish real metric computation and emit `evaluator_end`, but then crash while generating the human-readable Markdown report:

```text
KeyError: 'component_denominator'
```

The relevant code path is:

```text
tests/run_eval.py
  -> website_design_eval.reward.build_reward_markdown(reward)
     -> row["component_denominator"]
```

Why this matters:

1. The metrics may already be computed.
2. `reward-details.json` may already be written.
3. The compact Harbor-facing `reward.json` is written after the Markdown report.
4. If Markdown rendering crashes first, Harbor never sees `reward.json`.
5. Harbor marks the verifier as failed even though the evaluator did useful work.

This is a report-generation bug, not necessarily a scoring bug.

Recommended fix:

1. Make `build_reward_markdown()` defensive:

```python
row.get("component_denominator", "")
```

and do the same for every non-essential row field.

2. In generated `tests/run_eval.py`, write the compact Harbor `reward.json` before optional Markdown report generation.

3. Wrap `build_reward_markdown()` in `try/except` so report formatting cannot nuke a valid reward.

The quickest unblock is to patch `scripts/package_harbor_task.py` so newly generated `run_eval.py` writes `reward.json` first and treats `reward-report.md` as best-effort. A future verifier image rebuild should also include the robust `website_design_eval/reward.py` fix.

## Visual Block Slowdown

If one capture's visual block score takes 300 seconds, the time is not coming from CLIP.

In the current full reward path, masked CLIP is disabled:

```python
include_masked_clip=False
```

The slow path is:

```text
website_design_eval/evaluator.py
  -> visual_block_score_from_blocks(...)
website_design_eval/block_visual.py
  -> _run_visual_block_analysis_from_blocks(...)
research/source-repos/.../visual_score.py
  -> find_possible_merge(...)
  -> repeated find_maximum_matching(...)
  -> scipy.optimize.linear_sum_assignment(...)
```

Why it gets slow:

- Each capture can have 100-200+ text/visual blocks.
- Matching builds a reference-by-candidate cost matrix.
- `find_possible_merge()` repeatedly tries adjacent block merges and reruns global matching.
- The global matcher uses Hungarian assignment via `linear_sum_assignment`.
- We also run block-level pixelmatch for matched block crops when `include_block_pixelmatch=True`.
- Async Playwright does not speed up CPU-bound block matching. It only lets other awaits progress.
- With 12 concurrent Harbor tasks, CPU contention can make one capture's visual-block section much slower than it is in isolation.

Concrete implication:

- A 300s visual-block capture is an algorithm/concurrency bottleneck, not a browser screenshot bottleneck and not an API call.

Recommended next optimizations:

1. Add a visual-block-specific semaphore, for example `WDE_VISUAL_BLOCK_CONCURRENCY=1` or `2`.
2. Add timing logs inside visual block:
   - extraction
   - merge/match
   - text/color/position scoring
   - block pixelmatch
3. Consider moving block pixelmatch out of the default reward or gating it separately.
4. Add a high-block-count fallback:
   - skip merge search above a threshold
   - or use a cheaper greedy text/geometry matcher
   - or cap repeated merge attempts.

## Candidate Manifest Planning

Important conceptual point for the next agent:

The candidate manifest/planner is intended to be intelligent. It should not blindly force the candidate to perform the exact oracle action.

Example:

- Oracle dropdown opens on hover.
- Candidate dropdown opens on click.
- The candidate should still receive state coverage if the desired visible state appears.

The planner should map intent/state, not action parity.

Correct behavior:

```json
{
  "state_resolved": true,
  "oracle_action": "hover",
  "resolved_action": "click",
  "interaction_parity": false
}
```

Reward should use the state resolution. Interaction parity can be diagnostic.

## Current Git Working Tree Notes

At handoff time, tracked local changes were:

```text
M docs/harbor-packaging.md
M scripts/package_harbor_task.py
```

This handoff doc should also be committed.

There are many untracked generated outputs and research repos. Do not blindly add them.

Examples:

```text
Generator/output/...
research/source-repos/...
modal-results/
harbor-tasks/
progress-logs/log4.txt
progress-logs/log5.txt
```

Treat those as local artifacts unless the user explicitly asks to version them.

## Recommended Immediate Next Steps

1. Patch reward output robustness:
   - generated `run_eval.py` writes Harbor `reward.json` before Markdown
   - Markdown report is best-effort
   - `build_reward_markdown()` uses `.get()` defaults

2. Regenerate packaged dataset:

```bash
python scripts/package_harbor_task.py
```

or use the repo's setup/package script if preferred.

3. Syntax-check generated verifier wrappers:

```bash
find datasets/synthetic-website-replication -path '*/tests/test.sh' -print0 |
  xargs -0 -n1 bash -n
```

4. Rebuild/push verifier image if the source package fix is meant to live inside `/opt/wde`.

5. Re-run one task first, then all 12.

6. If all 12 run but are too slow, throttle visual-block concurrency before changing reward semantics.

## What Not To Re-Debug

- Do not assume the agent sees oracle source. The packaged task is designed so the agent sees only screenshots.
- Do not assume the GHCR issue means Modal cannot pull any image. The specific issue was private agent image pulls through Dockerfile `FROM` without registry auth.
- Do not assume `RewardFileNotFoundError` means the agent failed. It can also mean the verifier crashed before writing compact `reward.json`.
- Do not blame CLIP for the current 300s visual block cases. Masked CLIP is disabled in the full path we inspected.
