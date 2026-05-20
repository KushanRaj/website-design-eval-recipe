# Evaluation Progress Report

Last updated: 2026-05-21

## Current State

The project has moved from a screenshot-scoring prototype to a manifest-aware
browser-state evaluator and a synthetic-site generation pipeline.

| Area | Status | Notes |
| --- | --- | --- |
| Reference test site | Working | Static BrightPath education site in `test-site/`. |
| Reproductions | Working | Good, bad, and moderate attempts under `reproductions/`. |
| Screenshot manifest | Working | Full pages plus meaningful page states, with per-capture weights and intent strings. |
| Manifest generator | Working | `website-design-eval generate-manifest` uses Playwright-rendered inventory and Claude Code/OpenAI backends. The inventory helper is currently Python sync Playwright. |
| Screenshot replay | Working | `scripts/capture-screenshots.mjs` replays static captures and optional animation captures. |
| Failed-state pruning | Working | Generator replay can prune failed optional captures instead of failing the whole seed. |
| Manifest-aware evaluator | Working | Serves reference/candidate folders, captures browser-state artifacts with Python async Playwright, writes `candidate-capture-plan.json`, and computes metrics. |
| Reward curriculum | Working V0 | `website-design-eval reward` computes the current weighted capture reward. |
| Harbor packaging | Working local path | Synthetic generated sites can be packaged into Harbor tasks with hidden verifier inputs. |
| Animation V1 | Integrated V1 | Static captures and animation captures are both manifest items in the current reward. |

## Files Of Interest

| File / Folder | Purpose |
| --- | --- |
| `website_design_eval/evaluator.py` | Manifest-aware evaluator runtime. |
| `website_design_eval/manifest_generator.py` | Browser-inventory-driven screenshot/animation manifest generator. |
| `website_design_eval/reward.py` | Reward curriculum V0. |
| `website_design_eval/scoring.py` | Screenshot, VLM, DreamSim, HTML, and diagnostic metrics. |
| `website_design_eval/block_visual.py` | Visual-block extraction and WebCode2M/Design2Code adapter. |
| `scripts/capture-screenshots.mjs` | Node/Playwright manifest replay and screenshot capture. |
| `Generator/` | Oracle/reference website generation pipeline. |
| `docs/reward-curriculum-v0.md` | Current final-score proposal. |
| `docs/evaluation-consolidation-2026-05-19.md` | Consolidated metric and evaluator notes. |
| `docs/animation-evaluation-design.md` | Animation scoring design. |
| `docs/harbor-packaging.md` | Harbor packaging and verifier-image flow. |

## Current Pipeline Shape

The current evaluator contract is:

```text
oracle site folder
oracle screenshot manifest
candidate site folder
  -> serve both on separate local origins
  -> resolve route and candidate action/state
  -> capture browser-rendered artifacts
  -> score artifacts
  -> compute weighted reward
```

The browser-rendered manifest state is the source of truth:

```text
route loaded in Playwright
  -> viewport set
  -> manifest state replayed
  -> screenshot
  -> rendered outerHTML
  -> CSSOM snapshot
  -> visual blocks
```

Raw source files are still inputs for serving and debugging. They are not the
main scoring substrate. This keeps the evaluator compatible with static HTML
today and React/Solid later.

Implementation note: the screenshot/capture evaluator path now uses Python
async Playwright and runs captures through an `asyncio.TaskGroup` with
`EvaluateConfig.capture_concurrency`. The isolated visual-block replay for
static captures also uses async Playwright. Non-browser scoring that is still
synchronous, such as DreamSim, VLM client calls, and visual-block pair scoring,
runs outside the browser path and may be dispatched to worker threads. The
experimental animation evaluator path still uses Python sync Playwright.

## Manifest Generation

The manifest generator now works from a Playwright-rendered browser inventory.
The prompt asks the model to produce:

- full-page captures for important unique pages
- interaction captures only when they reveal substantial hidden content, change
  layout, or change visible data/content
- intent strings that describe the desired visible state, not just the selector
  or action used in the oracle
- minimal high-information state coverage instead of repeated hover/focus noise
- optional `animations` entries when structured animation intent exists

The important distinction:

```text
selector/action = replay mechanism for this oracle
intent = semantic state the evaluator should look for in a candidate
```

For candidate evaluation, exact selectors may not exist. The evaluator uses the
oracle manifest as an intent/coverage guide and resolves candidate routes/actions
against rendered browser state.

Runtime note: oracle manifest generation and candidate manifest planning both
build route/control inventories through the shared `_browser_inventory` helper
in `website_design_eval/manifest_generator.py`. That helper currently uses
Python sync Playwright. The Claude Code calls around it are async, but inventory
collection itself has not yet been ported. After the candidate manifest is
produced, normal evaluator replay/capture uses the async Playwright evaluator
path.

## Screenshot Replay And Pruning

`scripts/capture-screenshots.mjs` is used both for reference screenshot
generation and generator smoke replay.

Normal behavior:

- required no-action captures must succeed
- failed captures are reported in `_replay-report.json`
- without pruning, any failed capture makes replay fail

Generator behavior:

- the generator calls replay with `--prune-failed`
- failed optional interaction captures are removed from the manifest
- successfully captured screenshots remain
- packaging later validates only the remaining enabled captures

This is intentional. A generated reference should not fail because of one flaky
or low-value interaction such as an offscreen dismiss button. Broad design
coverage matters more than proving every UI control is functionally clickable.

The generator validator also ignores managed `screenshots/` output during repair
loops, so screenshots created by a previous attempt are not treated as files
written by the builder.

## Current Score Surface

Default/currently useful metrics:

- manifest/state coverage
- render sanity and screenshot size match
- DreamSim
- Web2Code-style VLM judge
- rendered HTML text BLEU/ROUGE
- bbox geometry over matched visual blocks
- CSSOM block-style over matched visual blocks
- global pixelmatch as an exactness signal
- animation motion/color rows when present in the manifest

Collected but not counted in reward V0:

- visual-block aggregate score
- visual-block matched-block pixelmatch
- rendered HTML tree BLEU/ROUGE/F1
- SSIM
- MSE / MAE
- global CLIP
- WebSee / WebCoderBench diagnostics
- WebCode2M bbox inventory
- code diff / AST score
- masked CLIP inside visual block

Tree metrics remain in reports for now, but current examples show they mostly
measure generic HTML skeleton overlap and do not separate good/bad attempts well.

## Reward Curriculum V0

The current reward is a direct weighted score per manifest item, with coverage
applied once as the outer multiplier:

```text
capture_reward =
  coverage *
  weighted_mean_available(
    screenshot_size_match,
    rendered_html,
    vlm,
    global_pixelmatch,
    bbox_geometry,
    cssom_style,
    dreamsim
  )
```

Important current behavior:

- Visual-block aggregate scoring is not computed for reward.
- Visual-block matching is still computed when needed, because bbox geometry and
  CSSOM style use the matched visible-block pairs.
- Matched-block crop pixelmatch is not computed in the core reward path.
- `pixel_match` means screenshot-level global pixelmatch.
- If a metric is unavailable, skipped, or unsupported, its weight is removed
  from that manifest item's denominator. A real numeric `0.0` remains a real
  zero.
- Static screenshots and animation checks are both manifest items; animations
  reuse bbox geometry, global/target pixelmatch, and CSSOM-style channels where
  applicable.

Full details live in `docs/reward-curriculum-v0.md`.

## Animation V1

Animation work is now part of the synthetic dataset path and the current reward
surface.

Implemented shape:

- concepts can carry structured `animations`
- manifests can include top-level `animations`
- the capture script records animation frames and `timeline.json`
- evaluator hooks score motion/color channels from browser-observed timelines
- packaged Harbor tasks include animation metadata and hidden replay evidence
  when the generated oracle has animation captures

V1 only supports:

- `motion`: bbox IoU and movement-weighted motion delta
- `color`: target-box pixelmatch and CSSOM color comparison

Full-page DreamSim/CLIP/SSIM are not animation reward channels. Animation intent
comes from the concept/oracle side; the evaluator should not infer animation
intent from pixels alone.

## Harbor Status

The local Harbor packaging path exists:

```text
Generator/output/harbor-dataset/
  -> scripts/package_synthetic_dataset.py
  -> datasets/synthetic-website-replication/
```

Packaged tasks expose numbered screenshots to the agent. Hidden
verifier inputs contain the oracle site, manifest, and metric config.

Important rule: packaging never regenerates screenshots. It only copies and
validates them. If a manifest capture survives pruning, its PNG must exist.

## Open Engineering Items

- Keep testing generated oracle manifests on more sites and prune low-value/flaky
  replay states.
- Port `_browser_inventory` to async Playwright if manifest generation/planning
  becomes a meaningful bottleneck; this is separate from the already-async
  evaluator capture path.
- Improve candidate action resolution with stronger intent/postcondition use.
- Keep comparing EC2-local and Modal-backed Harbor runs under explicit resource
  overrides before deciding the default task resource contract.
- Run more controlled reproductions before locking reward weights.
