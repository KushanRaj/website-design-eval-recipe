# Plan 003: Browser-State Scoring Substrate

## Status Update - 2026-05-20

The main substrate shift has been implemented in the manifest-aware evaluator:

- rendered HTML text/tree metrics read `outerHTML` from the Playwright capture
  artifacts
- CSSOM is captured from the manifest-replayed page state
- visual blocks are extracted from isolated Playwright pages that replay the same
  manifest state before doing text-color mutation
- candidate routes can use semantic route inventory fallback when exact paths
  differ
- evaluator-added node stamps are removed before clean artifact capture

Remaining work is mostly calibration and robustness: stronger intent/postcondition
schemas, better action resolution, more generated-site runs, and batch/runtime
optimization.

## Summary

The evaluator should treat the Playwright-rendered page state as the ground truth for scoring.

Raw source files are only inputs used to serve the site. They are not the scoring substrate. For static HTML, React, Solid, or any future framework, the core question is the same: what did the browser render after loading the route, setting the viewport, replaying the manifest state, and waiting for the page to settle?

The intended source of truth for every capture is:

```text
Playwright page after:
  route loaded
  viewport set
  manifest action or intent replayed
  page settled
```

From that state, the evaluator derives:

- screenshot
- rendered `outerHTML`
- visible text / rendered DOM tree
- CSSOM snapshot
- layout boxes
- visual-block extraction
- DreamSim / VLM screenshot inputs
- HTML text/tree metrics such as BLEU, ROUGE, and tree F1

## Current Understanding

The HTML metrics should not read raw source files. They should run from browser-rendered state:

```text
Playwright page
  -> document.documentElement.outerHTML
  -> WebCode2M text BLEU / ROUGE
  -> WebCode2M DOM/tree BLEU / ROUGE / F1
```

This is acceptable even though the text/tree algorithms use BeautifulSoup internally, because BeautifulSoup is only parsing the HTML string fetched from Playwright. It is not deciding what the page state is.

The visual-block metrics are different. They cannot be solved by `outerHTML` alone because visual block depends on browser rendering, layout, colors, text boxes, and screenshots. Visual block must run in an isolated Playwright page where the same capture state is replayed.

## Non-Negotiable Rule

If a metric is part of the core report, it must consume artifacts derived from the Playwright-rendered manifest state.

Do not do this in core scoring:

```text
raw HTML file path
  -> independent default render
  -> score
```

Do this instead:

```text
manifest capture state in Playwright
  -> artifact
  -> score
```

## Intended Capture Flow

For each oracle capture:

```text
1. Start reference page in Playwright.
2. Navigate to the capture route.
3. Set viewport and screenshot mode.
4. Replay the manifest state: hover, click, focus, fill, scroll, or intent.
5. Wait for page settle.
6. Capture reference artifacts.

7. Start candidate page in Playwright.
8. Resolve the candidate route.
9. Resolve candidate action targets from rendered DOM / accessibility state.
10. Replay the intended state.
11. Wait for page settle.
12. Capture candidate artifacts.

13. Score reference artifacts against candidate artifacts.
```

The candidate resolver should prefer browser state over source code. TypeScript, React, Solid, build output, and component structure are implementation details. The browser-rendered DOM and accessibility state are what the user sees and interacts with.

## Artifact Contract

Each capture artifact should include:

- capture id
- route/page
- viewport
- screenshot path and dimensions
- rendered `outerHTML` from `document.documentElement.outerHTML`
- visible text snapshot
- rendered DOM/control snapshot
- CSSOM snapshot
- action replay metadata
- postcondition checks
- missing/unsupported reason, if any

Raw file paths may be retained for debugging and serving, but core scorers should not use them as their primary input.

## HTML Text/Tree Metrics

The evaluator should compute these from rendered `outerHTML`:

- text BLEU-1
- text ROUGE-1 recall
- DOM/tree BLEU
- DOM/tree ROUGE
- DOM/tree F1

This is the correct substrate:

```text
reference_artifact.outer_html
candidate_artifact.outer_html
```

Not:

```text
reference_route.file_path
candidate_route.file_path
```

Expected behavior:

- On current static pages, rendered-HTML metrics may match raw-file metrics exactly.
- On React/Solid/dynamic pages, rendered-HTML metrics may intentionally differ from raw source metrics.
- The report should label these as rendered HTML metrics, not raw HTML metrics.

## CSSOM Metrics

CSSOM metrics should consume the CSSOM snapshots captured from the same manifest state as the screenshot.

Current problem:

```text
cssom_block_style_score(reference_route.file_path, candidate_route.file_path, ...)
```

That reopens raw/default HTML and can lose hover, focus, scroll, or dynamic framework state.

Required direction:

```text
cssom_block_style_score(reference_artifact.cssom_snapshot, candidate_artifact.cssom_snapshot, matched_blocks, ...)
```

or equivalent.

The metric may still reuse the existing CSS comparison logic, but the rendered state should come from the centralized Playwright capture, not a second default render from files.

The CSSOM snapshot contract must be explicit because block-style scoring resolves visual blocks back to rendered DOM elements. Each element record should include:

- `bbox_px`: document-space pixel box, normalized against full-page screenshot coordinates when the screenshot is full-page.
- `bbox`: normalized `[x, y, width, height]` in the same coordinate space as visual-block boxes.
- viewport width, height, and device pixel ratio.
- document width and height.
- screenshot width and height.
- scroll offset at capture time.
- a clear coordinate note: whether boxes are viewport-relative or document/full-page-relative.

For the current full-page screenshot flow, prefer document/full-page coordinates so visual blocks, screenshots, and CSSOM element boxes are comparable without guessing.

## Visual Block Metrics

Visual block must run in isolation because it mutates page text colors to recover block boxes.

Current problem:

```text
manifest-state screenshot
raw/default HTML file -> visual-block recolor/render -> blocks
```

This creates false failures for states such as dropdowns and hover captures. The screenshot is from the manifest state, but the extracted blocks are from the default page state.

Required direction:

```text
isolated Playwright page
  -> navigate to same route
  -> set same viewport
  -> replay same manifest action/intent state
  -> inject visual-block color mutation
  -> screenshot mutated page
  -> extract blocks
```

Run this separately for reference and candidate, then compare blocks.

Important constraints:

- Do not mutate the normal artifact page.
- Do not call the old WebCode2M `html2screenshot.py` path in the core evaluator.
- Do not pass raw route file paths into visual-block core scoring.
- If the isolated replay cannot reproduce the capture state, mark visual block unsupported for that capture instead of returning a false zero.
- Do not depend on transient resolver-stamp selectors such as `[data-wde-node-id="wde-49"]` during isolated replay.
- In V1, re-run target resolution inside each isolated replay page instead of trying to persist page-local stamped selectors.

The visual-block refactor should preserve upstream scoring fidelity. The goal is not to invent a new visual-block score. The goal is to replace only the browser IO layer:

```text
old:
  HTML file -> WebCode2M html2screenshot.py -> recolored renders -> block lists

new:
  isolated Playwright manifest-state page -> recolored renders -> block lists
```

After block extraction, feed the resulting block lists into the existing WebCode2M/Design2Code merge, match, and scoring logic wherever possible. Add parity tests on static/default captures so that unchanged full-page captures still match the previous visual-block scores.

The implementation should be staged. First prove that the browser-state extractor can reproduce the legacy metric on static/default captures. Only after that should it become the source for action-state captures such as dropdowns and hovers.

Stage 1 acceptance:

- `home.desktop.full` and at least one non-home full-page capture are compared against the current visual-block adapter.
- If scores or block counts differ, the difference must be explained and documented rather than silently treated as parity. Expected causes include the browser-state path loading CSS/assets and respecting real visibility/display state where the legacy `html2screenshot.py` default render did not.
- The extracted block counts and matched-pair counts match or have an explained, documented difference.
- CSSOM block-style score remains unchanged for these static/default captures because it receives the same visual-block pairs.

Stage 2 acceptance:

- `home.desktop.work-dropdown` no longer returns a false zero caused by default-state rendering.
- The visual-block result records `artifact_source: isolated_playwright_manifest_state`.
- If isolated replay fails, the metric is marked unsupported with a reason rather than scored as zero.

## Candidate Action Resolution And Intents

The manifest may contain selectors, but candidate code may use different selectors. The evaluator therefore needs a candidate resolver.

Resolution order:

1. Try exact selector.
2. Use rendered DOM / accessibility state: role, tag, visible text, accessible name, labels, input metadata, and geometry.
3. Use intent metadata when present.
4. Optionally use an LLM-assisted resolver later.
5. Verify postconditions after the action.

Example manifest intent:

```json
{
  "id": "home.desktop.work-dropdown",
  "intent": "Reveal the Work dropdown in the desktop nav",
  "action": {
    "type": "hover",
    "target": {
      "role": "button",
      "text": "Work",
      "region": "desktop navigation"
    }
  },
  "postcondition": {
    "visible_text": [
      "With governments",
      "With enterprises",
      "With schools"
    ]
  }
}
```

Control matching should not give full confidence just because two inputs share the same type. For example, any random `type="email"` input should not pass an email-focus capture. Type is one feature; it is not identity.

When isolated replays are needed, the resolver should run again inside that isolated page. Persisting a transient stamped selector from the first page is not a stable replay strategy. The capture plan may record the original resolver evidence and confidence, but the isolated page should resolve the action target against its own rendered DOM.

If intent and postcondition fields become first-class manifest fields, update the manifest schema before relying on them. The current manifest model is strict, so intent rollout should include an explicit schema migration rather than ad hoc extra fields.

## What We Defer

Element-local scoring can come later.

Once both reference and candidate action targets are resolved, it may be useful to compare only the affected element, dropdown, menu, or local region. That is a separate metric. The immediate goal is to make full-page state scoring correct first.

DOM stamping is no longer treated as a scoring substrate. The evaluator removes
its own `data-wde-node-id` attributes before clean artifact capture and
visual-block extraction.

## Implementation Steps

### Step 1: Enforce Rendered HTML Inputs

- Ensure HTML text/tree metrics only read `reference_artifact.outer_html` and `candidate_artifact.outer_html`.
- Add report labels showing `artifact_source: rendered_outer_html`.
- Add tests that fail if evaluator HTML metrics use route file paths.

### Step 2: Refactor CSSOM To Snapshot Inputs

- Split CSSOM extraction from CSSOM scoring.
- Keep extraction in the Playwright capture step.
- Store CSSOM boxes with both `bbox_px` and normalized `bbox`, plus viewport, document, screenshot, scroll, and coordinate-space metadata.
- Change block-style CSSOM scoring to consume captured snapshots and matched blocks.
- Remove file-path/default-render CSSOM calls from the core evaluator.

### Step 3: Refactor Visual Block To Isolated Playwright Replay

- Add a browser-state visual-block extractor behind a separate code path; do not replace the existing adapter in one step.
- Port WebCode2M OCR-free render IO faithfully:
  - assign unique text colors
  - render twice with different color offsets
  - diff the recolored screenshots
  - build the HTML text-color tree / equivalent text-color mapping
  - recover block boxes from the original manifest-state screenshot
- Use isolated Playwright pages for the recolored renders.
- In the isolated page/context, replay the same route, viewport, and manifest action state.
- Re-run target resolution inside the isolated page rather than using transient stamped selectors from the normal capture page.
- Feed extracted block lists into the existing WebCode2M/Design2Code merge, match, and scoring logic.
- First run static/default parity tests against the current visual-block adapter.
- Only after parity is understood, enable the new extractor for action-state captures such as dropdown and hover.

### Step 4: Manifest Intent Schema Migration

- Extend the manifest schema for optional intent and postcondition fields before relying on them.
- Keep existing selector/action manifests valid.
- Record intent usage and postcondition checks in `candidate-capture-plan.json`.

### Step 5: Tighten Candidate Control Resolution

- Remove hard overrides such as `same input type = confidence 1.0`.
- Require a combined match across role/tag/text/accessibility/name/id/label/geometry.
- Verify that postconditions are met after action replay.
- Record resolver confidence and postcondition confidence separately.

### Step 6: Update Reports

The core report should make substrate source explicit:

- screenshot metrics: manifest-state screenshot
- VLM: manifest-state screenshot
- HTML text/tree: manifest-state rendered `outerHTML`
- CSSOM: manifest-state CSSOM snapshot
- visual block: isolated manifest-state Playwright replay

## Acceptance Criteria

- No core scorer uses `reference_route.file_path` or `candidate_route.file_path` as its primary scoring substrate.
- Current static full-page HTML text/tree scores remain unchanged where rendered `outerHTML` equals source semantics.
- Dropdown/hover captures no longer produce visual-block false zeros from default-state rendering.
- CSSOM/block-style scores are computed from manifest-state CSSOM snapshots.
- Candidate capture plan records exact selector matches, resolver matches, intent usage, postcondition checks, and unsupported reasons.
- The evaluator remains framework-ready: React/Solid pages are evaluated through browser-rendered state, not source-code structure.
