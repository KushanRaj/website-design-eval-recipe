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
| Visual block | 0.00 |
| BBox geometry | 0.10 |
| CSSOM style | 0.10 |
| DreamSim | 0.10 |

These sum to `0.70`, so the implementation normalizes by `0.70` when all
components are available:

```text
capture_reward =
  coverage *
  (
      0.05 * screenshot_size_match
    + 0.10 * html
    + 0.20 * vlm
    + 0.05 * pixel_match
    + 0.00 * visual_block
    + 0.10 * bbox_geometry
    + 0.10 * cssom_style
    + 0.10 * dreamsim
  ) / 0.70
```

The final reward is the manifest-weighted mean of `capture_reward` across
scored manifest items. Static screenshots and animations are both manifest
items; animations do not get a separate multiplier or special bonus.

If a component is missing, skipped, errored, or unsupported, the reward removes
that component's weight from the capture denominator and renormalizes the
remaining available components. This is evaluator-failure handling, not a free
pass for bad outputs: a numeric score of `0.0` is still treated as a real zero.

Animation rows reuse the same component machinery with only the metrics that
exist for the animation channel:

- motion contributes through `bbox_geometry`, using target bbox IoU and
  reference-weighted directional motion delta.
- color contributes through `pixel_match` and `cssom_style`, using target-box
  delta pixel match and visual-area-weighted relative RGB color delta from the
  first sampled frame.
- screenshot size, HTML, VLM, visual block, and DreamSim are unavailable for the
  animation row unless explicitly added later, so they are removed from that
  row's denominator.

The color term is deliberately delta-based rather than absolute. For animation,
the honest question is whether the browser-observed style changed in the same
way over the timeline. A candidate should not receive high color-animation
credit merely because its initial or final color is close to the oracle; it must
match the relative RGB movement from the first sampled frame.

One caveat: animations are weighted like other manifest items. If a task has
many static captures and only one animation capture, even a severe animation
failure will only move the final task reward by that item's share of total
manifest weight. If animation fidelity is central to a task, the manifest should
assign that capture a higher weight or the curriculum should add an
animation-specific gate/cap.

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
  global_pixelmatch.score

visual_block =
  not computed for reward

bbox_geometry =
  bbox_geometry.score

cssom_style =
  cssom_block_style.score

dreamsim =
  dreamsim.score
```

`global_pixelmatch` is screenshot-level pixel match. Matched-block crop
pixelmatch is not computed in the core reward path.

`visual_block.score` is intentionally excluded from the reward. The evaluator
still performs visual-block extraction/matching when needed so BBox geometry and
CSSOM style can reuse the matched visible block pairs.

## Important Behavior

- Coverage is applied once, outside the component sum.
- DreamSim and global pixelmatch are not multiplied by visual-block size.
- BBox geometry and CSSOM style are separate components at 0.10 raw weight
  each. They are not averaged into a hidden combined 0.20 component.
- Unsupported/missing metric components are removed from that capture's
  denominator when gates pass. Numeric zero remains a real zero.
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
