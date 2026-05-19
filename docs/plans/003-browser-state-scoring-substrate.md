# Plan 003: Browser-State Scoring Substrate

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

## What We Defer

Element-local scoring can come later.

Once both reference and candidate action targets are resolved, it may be useful to compare only the affected element, dropdown, menu, or local region. That is a separate metric. The immediate goal is to make full-page state scoring correct first.

DOM stamping cleanup can also come later unless it affects metrics. A clean implementation would isolate resolver DOM stamping from artifact capture, but the main functional blocker is visual block and CSSOM state correctness.

## Implementation Steps

### Step 1: Enforce Rendered HTML Inputs

- Ensure HTML text/tree metrics only read `reference_artifact.outer_html` and `candidate_artifact.outer_html`.
- Add report labels showing `artifact_source: rendered_outer_html`.
- Add tests that fail if evaluator HTML metrics use route file paths.

### Step 2: Refactor CSSOM To Snapshot Inputs

- Split CSSOM extraction from CSSOM scoring.
- Keep extraction in the Playwright capture step.
- Change block-style CSSOM scoring to consume captured snapshots and matched blocks.
- Remove file-path/default-render CSSOM calls from the core evaluator.

### Step 3: Refactor Visual Block To Isolated Playwright Replay

- Add a visual-block extractor that accepts a replayed Playwright page or a replay function.
- In an isolated page/context, replay the same route, viewport, and manifest action state.
- Inject color mutations into that isolated page.
- Screenshot mutated states with Playwright.
- Extract blocks from those mutated screenshots.
- Compare blocks with the existing WebCode2M/Design2Code scoring logic where possible.

### Step 4: Tighten Candidate Control Resolution

- Remove hard overrides such as `same input type = confidence 1.0`.
- Require a combined match across role/tag/text/accessibility/name/id/label/geometry.
- Verify that postconditions are met after action replay.
- Record resolver confidence and postcondition confidence separately.

### Step 5: Update Reports

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

