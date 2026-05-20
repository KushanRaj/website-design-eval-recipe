# Simple Weighted Reward V1

This replaces the earlier pass/curriculum formula. The reward is now a direct
weighted score per manifest capture, with coverage applied once as the outer
multiplier.

## Formula

Raw requested weights:

| Component | Raw weight |
| --- | ---: |
| Screenshot size match | 0.05 |
| Rendered HTML | 0.10 |
| VLM | 0.20 |
| Pixel match | 0.05 |
| Visual block | 0.20 |
| BBox geometry | 0.10 |
| CSSOM style | 0.10 |
| DreamSim | 0.10 |

These sum to `0.90`, so the implementation normalizes by `0.90`:

```text
capture_reward =
  coverage *
  (
      0.05 * screenshot_size_match
    + 0.10 * html
    + 0.20 * vlm
    + 0.05 * pixel_match
    + 0.20 * visual_block
    + 0.10 * bbox_geometry
    + 0.10 * cssom_style
    + 0.10 * dreamsim
  ) / 0.90
```

The final reward is the manifest-weighted mean of `capture_reward` across
captures.

## Gate

Before using the expensive/specific components, the capture must pass the basic
screening signals:

```text
screenshot_size_match >= 0.40
html >= 0.40
vlm >= 0.40
```

If any of these fail, only `screenshot_size_match`, `html`, and `vlm`
contribute. `pixel_match`, `visual_block`, `bbox_geometry`, `cssom_style`, and
`dreamsim` are set to zero for that capture.

## Component Definitions

```text
html =
  mean_available(
    rendered_html_text_bleu_1,
    rendered_html_text_rouge_1_recall,
    rendered_dom_tree_bleu,
    rendered_dom_tree_f1
  )

vlm =
  web2code_style_vlm.overall

pixel_match =
  mean_available(global_pixelmatch.score, visual_block.block_pixelmatch.score)

visual_block =
  visual_block.score

bbox_geometry =
  bbox_geometry.score

cssom_style =
  cssom_block_style.score

dreamsim =
  dreamsim.score
```

`global_pixelmatch` is screenshot-level pixel match. `visual_block.block_pixelmatch`
is the matched-block crop pixel match from the visual-block correspondence.

`visual_block.score` is the visual-block aggregate excluding masked CLIP in the
current core path. It uses the block size/text/position/text-color agreement
from the Playwright-captured state.

## Important Behavior

- Coverage is applied once, outside the component sum.
- DreamSim and global pixelmatch are not multiplied by visual-block size.
- BBox geometry and CSSOM style are separate components at 0.10 raw weight
  each. They are not averaged into a hidden combined 0.20 component.
- Unsupported/missing metric components score `0` for that component only.
- Unsupported visual block does not suppress DreamSim or other global metrics
  unless one of the explicit gate inputs fails.

## Current Implementation

Code:

```text
website_design_eval/reward.py
```

Tests:

```text
website_design_eval/tests/test_reward.py
```

Harbor reward wrapper:

```text
scripts/package_harbor_task.py
```

The wrapper writes `reward.json`, `reward-details.json`, and
`reward-report.md`. `reward.json` includes the final reward and the major
component summaries so the score can be inspected without opening the full
details file.
