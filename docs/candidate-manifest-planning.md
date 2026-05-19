# Candidate Manifest Planning

This is the current evaluation flow for Harbor full reward.

## Short Version

The coding agent does **not** generate a manifest. The coding agent only sees
numbered screenshots and writes a candidate website.

The verifier does generate a candidate-side capture manifest. It uses Claude
Code, inside the verifier/evaluator flow, after the candidate website exists.

## What Exists Before Evaluation

At dataset creation time we freeze:

- the oracle website files
- the oracle `screenshot-manifest.json`
- the public numbered screenshots shown to the coding agent

The oracle manifest is hidden from the coding agent. It lives under
`tests/private/screenshot-manifest.json` in a packaged Harbor task.

## What Happens During Evaluation

For the full Harbor reward profile, the evaluator calls the candidate manifest
planner before it captures screenshots or scores metrics.

Inputs to the planner:

- hidden oracle manifest, used as state/intent guidance
- candidate website root, served locally
- Playwright-rendered candidate inventory:
  - routes
  - visible text
  - controls
  - selector candidates
  - layout boxes

Output from the planner:

- `generated-candidate-manifest.json`

The generated manifest preserves oracle capture IDs, but maps each capture to
the candidate route and candidate action that should reach the same visible
state. This is where cases like these are handled:

- oracle path `/audio.html` maps to candidate path `/talks.html`
- oracle hover dropdown maps to candidate click dropdown
- oracle selector names do not need to exist in the candidate

The evaluator then replays the generated candidate manifest directly.

## Important Boundary

Manifest planning is not the final visual reward. The planner is only deciding:

- which candidate route corresponds to each oracle capture
- which candidate action should be attempted for that state

If the action executes but the resulting screenshot is wrong, the normal visual,
DOM, CSSOM, visual-block, VLM, and reward metrics should punish that. The
manifest planner should not be treated as proof that the visual state is
correct.

## Code Paths

Main planner:

- `website_design_eval/candidate_planner.py`

Evaluator wiring:

- `website_design_eval/evaluator.py`
- `EvaluateConfig.candidate_manifest_planner`
- `EvaluateConfig.candidate_manifest`

CLI:

```bash
uv run website-design-eval generate-candidate-manifest \
  --oracle-manifest tests/private/screenshot-manifest.json \
  --candidate-root /app/site \
  --output /logs/verifier/eval/generated-candidate-manifest.json \
  --model opus
```

Integrated evaluation path:

```bash
uv run website-design-eval evaluate \
  --reference-root tests/private/oracle-site \
  --reference-manifest tests/private/screenshot-manifest.json \
  --candidate-root /app/site \
  --candidate-manifest-planner claude-code \
  --output-dir /logs/verifier/eval
```

Harbor packaging writes this into `tests/private/metric-config.json` for
`full-vlm`:

```json
{
  "candidate_manifest_planner": "claude-code",
  "candidate_manifest_model": "opus",
  "candidate_manifest_claude_auth": "api"
}
```

## Required Environment

The verifier container needs:

- `OPENAI_API_KEY` for VLM scoring
- `ANTHROPIC_API_KEY` for Claude Code candidate manifest planning

`CLAUDE_CODE_OAUTH_TOKEN` is not enough for verifier-side API planning in the
current packaged flow.

## Do Not Confuse These

Do not say "the evaluator only uses deterministic route matching" for Harbor
full reward. Deterministic route/action matching remains a fallback/debug path
when no candidate manifest planner is configured.

For the full Harbor reward path, candidate capture planning is Claude
Code-backed.
