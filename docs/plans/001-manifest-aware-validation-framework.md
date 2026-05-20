# Plan 001: Manifest-Aware Validation Framework

## Status Update - 2026-05-20

This plan has largely been implemented and partially superseded by later work.
Treat the body below as the original build plan, not the latest product surface.

Current deltas from this first plan:

- visual-block extraction from isolated Playwright manifest-state pages is now
  implemented rather than merely planned/unsupported
- static screenshot/capture evaluation now uses Python async Playwright with
  per-capture task-group execution; the experimental animation evaluator path
  still uses sync Playwright
- manifest inventory generation for oracle/candidate manifest planning still
  uses the shared sync Playwright `_browser_inventory` helper
- rendered `outerHTML` text/tree metrics are captured and reported
- reward curriculum V0 is defined in `docs/reward-curriculum-v0.md`
- pixelmatch is included as a later-pass precision signal in reward V0
- LLM-backed oracle manifest generation now exists
- generator manifest replay can prune failed optional interaction captures

The current overview is `docs/evaluation-progress-report.md`; the browser-state
substrate follow-up is `docs/plans/003-browser-state-scoring-substrate.md`.

## Summary

Build a new evaluator path where the evaluator receives the oracle code folder, oracle manifest, and candidate code folder, then generates the candidate capture plan itself.

The browser runtime becomes the source of truth: every screenshot, browser-rendered `outerHTML`, CSSOM snapshot, and visual-block extraction is produced from the manifest state using one Python Playwright runtime.

The immediate goal is not a final reward formula. The immediate goal is a functional evaluator that can print: captures replayed, artifacts produced, scores computed, and missing/unsupported states reported clearly.

Default report surface:

- manifest/state coverage
- validity/render guard
- screenshot-based scores: screenshot size match and DreamSim
- VLM-based scores, using the WebCode2M-style visual judge when `OPENAI_API_KEY` is available
- visual-block-based scores: visual block core, bbox geometry, and CSSOM/block-style comparison when live-state extraction is available

Do not add a separate HTML-metric bucket in this pass. Browser-rendered `outerHTML` is still captured because it is the right artifact for later React/Solid support, but it is infrastructure/debug data rather than a default scoring bucket.

SSIM/MSE/MAE, global CLIP, WebCoderBench, WebSee, WebCode2M bbox inventory, and pixelmatch/diff are not part of the default functional run. Pixelmatch/diff may be added later as an explicit scoring experiment, but not as failure-localization machinery.

## Key Changes

### Python Playwright Evaluator Runtime

- Add a Python Playwright evaluator runtime with one browser/session owner.
- Serve reference and candidate folders on separate local origins.
- Use separate browser contexts/pages for reference and candidate captures.
- Do not share storage, cookies, service workers, or page state between reference and candidate.
- Replay oracle/candidate capture states.
- Extract screenshot, browser-rendered `outerHTML`, and CSSOM from the same live page state.
- Run visual-block extraction from an isolated replay of the same state when the live-state extractor is implemented; until then, mark visual-block metrics unsupported without blocking the rest of the evaluator.
- Cache oracle artifacts once per capture and reuse them across candidates.

### Evaluator-Generated Candidate Capture Plan

- For each oracle capture, first map the same path/page in the candidate.
- Record route/page resolution separately from action resolution, including route confidence and a failure mode such as exact path missing, fallback path used, navigation failure, or rendered page mismatch.
- For each action, resolve the candidate target using exact selector first, then rendered-DOM element matching by role, tag, text, accessible name, input metadata, and geometry.
- After each resolved action, validate that the intended post-state happened. Resolver confidence alone is not enough.
- Post-state checks can include expected visible text, element visibility, role/state changes such as `aria-expanded`, scroll position, focused element, or a DOM/visual delta from the pre-action state.
- If a page, action target, or post-state cannot be resolved, mark that capture as missing/unsupported and include it in manifest coverage instead of silently producing bad metric scores.
- Write a generated `candidate-capture-plan.json` containing route resolution, resolved actions, resolver confidence, post-state confidence, coverage contribution, and missing-state reasons.

### Rendered-State Artifacts

- Capture `document.documentElement.outerHTML` after navigation/actions. For current static HTML pages this will usually be close to the source file; for future framework pages it captures the browser-rendered UI that source HTML does not contain.
- Use simple page-settling for V1: `page.goto(..., waitUntil=...)`, manifest `afterLoadWaitMs`, and per-action `settleMs`.
- Do not make DOM-stability detection a blocker for V1. If needed later, inspect the `~/browser-challenge` DOM-walker/CDP workflow for mutation-settling ideas.
- CSSOM extraction runs on the already-open page state.
- Raw source HTML may remain available for inspection, but scoring should prefer browser-state artifacts where practical.

### Visual-Block State Handling

- Visual-block extraction must replay the same path, viewport, screenshot mode, scroll, hover, click, and focus state as the normal capture.
- The extraction may inject temporary color/style mutations only inside its isolated page/context.
- The normal screenshot, `outerHTML`, and CSSOM artifacts must be captured before or outside those mutations.
- If the visual-block replay cannot reproduce the capture state, mark the visual-block score unsupported for that capture instead of returning a false zero.
- Do not let the visual-block live-state rewrite block the initial evaluator. V1 may produce screenshots, `outerHTML`, CSSOM, candidate plans, screenshot size match, DreamSim, and VLM while visual-block live extraction reports `unsupported`.

### Score Surface

- Screenshot-based: screenshot size match and DreamSim. Pixelmatch/diff are excluded unless explicitly enabled later as scoring experiments.
- VLM-based: WebCode2M-style visual judge outputs when the API key is available; skipped, not failed, when unavailable.
- Visual-block-based: visual block core, bbox geometry, and CSSOM/block-style comparison.
- No final aggregate reward is defined in this plan.

## Interfaces

Add CLI:

```bash
uv run website-design-eval evaluate \
  --reference-root test-site \
  --reference-manifest test-site/screenshot-manifest.json \
  --candidate-root reproductions/claude-attempt-01 \
  --output-dir metrics-results/latest
```

Generated outputs:

- `candidate-capture-plan.json`
- `artifacts/reference/<capture-id>.json`
- `artifacts/candidate/<capture-id>.json`
- `functional-report.md`
- `metrics.json`

Artifact shape per capture:

- capture id
- page
- route/page resolution result
- viewport
- actions
- screenshot path
- screenshot dimensions and screenshot size match against the reference capture
- browser-rendered `outerHTML`
- CSSOM snapshot
- visual blocks
- post-state validation results
- extraction errors
- missing/unsupported state reason, if any

Manifest coverage score:

- each enabled oracle capture is one unit
- page missing or screenshot failure = `0`
- route/page resolution contributes to the capture before action coverage
- no-action capture with matched page = `1`
- action capture = mean of action coverage contributions
- action coverage contribution = resolver confidence multiplied by post-state confidence
- total manifest score = mean over enabled oracle captures

## Test Plan

### Current Good Candidate

- All 9 oracle captures resolve.
- Route/page resolution records exact-path success for all 9 captures.
- All action captures pass post-state validation.
- Dropdown, scroll, and focus states produce non-missing artifacts.
- Visual-block state captures no longer return false zero from default-state rendering.

### Current Bad Candidate

- Missing dropdown state is reported as missing/unsupported in manifest coverage.
- Route/page failures, if any, are separated from action/post-state failures in `candidate-capture-plan.json`.
- Missing state is not scored as a visual-block failure.
- Coverage score is partial.

### Runtime And Caching

- Oracle artifacts are computed once per capture.
- Screenshot, browser-rendered `outerHTML`, and CSSOM come from the same page state.
- Visual-block extraction uses an isolated replay of the same state when available; otherwise visual-block metrics are marked unsupported and the evaluator still completes.
- No WebCode2M subprocess screenshot calls in the core path.

### Metric Surface

- The default report includes manifest/state coverage, validity/render guard, screenshot size match, DreamSim, VLM-based scores, and visual-block-based scores when available.
- The default report excludes SSIM/MSE/MAE/global CLIP/WebCoderBench/WebSee/WebCode2M bbox inventory.
- Browser-rendered `outerHTML` is present in artifacts, but there is no separate default HTML-metric bucket.
- The CLI prints a short functional status showing whether the run completed, how many captures were covered, and where artifacts/reports were written.

## Assumptions

- Candidate manifest is not trusted or required; the evaluator generates candidate capture states.
- V1 still targets static/local folders, but the runtime design uses browser-rendered DOM so React/Solid can be added later without changing metric semantics.
- VLM is included when `OPENAI_API_KEY` is available; otherwise it is marked skipped, not failed.
- Final reward aggregation is out of scope for this plan.
- WebCode2M code remains an algorithm source, not the orchestrator.
