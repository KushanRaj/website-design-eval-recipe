# Plan 001: Manifest-Aware Validation Framework

## Summary

Build a new evaluator path where the evaluator receives the oracle code folder, oracle manifest, and candidate code folder, then generates the candidate capture plan itself.

The browser runtime becomes the source of truth: every screenshot, rendered DOM, CSSOM snapshot, and visual-block extraction is produced from the same manifest state using one Python Playwright runtime.

Default report surface is core only:

- manifest/state coverage
- validity/render guard
- DreamSim
- WebCode2M-style VLM
- visual block core
- bbox geometry
- CSSOM
- rendered-DOM text/tree

Pixelmatch/diff, SSIM/MSE/MAE, CLIP, WebCoderBench, WebSee, and WebCode2M bbox inventory move to debug/research profiles.

## Key Changes

### Python Playwright Evaluator Runtime

- Add a Python Playwright evaluator runtime with one browser/session owner.
- Serve reference and candidate folders.
- Replay oracle/candidate capture states.
- Extract screenshot, rendered DOM, CSSOM, and visual blocks from the same live page state.
- Cache oracle artifacts once per capture and reuse them across candidates.

### Evaluator-Generated Candidate Capture Plan

- For each oracle capture, first map the same path/page in the candidate.
- For each action, resolve the candidate target using exact selector first, then rendered-DOM element matching by role, tag, text, accessible name, input metadata, and geometry.
- If a page or action cannot be resolved, mark that capture as missing/unsupported and include it in manifest coverage instead of silently producing bad metric scores.
- Write a generated `candidate-capture-plan.json` containing resolved actions, confidence, and missing-state reasons.

### Rendered-State Artifacts

- Replace raw-HTML scoring with rendered-state artifacts where possible.
- HTML text/tree metrics use `document.documentElement.outerHTML` after navigation/actions.
- CSSOM extraction runs on the already-open page state.
- Visual-block extraction must inject color mutations into the live page state, not call WebCode2M `html2screenshot.py` on default raw HTML.

### Scoring Profiles

- `core`: manifest coverage, validity, DreamSim, VLM, visual block core, bbox geometry, CSSOM, rendered-DOM text/tree.
- `debug`: core plus gated pixelmatch/diff.
- `research`: all old/extra metrics.
- Pixelmatch/diff only run when `dreamsim_score >= 0.70` and, if VLM is enabled, `vlm_overall >= 0.70`.

## Interfaces

Add CLI:

```bash
uv run website-design-eval evaluate \
  --reference-root test-site \
  --reference-manifest test-site/screenshot-manifest.json \
  --candidate-root reproductions/claude-attempt-01 \
  --profile core \
  --output-dir metrics-results/latest
```

Generated outputs:

- `candidate-capture-plan.json`
- `artifacts/reference/<capture-id>.json`
- `artifacts/candidate/<capture-id>.json`
- `core-report.md`
- `core-metrics.json`

Artifact shape per capture:

- capture id
- page
- viewport
- actions
- screenshot path
- rendered DOM HTML
- CSSOM snapshot
- visual blocks
- extraction errors
- missing/unsupported state reason, if any

Manifest coverage score:

- each enabled oracle capture is one unit
- page missing or screenshot failure = `0`
- no-action capture with matched page = `1`
- action capture = average resolved-action confidence
- total manifest score = mean over enabled oracle captures

## Test Plan

### Current Good Candidate

- All 9 oracle captures resolve.
- Dropdown, scroll, and focus states produce non-missing artifacts.
- Visual-block state captures no longer return false zero from default-state rendering.

### Current Bad Candidate

- Missing dropdown state is reported as missing/unsupported in manifest coverage.
- Missing state is not scored as a visual-block failure.
- Coverage score is partial.

### Runtime And Caching

- Oracle artifacts are computed once per capture.
- CSSOM and rendered DOM come from the same page state as the screenshot.
- No WebCode2M subprocess screenshot calls in the core path.

### Metric Surface

- `core` report excludes SSIM/MSE/MAE/global CLIP/WebCoderBench/WebSee/bbox inventory.
- `debug` runs pixelmatch/diff only after DreamSim/VLM gates pass.
- Rendered-DOM text/tree metrics match current raw-HTML metrics on static pages within expected tolerance.

## Assumptions

- Candidate manifest is not trusted or required; the evaluator generates candidate capture states.
- V1 still targets static/local folders, but the runtime design uses browser-rendered DOM so React/Solid can be added later without changing metric semantics.
- VLM is part of the core report when `OPENAI_API_KEY` is available; otherwise it is marked skipped, not failed.
- DreamSim threshold for bringing in pixel/diff debug metrics is `0.70`.
- WebCode2M code remains an algorithm source, not the orchestrator.
