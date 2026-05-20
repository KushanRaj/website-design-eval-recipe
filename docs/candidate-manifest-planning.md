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
- reference-side animation evidence from the hidden oracle site, used to expose
  the rendered target/trigger element shape, text, class, and bounding box
- candidate website root, served locally
- Playwright-rendered candidate inventory:
  - routes
  - visible text
  - controls
  - selector candidates
  - layout boxes

Output from the planner:

- `generated-candidate-manifest.json`
- `generated-candidate-manifest.prompt.txt`
- `generated-candidate-manifest.claude-transcript.jsonl`

The generated manifest preserves oracle capture IDs, but maps each capture to
the candidate route and candidate action that should reach the same visible
state. It also preserves oracle animation IDs while mapping animation routes,
triggers, and target selectors onto the candidate implementation. This is where
cases like these are handled:

- oracle path `/audio.html` maps to candidate path `/talks.html`
- oracle hover dropdown maps to candidate click dropdown
- oracle selector names do not need to exist in the candidate
- oracle animation target is a large card while the candidate has both a
  clickable map marker and a clickable card with similar text

The evaluator then replays the generated candidate manifest directly.

## Runtime Implementation Notes

There are two separate browser uses in this flow:

- **Manifest planning inventory:** `generate-manifest` and
  `generate-candidate-manifest` call the shared `_browser_inventory` helper in
  `website_design_eval/manifest_generator.py`. That helper currently uses
  Python sync Playwright to serve the site, visit routes, and extract visible
  text, controls, selector candidates, and layout boxes. The surrounding Claude
  Code SDK call is async, but the inventory collection itself is not.
- **Evaluator replay/capture:** after the candidate manifest exists, the main
  evaluator capture path uses Python async Playwright. It replays the reference
  and candidate states, captures screenshots, rendered `outerHTML`, CSSOM, and
  isolated visual-block artifacts from the async browser path.

The older deterministic fallback route/action resolver is still present for
debugging or runs without `candidate_manifest_planner`, but Harbor `full-vlm`
uses Claude Code-backed candidate manifest planning.

Candidate planning currently gives Claude Code up to `16` turns. If planning
fails, inspect `generated-candidate-manifest.prompt.txt` for the exact prompt
and `generated-candidate-manifest.claude-transcript.jsonl` for the SDK messages,
assistant text, result errors, and structured-output status captured before the
failure.

## Important Boundary

Manifest planning is not the final visual reward. The planner is only deciding:

- which candidate route corresponds to each oracle capture
- which candidate action should be attempted for that state
- which candidate route, trigger, and target element correspond to each oracle
  animation

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

Also do not say "all Playwright usage is async." The current precise statement
is: evaluator screenshot/capture replay is async Playwright; manifest inventory
generation and the experimental animation evaluator path still use sync
Playwright.
