# Evaluation Consolidation - 2026-05-19

This note pulls together the current state after the manifest-aware evaluator, rendered-state HTML/CSSOM work, isolated Playwright visual-block work, reward curriculum V0, and final validation run.

The short version: the useful direction is no longer "collect more metrics." The useful direction is to make the browser-state evaluator clean, reduce duplicated runtime, and then test redundancy inside a smaller set of promising signals.

## Current North Star

The browser-rendered manifest state is the scoring substrate.

For every capture, the evaluator should derive artifacts from:

```text
route loaded in Playwright
  -> viewport set
  -> manifest action/intent replayed
  -> page settled
  -> screenshot + rendered outerHTML + CSSOM + visual blocks
```

Raw source files are inputs for serving the site. They are not the main scoring substrate. This is what makes the evaluator compatible with static HTML now and React/Solid/dynamic apps later.

## What We Have Working

The current evaluator can:

- serve a reference folder and candidate folder on separate local origins
- read the oracle screenshot manifest
- generate a candidate capture plan instead of trusting a candidate manifest
- resolve routes and candidate actions
- capture screenshots, rendered `outerHTML`, CSSOM snapshots, and visual blocks
- report missing/unsupported states as manifest coverage failures
- compute DreamSim, VLM judge scores, pixelmatch, rendered HTML text/tree scores, visual block core, bbox geometry, and CSSOM block-style scores
- compute reward curriculum V0 from `metrics.json`
- produce Markdown/HTML reports with per-capture scores

Latest full validation output:

```text
metrics-results/reward-validation-2026-05-19/report.html
metrics-results/reward-validation-2026-05-19/report.md
```

Summary from that run:

| Candidate | Coverage | DreamSim | VLM | Pixelmatch | Visual Block | Text Rouge | Reward | Wall Time |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `claude-attempt-01` | 9 / 9 | 0.9321 | 0.8194 | 0.9181 | 0.9690 | 0.9164 | 0.8881 | 176.7s |
| `claude-attempt-02-bad` | 8 / 9 | 0.5407 | 0.1560 | 0.6970 | 0.5205 | 0.2648 | 0.0840 | 185.5s |

The bad candidate's dropdown remains a coverage failure instead of being converted into a fake visual-block zero.

## Current Score Surface

The metrics worth keeping in the main discussion are:

- manifest/state coverage
- render validity / screenshot size match
- DreamSim as the main global perceptual screenshot signal
- Web2Code/WebCode2M-style VLM judge as a flexible visual judge
- visual block core: size, text, position, text color
- bbox geometry over visual-block matches
- CSSOM block-style over visual-block matches
- rendered `outerHTML` text/tree metrics, mostly as a browser-state artifact and content/structure signal

The metrics that should stay out of the default path unless explicitly debugging/researching:

- SSIM
- MSE
- MAE
- global CLIP
- pixelmatch/diff as a first-pass score
- WebCoderBench diagnostic bundle
- WebSee diff/localization bundle
- WebCode2M bbox inventory tables
- code diff / AST code score

Pixelmatch is now included in reward curriculum V0 as a Pass 3 local precision signal. It is not a first-pass filter and it is not a standalone reward.

## Key Lessons So Far

### Screenshot coverage matters

One screenshot per page is not enough. Dropdowns, focused fields, scrolled sections, mobile views, clicked states, and hover states need explicit capture entries.

The canonical manifest is the full visual state contract. Disclosure and evaluation can be derived from it:

```text
canonical manifest: everything known
disclosure manifest: what the agent sees
evaluation manifest: what the grader scores
```

For fair replication, disclosure and evaluation should usually match. If withheld states are scored, report them separately as generalization.

### Assets need explicit handoff

If a reference site uses photographs, generated bitmap images, downloaded illustrations, video, Lottie, or other non-reconstructable assets, those assets should be passed to the candidate agent.

Otherwise the task accidentally tests asset invention instead of design replication.

### Raw HTML is the wrong long-term substrate

Static HTML makes raw source and rendered DOM look similar, but frameworks break that assumption. The evaluator should keep using:

```text
document.documentElement.outerHTML
```

after route load and manifest action replay.

### Visual block is useful but expensive

Visual block is valuable because it gives matched visual text blocks, not just global image similarity. It also underpins bbox geometry and CSSOM block-style scores.

Masked CLIP is now skipped in the manifest-aware default path. That removes the most questionable CLIP forward pass, but the evaluator is still multi-minute for a full good/bad validation because it replays nine captures per candidate and runs VLM/DreamSim/visual-block extraction over each scored capture.

DreamSim is not the bottleneck right now.

### Reference caching has two meanings

Inside one candidate run, reference artifacts are already computed once per capture and reused.

Across many candidate runs, reference artifacts are not yet shared. A future batch evaluator should compute oracle artifacts once globally and reuse them across N candidates.

For a single candidate, the realistic speedups are not reference caching. They are reducing duplicate visual-block replay, parallelizing VLM, and making render sanity cheaper.

## Reward Curriculum V0

The current reward proposal is documented in:

```text
docs/reward-curriculum-v0.md
```

The score is a weighted curriculum:

```text
capture_score =
  manifest_coverage *
  (0.05 * foundation + 0.15 * content + 0.80 * specifics)
```

Pass 1 is a low-weight foundation check, Pass 2 is rendered text content, and Pass 3 is visual/block/style/pixel/DreamSim specificity. DreamSim is counted in Pass 3 only after being multiplied by visual block size. The bad candidate scores `0.0840` on the latest run, which is much closer to the desired behavior than the earlier flat averages.

## Worth Looking Into Next

### 1. Single-page visual-block mutation after clean artifact capture

Current visual-block extraction opens an isolated page, replays the same manifest state, recolors text, screenshots twice, and extracts blocks.

That is correct, but slow.

The likely next optimization:

```text
normal capture page:
  capture clean screenshot
  capture rendered outerHTML
  capture CSSOM
  capture page state metadata
  then mutate this same page for visual-block recoloring
  screenshot recolored states
  close page
```

Since clean artifacts are captured before mutation, the visual-block color pollution should not contaminate them. This avoids a second navigation/action replay and should preserve the exact same hover/focus/scroll state.

This is the most practical single-candidate speedup.

### 2. VLM concurrency and reproducibility

VLM took about 49 seconds for 17 calls. These are independent image-pair judgements.

Use bounded concurrency, probably 3-4 calls at a time, and keep the report explicit about:

- model
- prompt/rubric
- run timestamp
- per-dimension scores
- whether the score is API-backed

This is a runtime optimization, not a reward-design decision.

### 3. Render sanity downsampling

Render sanity took about 45 seconds, which is too high for a guardrail.

It should become a cheap check:

- cache by screenshot path/hash
- downsample before entropy/color scans
- only run expensive checks when the cheap guard fails

### 4. Resolver/intents/postconditions

The candidate action resolver still needs to mature.

The right direction:

- route confidence separate from action confidence
- exact selector first
- rendered DOM/accessibility matching second
- optional manifest intent fields
- postconditions after action replay
- no hard rule like "same input type means perfect match"

This matters for dropdowns, focused fields, tabs, modals, menus, forms, and eventually component libraries.

### 5. Rendered element matching beyond text blocks

Visual block is mostly a text-block metric. It misses or underserves:

- icons
- hero images
- SVG-heavy sections
- cards/backgrounds/decorative panels
- image-only controls
- canvas/video/animation-heavy interfaces

The next experimental scoring substrate should be rendered element matching:

```text
extract rendered reference elements
extract rendered candidate elements
compare semantic + geometry + style + visual crop features
run maximum-weight one-to-one assignment
report matched / missing / extra elements
```

This should not replace visual block immediately. It should sit beside it and tell us whether it adds signal on non-text-heavy pages.

### 6. Generator pipeline and WebSight-style recipe

The WebSight notes are still useful, but mostly for dataset/reference generation rather than scoring.

The generator side should likely become:

```text
dataset plan
  -> concept candidates
  -> concept critic
  -> website builder
  -> verifier / oracle QA
  -> screenshot manifest generator
  -> accepted reference package
```

Useful knobs:

- page count
- capture count
- interaction count
- asset policy
- visual motif
- layout family
- text density
- mobile requirement
- framework/static constraint

This is related but separate from candidate scoring.

## Stale Or Historical Material

Some docs are intentionally historical and should not be treated as the current final recipe:

- `docs/evaluation-progress-report.md` still contains early metric tables where pixelmatch, CLIP, SSIM, code diff, and WebSee/WebCoderBench diagnostics were all being explored.
- `docs/scoring-functions.md` documents many available functions, including research/debug metrics. Availability does not mean default reward usefulness.
- `progress-logs/log1.md` and `log2.md` contain the early thought process around HTML/CSSOM/screenshots. The current resolution is: use browser-rendered state, not raw source HTML.

The current design center is better represented by:

- `docs/plans/001-manifest-aware-validation-framework.md`
- `docs/plans/003-browser-state-scoring-substrate.md`
- `progress-logs/ideas.md`
- this consolidation note

## Immediate Recommended Next Work

If the goal is to keep improving the evaluator, the next work should be:

1. Refactor visual-block extraction to mutate the already-captured page after clean artifacts are captured.
2. Add cheap/downsampled render sanity.
3. Add bounded VLM concurrency.
4. Add a local pixelmatch variant over matched visual blocks or element boxes.
5. Update `docs/scoring-functions.md` so it distinguishes:
   - historical/research functions
   - current default evaluator metrics
   - debug-only diagnostics

If the goal is to start dataset generation, switch tracks to the generator/WebSight recipe and validate one full generated website package end-to-end:

```text
concept -> reference site -> manifest -> screenshots -> evaluator run
```

## Do Not Do Yet

- Do not treat reward curriculum V0 as final or universal yet.
- Do not spend more time making SSIM/MSE/MAE central.
- Do not treat VLM as the only reward.
- Do not build a large React/Solid evaluator before the static browser-state path is cleaner.
- Do not optimize around reference caching unless evaluating many candidates per oracle.
