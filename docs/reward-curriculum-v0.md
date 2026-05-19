# Reward Curriculum V0

This is the current final-score proposal for the website design evaluator. It is intentionally a curriculum, not a flat average.

The school analogy is the right mental model: each capture has several exams. Passing the early exams matters, but early exams have small weight. A candidate that only does the basics well cannot receive a high final reward, because the high-value marks live in the later, more specific exams.

## Included Metrics

V0 counts:

- manifest/state coverage
- screenshot size match
- DreamSim
- Web2Code-style VLM overall score
- rendered HTML text BLEU
- rendered HTML text ROUGE
- visual block size
- visual block text
- visual block position
- visual block text color
- bbox geometry
- CSSOM block-style
- pixelmatch as a local Pass 3 precision signal

V0 does not count:

- masked CLIP inside visual block
- global CLIP
- SSIM / MSE / MAE
- raw code diff / AST score
- WebSee / WebCoderBench diagnostics
- tree BLEU / tree ROUGE / tree F1

Tree metrics remain in reports for now, but they are not part of this reward. On the current examples they mostly measure generic HTML skeleton overlap, so they do not separate good and bad attempts cleanly enough.

## Pass 1: Foundation

Pass 1 is worth 5% of the final score.

It asks whether the candidate showed up in roughly the right state:

```text
foundation =
  0.50 * manifest_coverage
+ 0.50 * screenshot_size_match
```

This is deliberately low weight. A poor page should not get meaningful reward merely because it routed to a page or matched screenshot dimensions.

## Pass 2: Content And Broad Fit

Pass 2 is worth 15% of the final score.

It checks rendered text content plus broad visual/state adequacy:

```text
content =
  0.35 * rendered_text_bleu
+ 0.35 * rendered_text_rouge
+ 0.15 * vlm_overall
+ 0.15 * visual_block_size
```

VLM and visual block size live here instead of Pass 1. They are stronger than pure attendance/size checks, but they should still not dominate the final reward. Text content remains the majority of Pass 2 because it varied meaningfully across the good and bad attempts.

## Pass 3: Specifics

Pass 3 is worth 80% of the final score.

It checks the details that should separate acceptable from excellent:

```text
visual_block_quality =
  0.40 * visual_block_text
+ 0.35 * visual_block_position
+ 0.25 * visual_block_text_color

visual_block_core =
  visual_block_size * visual_block_quality

local_layout_style =
  visual_block_size *
  (0.60 * cssom_block_style + 0.40 * bbox_geometry)

pixel_precision =
  visual_block_size * pixelmatch

dreamsim_visual =
  visual_block_size * dreamsim_score

specifics =
  0.35 * visual_block_core
+ 0.30 * local_layout_style
+ 0.20 * pixel_precision
+ 0.15 * dreamsim_visual
```

Visual block size gates the block-level detail scores. If the page only matches a tiny fraction of the reference visual block area, it should not receive high reward because a few matched blocks have similar text or styling.

DreamSim also belongs here, not in Pass 1. It remains a useful global perceptual signal, but it is multiplied by visual block size so a bad page cannot get too much reward from broad screenshot similarity alone.

Pixelmatch belongs here, not in Pass 1. It is a local exactness signal after the page has already shown broad and block-level similarity.

## Per-Capture Score

```text
capture_score =
  manifest_coverage *
  (0.05 * foundation + 0.15 * content + 0.80 * specifics)
```

Missing captures stay in the denominator. They receive score `0`; they are not dropped.

## Manifest Weights

The manifest can assign each capture a weight:

```json
{
  "id": "home.desktop.work-dropdown",
  "weight": 0.25
}
```

Current defaults in `test-site/screenshot-manifest.json`:

| Capture type | Weight |
| --- | ---: |
| full unique page | 1.00 |
| scrolled section | 0.50 |
| focused form state | 0.50 |
| dropdown / small interaction state | 0.25 |

The dropdown is lower weight because it is mostly the same page with a small state change. Full unique pages get the largest weight.

## Current Outputs

Latest validation run:

```text
metrics-results/reward-validation-2026-05-19/
```

| Candidate | Coverage | Size Match | Pixelmatch | DreamSim | VLM | Visual Block | Text BLEU | Text ROUGE | Final Reward |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `claude-attempt-01` | 1.0000 | 0.9474 | 0.9181 | 0.9321 | 0.8194 | 0.9690 | 0.8705 | 0.9164 | 0.8906 |
| `claude-attempt-02-bad` | 0.8197 | 0.8361 | 0.6970 | 0.5407 | 0.1560 | 0.5205 | 0.2092 | 0.2648 | 0.0985 |

Contribution breakdown:

| Candidate | Pass 1 / 0.05 | Pass 2 / 0.15 | Pass 3 / 0.80 | Final Reward |
| --- | ---: | ---: | ---: | ---: |
| `claude-attempt-01` | 0.0484 | 0.1340 | 0.7082 | 0.8906 |
| `claude-attempt-02-bad` | 0.0412 | 0.0280 | 0.0293 | 0.0985 |

The full comparison report is:

```text
metrics-results/reward-validation-2026-05-19/report.html
```

The executable form is:

```bash
uv run website-design-eval reward metrics-results/<run>/<candidate>/metrics.json \
  --weight-mode manifest \
  --output-json metrics-results/<run>/<candidate>/reward.json \
  --output-md metrics-results/<run>/<candidate>/reward.md
```

`--weight-mode manifest` uses capture weights from the manifest. `--weight-mode equal` ignores them. `--weight-mode suggested` applies the built-in defaults for old metric files that do not have weights.

## Determinism Expectation

For a fixed reference folder, candidate folder, manifest, browser version, and runtime environment, the browser-rendered artifacts should be deterministic:

- screenshots
- rendered `outerHTML`
- CSSOM snapshots
- visual blocks
- pixelmatch
- bbox geometry
- CSSOM block-style
- rendered text/tree metrics

If those change across repeated runs, treat it as an evaluator bug or a page-settling bug.

The only expected drift is:

- VLM judge output, because it is API-backed model inference
- very small DreamSim numeric drift if the model/runtime/device changes or nondeterministic kernels are used

Reward computation from a fixed `metrics.json` should be exactly deterministic.

## Open Questions

- Pixelmatch is currently full-screenshot pixelmatch. The likely better version is local pixelmatch over matched visual blocks or element boxes.
- VLM is counted as one broad foundation component for now. We still need more runs before deciding whether it should remain in the final reward.
- Tree metrics are excluded from reward, but we should keep collecting them until we have enough examples to retire or redesign them.
