# Evaluation Progress Report

## Current State

We now have a small controlled setup for testing website design replication:

| Area | Status | Notes |
| --- | --- | --- |
| Reference site | Working | Static six-page BrightPath education website in `test-site/`. |
| Reproductions | Working | Two Claude-generated attempts in `reproductions/`. One good-ish, one intentionally poor. |
| Screenshot manifest | Working | Manifest captures full pages and a few page states. |
| Screenshot runner | Working | Playwright-based runner reads the manifest, opens pages, performs actions, and saves screenshots. |
| Scoring functions | Working | Local pixel/SSIM/CLIP/HTML/DOM/code metrics are available. |
| VLM judge | Working | OpenAI key loads from `.env`; VLM judge ran successfully on sample screenshots. |
| Harbor packaging | Not started | We have the pieces, but not yet wrapped as Harbor tasks/tests. |

## Files Of Interest

| File / Folder | Purpose |
| --- | --- |
| `test-site/` | Reference website. |
| `test-site/screenshot-manifest.json` | Canonical capture manifest for the reference site. |
| `scripts/capture-screenshots.mjs` | Playwright screenshot runner. |
| `test-site/screenshots/reference/` | Reference screenshots generated from the manifest. |
| `reproductions/claude-attempt-01/` | Better reproduction. |
| `reproductions/claude-attempt-02-bad/` | Worse reproduction. |
| `website_design_eval/scoring.py` | Scoring functions. |
| `website_design_eval/cli.py` | CLI wrapper for screenshot scoring. |
| `docs/scoring-functions.md` | Scoring API documentation. |
| `progress-logs/ideas.md` | Notes on assets, screenshot manifests, disclosure/evaluation policies. |

## Screenshot Capture

The active reference manifest currently captures:

| Capture type | Count | Examples |
| --- | ---: | --- |
| Full-page desktop screenshots | 6 | Home, governments, enterprises, schools, careers, contact |
| Page states | 3 | Work dropdown, scrolled work section, focused contact email field |
| Disabled / parked captures | 12 | Default viewport and mobile viewport captures |

The reproduction manifests use the same capture IDs where possible.

| Reproduction | Screenshots generated | Notes |
| --- | ---: | --- |
| `claude-attempt-01` | 9 | Implements dropdown, work-section scroll, email focus. |
| `claude-attempt-02-bad` | 8 | Dropdown state is missing/disabled because the page has no dropdown. |

This exposed an important grading question: missing states should not silently disappear. They should become an explicit coverage or missing-state penalty.

## Available Scoring Functions

| Function | Input | Current usefulness |
| --- | --- | --- |
| `render_sanity_score` | Screenshot, optional HTML | Useful guardrail for blank/broken renders. |
| `pixelmatch_score` | Screenshot pair | Strong deterministic visual signal. |
| `mse_score` | Screenshot pair | Diagnostic pixel error. |
| `mae_score` | Screenshot pair | Diagnostic pixel error. |
| `ssim_score` | Screenshot pair | Some signal, less separating than expected here. |
| `clip_similarity` | Screenshot pair | Strong perceptual signal; local model worked. |
| `vlm_judge_score` | Screenshot pair | Strong qualitative signal; API-backed and slower/costly. |
| `html_text_score` | HTML pair | Very useful for checking content preservation. |
| `dom_tree_score` | HTML pair | Some signal, but shallow and noisy. |
| `code_diff_score` | Code pair | Diagnostic only; can be implementation-biased. |
| `ast_code_score` | HTML/code pair | Not reliable as a visual signal. |
| `cw_ssim_score` | Placeholder | Not implemented. |
| `visual_block_score` | HTML + screenshot pair | Wired through the checked-in WebCode2M/Design2Code OCR-free block metric; promising but still optional/experimental. |
| `element_block_pixelmatch_score` | HTML + screenshot pair | Uses the visual block matcher, then runs pixelmatch on matched block crops. |
| `cssom_block_style_score` | HTML + screenshot pair | Uses the visual block matcher, then compares computed CSSOM styles for resolved matched blocks. |

## Metric Results

### Screenshot Metrics

Directory-level screenshot scoring against `test-site/screenshots/reference`.

| Reproduction | Pixelmatch ↑ | SSIM ↑ | CLIP ↑ | Missing captures |
| --- | ---: | ---: | ---: | --- |
| `claude-attempt-01` | 0.897 | 0.793 | 0.906 | None |
| `claude-attempt-02-bad` | 0.683 | 0.745 | 0.643 | `home.desktop.work-dropdown.png` |

Interpretation:

- Pixelmatch separated the good and bad attempts clearly.
- CLIP also separated them clearly.
- SSIM separated them, but less strongly.
- Missing captures are already surfaced by the directory scorer, but not yet converted into an explicit reward penalty.

### HTML / Code Metrics

Page-by-page scoring across:

- `index.html`
- `governments.html`
- `enterprises.html`
- `schools.html`
- `careers.html`
- `contact.html`

| Reproduction | HTML text F1 ↑ | DOM tree F1 ↑ | Code token F1 ↑ | Tag F1 ↑ |
| --- | ---: | ---: | ---: | ---: |
| `claude-attempt-01` | 0.989 | 0.364 | 0.789 | 0.727 |
| `claude-attempt-02-bad` | 0.303 | 0.244 | 0.762 | 0.839 |

Interpretation:

- `html_text_score` is very useful here. It strongly distinguishes the good attempt from the bad one.
- `dom_tree_score` is weak but directionally useful.
- `code_diff_score` is not very useful for design quality. The bad attempt still scores high because it has similar amounts of HTML/code.
- `ast_code_score` is actively misleading here: the bad attempt scores higher on tag F1 than the good attempt. This reinforces that tag structure is not design quality.

### Visual Block Metric

Home-page scoring through the checked-in WebCode2M/Design2Code OCR-free block metric:

| Reproduction | Score ↑ | Size ↑ | Text ↑ | Position ↑ | Text color ↑ | Masked CLIP ↑ |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `claude-attempt-01` | 0.957 | 1.000 | 0.997 | 0.885 | 0.972 | 0.931 |
| `claude-attempt-02-bad` | 0.584 | 0.096 | 0.729 | 0.752 | 0.628 | 0.717 |

Interpretation:

- This metric separated the two examples clearly on the home page.
- It is useful because it checks matched visual text blocks, not just whole-image similarity.
- It should stay optional for now because it is slower, dependency-heavy, and still uses the research pipeline internally.

### Element Block Pixelmatch

Home-page crop-level pixelmatch over the visual block matcher pairs:

| Reproduction | Coverage-adjusted ↑ | Matched crop pixelmatch ↑ | Block coverage ↑ | Matched pairs |
| --- | ---: | ---: | ---: | ---: |
| `claude-attempt-01` | 0.794 | 0.794 | 1.000 | 49 |
| `claude-attempt-02-bad` | 0.047 | 0.490 | 0.096 | 12 |

Interpretation:

- This reuses the visual block matcher. It does not add a new CSSOM or selector-based matcher.
- `matched_pixelmatch` checks whether corresponding matched block crops actually look alike.
- `coverage_adjusted_score` multiplies crop similarity by block coverage so a page cannot score well by matching only a small subset of blocks.

### CSSOM Block Style

Home-page computed-style comparison over the visual block matcher pairs:

| Reproduction | Coverage-adjusted ↑ | Matched CSSOM ↑ | Resolution ↑ | Coverage ↑ | Resolved pairs |
| --- | ---: | ---: | ---: | ---: | ---: |
| `claude-attempt-01` | 0.850 | 0.856 | 0.993 | 1.000 | 48 / 49 |
| `claude-attempt-02-bad` | 0.060 | 0.632 | 1.000 | 0.096 | 12 / 12 |

Interpretation:

- This does not change `visual_block_score`; it uses the visual block matcher as correspondence.
- It compares CSSOM groups for resolved rendered nodes: typography, color, spacing, shape, effects, and layout.
- The bad attempt has a moderate matched-style score on the small subset it matches, but the coverage-adjusted score is low because most reference blocks are missing or unmatched.

### VLM Judge

VLM was run on `home.desktop.full.png` only as an initial check.

| Reproduction | Overall ↑ | Layout ↑ | Typography ↑ | Color ↑ | Content ↑ | Visual hierarchy ↑ |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `claude-attempt-01` | 0.78 | 0.72 | 0.88 | 0.82 | 0.94 | 0.82 |
| `claude-attempt-02-bad` | 0.12 | 0.22 | 0.04 | 0.03 | 0.20 | 0.12 |

Interpretation:

- VLM judge strongly separates the two attempts.
- The notes are useful for qualitative debugging.
- It should probably be used as an audit/calibration metric, not the main reward, because it is slower, costs money, and may be less deterministic.

## What Is Working

### 1. The screenshot-manifest idea is good

The manifest makes hidden visual states explicit:

- full pages
- dropdowns
- focused fields
- scrolled sections
- later, mobile and animation states

This gives us a reproducible contract for both generating reference screenshots and capturing candidate screenshots.

### 2. Pixelmatch is a useful first deterministic signal

It produced a strong separation:

```text
good attempt: 0.897
bad attempt:  0.683
```

It catches color, spacing, position, missing blocks, and broad visual drift.

### 3. CLIP is useful as a perceptual signal

It separated:

```text
good attempt: 0.906
bad attempt:  0.643
```

This is useful because pixel metrics can over-penalize small shifts while CLIP can capture broader visual similarity.

### 4. HTML text scoring is very useful

It separated:

```text
good attempt: 0.989
bad attempt:  0.303
```

This helps catch cases where the visual style is plausible but the content is wrong or incomplete.

### 5. VLM judge is useful for calibration

The VLM judge gave intuitive scores and useful critique. It can help validate whether the deterministic reward is aligned with human judgment.

## What Is Not Working Yet

### 1. No single reward function yet

We have metrics, but not a final reward formula. The next step is a manifest-aware site scorer that emits one reward JSON.

### 2. Missing states are not penalized properly yet

The bad reproduction missing `home.desktop.work-dropdown.png` is reported, but not yet converted into a numeric penalty.

### 3. Candidate state capture is still manually mapped

For the good reproduction, the dropdown selector changed from `.dropdown` to `.has-menu`, so we wrote a reproduction-specific manifest.

This is okay for now, but the real grader should eventually understand state intent:

```json
{
  "state": "work dropdown open",
  "intent": {
    "triggerText": "Work",
    "expectedVisibleText": [
      "With governments",
      "With enterprises",
      "With schools"
    ]
  }
}
```

Then the grader can try reference selectors, text selectors, heuristics, and maybe LLM-assisted locator fallback.

### 4. Source HTML comparison will not generalize to React/Solid

For plain HTML, `html_text_score` and DOM checks can read source files directly.

For React, Solid, Tailwind, etc., source files are not comparable:

- source may be JSX/TSX
- DOM only exists after render/hydration
- Tailwind classes encode styling differently
- components can generate equivalent output from very different code

So the durable direction is **rendered DOM scoring**, not raw source scoring.

### 5. DOM/tag/code metrics are noisy

The bad attempt scored higher than the good attempt on tag F1. That means these metrics should be diagnostic or low-weight only.

## How To Handle Multiple Pages

The right shape is page-level scoring:

```text
site score
  home
    screenshots: full, dropdown, scrolled section
    HTML/text/DOM score: index.html
  governments
    screenshots: full
    HTML/text/DOM score: governments.html
  enterprises
  schools
  careers
  contact
```

Each page gets a local score:

```json
{
  "page": "home",
  "visual_score": 0.82,
  "text_score": 0.91,
  "dom_score": 0.36,
  "state_coverage": 1.0,
  "page_score": 0.80
}
```

Then the final site reward is an aggregate of all page scores.

## How This Changes For React / Solid

For modern frameworks, avoid raw source comparison.

Instead:

1. Build/run the candidate app.
2. Use Playwright to visit the same routes/states.
3. Capture screenshots.
4. Extract rendered DOM/text/layout/computed styles from the browser.
5. Score the rendered artifacts.

This means the same grader can work across:

- HTML/CSS
- React + CSS
- React + Tailwind
- Solid + Tailwind

The contract should be the rendered website, not the source structure.

## Proposed Reward Shape

Initial rough formula:

| Component | Weight | Notes |
| --- | ---: | --- |
| Visual screenshot score | 55% | Pixelmatch + SSIM + maybe CLIP. |
| Text/content score | 20% | HTML text now, rendered visible text later. |
| State coverage | 10% | Missing dropdowns/modals/focus states penalized. |
| Render sanity | 5% | Prevent blank/broken pages passing. |
| DOM/layout diagnostics | 10% | Use rendered DOM/layout later; source DOM only for now. |

Code similarity should not be in the main reward, or should be very low-weight, because it encourages copying the reference implementation rather than matching the design.

## Next Engineering Steps

### 1. Implement a manifest-aware `site` scorer

Add a CLI command like:

```bash
uv run website-design-eval site \
  --reference-root test-site \
  --candidate-root reproductions/claude-attempt-01 \
  --reference-manifest test-site/screenshot-manifest.json \
  --reference-screenshots test-site/screenshots/reference \
  --candidate-screenshots reproductions/claude-attempt-01/screenshots
```

It should:

1. Read the manifest.
2. Group captures by page.
3. Score matching screenshots.
4. Penalize missing required captures.
5. Score matching HTML pages.
6. Emit page-level and site-level JSON.

### 2. Add a simple aggregate reward

The output should look like:

```json
{
  "reward": 0.81,
  "visual_score": 0.78,
  "text_score": 0.91,
  "state_coverage": 0.89,
  "render_sanity": 0.92,
  "missing_captures": ["home.desktop.work-dropdown.png"],
  "pages": {}
}
```

### 3. Add rendered DOM snapshot extraction

This is the key bridge to React/Solid.

For each manifest capture, extract:

- visible text
- element bounding boxes
- computed styles
- headings/buttons/nav/form controls
- maybe coarse layout regions

### 4. Calibrate on more controlled variants

Create variants with known failure modes:

- wrong colors
- missing section
- layout shifted
- wrong typography
- missing dropdown
- bad responsive layout

Then verify that reward ordering matches expectation.

### 5. Only then wrap in Harbor

Once reward behavior is sane, package this into Harbor:

- task includes screenshots/assets
- agent writes website
- verifier captures candidate screenshots
- verifier runs site scorer
- verifier writes `/logs/verifier/reward.json`

## Current Takeaway

The current stack is promising:

- Pixelmatch catches concrete visual differences.
- CLIP catches perceptual similarity.
- HTML text catches content preservation.
- VLM judge is useful for calibration.
- DOM/code/tag metrics need caution.

The immediate missing piece is not more metrics. It is a clean **manifest-aware site scorer** that combines the existing metrics across pages and states into a stable reward.
