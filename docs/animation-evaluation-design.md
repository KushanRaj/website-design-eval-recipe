# Animation Evaluation Design

## Goal

Part 2 of the proximal challenge should extend generated website tasks with deliberate, judgeable animations.

The core rule is: do not infer animation intent from pixels alone. During oracle generation, we should know exactly which animation we asked for, preserve that intent in the manifest, and then evaluate whether the candidate reproduced the same browser-observed behavior.

## V1 Decision

Start with two animation channels only:

- `motion`
- `color`

Do not introduce a broad taxonomy yet. In V1:

- motion is scored with target bounding-box IoU and movement-weighted motion delta
- color is scored with target-box pixelmatch and CSSOM color comparison
- growth/shrink is not a separate channel; it affects the target bbox and is therefore covered by bbox IoU
- CLIP, DreamSim, SSIM, and full-page metrics are diagnostics only for animation, not primary scores
- shadows, blur, filters, SVG morphs, canvas/WebGL, Lottie, and video are out of V1 unless they can be represented as a simple color or motion target

This keeps animation evaluation narrow, interpretable, and directly tied to the concept generator's stated intent.

## Current Implementation Status

As of 2026-05-20:

- `Generator.models` has concept-level animation intent and manifest animation
  capture schemas.
- `Generator.prompts` asks the concept generator to emit structured animation
  intent when appropriate and asks the manifest generator to map that intent to
  replayable triggers, targets, and timelines.
- `website_design_eval/manifest_generator.py` accepts a top-level `animations`
  array and sanitizes trigger/target selectors against the browser-rendered
  inventory.
- `scripts/capture-screenshots.mjs` can replay animation entries and write frame
  timelines under `screenshots/reference/animations/<id>/`.
- `website_design_eval/evaluator.py` has early animation capture/scoring hooks
  for bbox motion, target pixelmatch, and CSSOM color.

Animation V1 is still not part of the final reward curriculum. It is an
additional browser-state metric track.

## Pipeline Roles

### Orchestrator

The orchestrator decides whether a page/task should include animation at all.

Its job is not to pick selectors or inspect implementation details. It decides, at the task level:

- whether this website/page should include animation
- which page should include animation
- whether the animation should be simple enough to grade reliably
- whether the concept generator should create one animation or a small set of animations

For V1, the orchestrator should prefer animations that can be expressed as motion, color, or both.

### Concept Generator

The concept generator must explicitly specify the animation intent.

It should not say only "make this animated." It should emit a structured spec that says what element is animated, what triggers it, what channel is expected, and how long it should run.

Required V1 fields:

- `id`
- `page`
- `target`
- `trigger`
- `channels`
- `durationMs`
- `description`

Optional notes such as easing, exact distance, exact colors, and repeat behavior can be included, but the V1 scoring contract is still channel-based.

Example motion animation:

```json
{
  "id": "home.feature-card-hover",
  "page": "home",
  "target": "primary feature card in the hero section",
  "trigger": {
    "type": "hover",
    "target": "primary feature card in the hero section"
  },
  "channels": ["motion"],
  "durationMs": 220,
  "description": "When hovered, the feature card lifts upward and settles smoothly."
}
```

Example color animation:

```json
{
  "id": "pricing.cta-color-hover",
  "page": "pricing",
  "target": "primary CTA button",
  "trigger": {
    "type": "hover",
    "target": "primary CTA button"
  },
  "channels": ["color"],
  "durationMs": 180,
  "description": "When hovered, the CTA background shifts from blue to green."
}
```

Example combined animation:

```json
{
  "id": "home.demo-card-click",
  "page": "home",
  "target": "interactive demo card",
  "trigger": {
    "type": "click",
    "target": "interactive demo card"
  },
  "channels": ["motion", "color"],
  "durationMs": 600,
  "description": "When clicked, the demo card moves toward the center, grows slightly, and changes accent color at the end."
}
```

The concept generator's responsibility is to make the animation declarative and testable. If it cannot describe the target, trigger, channel, and duration, the evaluator cannot reliably score it.

### Oracle Site Generator

The oracle site generator implements the animation in the reference site.

It can use raw HTML/CSS/JS, React, Solid, Tailwind, or another supported frontend stack. The evaluation substrate remains the browser-rendered result, not the source framework.

The oracle generator should preserve the concept animation spec and, where possible, add stable hooks:

- target element marker
- trigger element marker
- animation id
- implementation notes for the manifest generator

Example hooks:

```html
<button
  data-wde-animation-trigger="pricing.cta-color-hover"
  data-wde-animation-target="pricing.cta-color-hover"
>
  Start trial
</button>
```

Hooks are preferred for oracle reliability, but candidates are not required to copy them. Candidate resolution still uses browser-observed matching.

### Manifest Generator

The manifest generator maps concept-level animation intent to concrete browser-replayable captures.

Its job is to resolve:

- page path
- viewport
- trigger selector or trigger resolution signature
- target selector or target resolution signature
- sample timeline
- tracked channels
- tracked computed CSS properties for color animations

Example manifest shape:

```json
{
  "id": "home.demo-card-click",
  "kind": "animation",
  "page": "home",
  "path": "/index.html",
  "viewport": { "width": 1440, "height": 900 },
  "trigger": {
    "type": "click",
    "selector": "[data-wde-animation-trigger='home.demo-card-click']",
    "settleBeforeMs": 0
  },
  "timeline": {
    "durationMs": 600,
    "samplesMs": [0, 100, 200, 400, 600],
    "recordFrames": true,
    "recordBoundingBoxes": true,
    "recordComputedStyles": true
  },
  "targets": [
    {
      "name": "interactive demo card",
      "selector": "[data-wde-animation-target='home.demo-card-click']",
      "channels": ["motion", "color"],
      "track": [
        "transform",
        "background-color",
        "color",
        "border-top-color",
        "border-right-color",
        "border-bottom-color",
        "border-left-color"
      ]
    }
  ]
}
```

The manifest identifies what to observe, not how the candidate implemented it.

### Prompting Rule

The manifest prompt should only create animation entries from explicit
concept/oracle animation intent. It should not invent animation captures because
a page happens to have CSS transitions, hover styling, or incidental movement.

For each animation, the prompt should preserve:

- the human intent
- the target element description
- the trigger description
- the V1 channel: `motion`, `color`, or both
- the sampling duration/timeline

Selectors are only oracle replay hooks. Candidate evaluation should resolve the
same intent in the candidate's rendered browser state, not require the candidate
to copy oracle hooks.

## Trigger And Recording Semantics

For each animation capture:

1. Open the page in Playwright.
2. Set the manifest viewport.
3. Wait for the page to finish loading and hydrating.
4. Resolve the trigger and target in the live browser DOM.
5. Record the pre-trigger sample at `t=0`.
6. Apply the trigger.
7. Sample the target and frame at the manifest timestamps.
8. Repeat the same process for the candidate.

The first sample should be the pre-trigger state. After the trigger is applied, each later sample should be taken relative to the same monotonic timer. We should avoid arbitrary sleeps except for explicit manifest settle values.

For hover animations, the trigger is a Playwright hover action. For click animations, the trigger is a Playwright click action. For future scroll animations, the trigger can be a deterministic scroll action, but scroll is not necessary for V1.

## Animation Channels

Animation scoring is channel-specific. There should not be one universal animation score.

### Motion

For V1 motion, use only:

- `bbox_iou`
- `motion_delta`

`bbox_iou` compares the oracle target box and candidate target box at each sampled timestamp:

```text
area(intersection(reference_box_t, candidate_box_t))
/
area(union(reference_box_t, candidate_box_t))
```

This catches whether the animated element is in the right place and roughly the right size at each frame.

`motion_delta` compares movement between adjacent samples:

```text
reference movement from t[i] to t[i+1]
vs
candidate movement from t[i] to t[i+1]
```

The important correction is that `motion_delta` must be weighted by reference movement distance. Idle intervals should not give static candidates free credit. If the oracle does not move between two samples, that interval should contribute little or nothing to the motion-delta score.

Do not use CLIP, DreamSim, pixelmatch, or full-page similarity as primary motion scores. A static object can look visually similar while failing to move.

### Color

For V1 color, use:

- `target_box_pixelmatch`
- `cssom_color`

`target_box_pixelmatch` compares only the target crop at each sampled timestamp. It should not compare the full page because small target-level color changes get diluted.

`cssom_color` compares browser-computed color properties for the target:

- `background-color`
- `color`
- `border-top-color`
- `border-right-color`
- `border-bottom-color`
- `border-left-color`

This gives an interpretable diagnostic when a candidate visually misses the intended color change.

CLIP and DreamSim are too forgiving for simple color changes and should remain secondary diagnostics only.

### Size And Growth

No separate `size` channel in V1.

If an animation grows or shrinks an element, that change is reflected in the target bounding box and therefore affects `bbox_iou`. If we later need a clearer diagnostic, we can add `bbox_area_ratio`, but it should not be a primary V1 metric.

### Out Of V1

These animation families should be deferred:

- blur and filter animations
- complex shadows
- gradient shimmer
- SVG/path morphing
- canvas/WebGL effects
- Lottie/video animation
- continuous looping animation without a clear trigger or duration

They may need target-region frame diagnostics later, but they should not block the first implementation.

## Candidate Resolution

Reference selectors may not exist in the candidate implementation.

Candidate target and trigger resolution should follow the same manifest-aware validation principle:

1. Try exact selector if present.
2. Use role, text, label, and accessibility signature.
3. Use element type and nearby text.
4. Use static visual block or bounding-box matching when available.
5. Mark unresolved if confidence is too low.

Animation scoring should expose target and trigger resolution diagnostics separately from channel scores. If the evaluator cannot find the target or cannot replay the trigger, the animation should be reported as unresolved or low confidence instead of silently becoming a pixel mismatch.

## Framework Handling

The evaluator should be framework-agnostic.

Raw HTML, React, Solid, Tailwind, and similar frontend stacks are all handled the same way:

```text
serve app
open in Playwright
wait for rendered browser state
replay manifest trigger
sample frames, bbox, and CSSOM
score browser-observed behavior
```

The evaluator should not parse React components, Solid signals, Tailwind classes, or source files to determine correctness.

Framework differences are operational only:

- React/Solid may require a build step before serving.
- React/Solid may need hydration settle time before sampling.
- Tailwind classes are implementation details; computed styles are what matter.
- Dynamic DOM insertion/removal must be observed from the live browser DOM.

This matches the broader validation direction: the rendered browser state is the source of truth.

## Evaluation Output

The evaluator should report channel-level signals, not only one aggregate:

```json
{
  "animation": {
    "id": "home.demo-card-click",
    "target_resolution": 1.0,
    "trigger_replay": 1.0,
    "channels": {
      "motion": {
        "bbox_iou": 0.95,
        "motion_delta": 0.96
      },
      "color": {
        "target_box_pixelmatch": 0.91,
        "cssom_color": 0.88
      }
    }
  }
}
```

Aggregation can be decided later. The important part is that the evaluator exposes clean moving pieces.

## Artifacts

Animation evaluation should write debuggable artifacts:

```text
artifacts/reference/animations/<id>/
  frames/frame-000.png
  frames/frame-100.png
  target-crops/frame-000.png
  timeline.json
  contact-sheet.png

artifacts/candidate/animations/<id>/
  frames/frame-000.png
  frames/frame-100.png
  target-crops/frame-000.png
  timeline.json
  contact-sheet.png
```

`timeline.json` should include:

- sample timestamps
- resolved trigger metadata
- resolved target metadata
- target bbox per timestamp
- selected computed styles per timestamp
- frame and crop paths

## Harbor Packaging

For candidate-facing task packages, animation expectations should be described in plain language as part of the task prompt, not exposed as hidden metric internals.

Public package can include:

- reference static screenshots
- reference animation contact sheets or frame strips when useful
- text description of expected animation behavior

Private package should include:

- structured animation manifest
- target/trigger resolution metadata
- frame sampling schedule
- scorer configuration

The candidate should know what animation to reproduce, but not the exact scoring hooks.

## Prototype Findings

The isolated `animation-probe` experiment tested:

- a motion animation
- a color animation
- a combined animation with one flashing box and one moving/growing/color-changing box

Findings:

- Full-page frame similarity is too diluted for small animations.
- Target-region scoring is more useful than full-page scoring.
- For motion, bbox/trajectory signals are clearer than crop visual similarity.
- For color, target-box pixelmatch and CSSOM color are sharper than CLIP/DreamSim.
- DreamSim and CLIP are useful diagnostics but too forgiving for simple color changes.
- Unweighted motion delta can over-credit static candidates because idle intervals score well.
- Motion delta should be weighted by oracle movement distance or should ignore idle intervals.

Current preferred V1 metrics:

```text
motion channel:
  bbox_iou
  movement-weighted motion_delta

color channel:
  target_box_pixelmatch
  cssom_color
```

## Implementation Start Plan

1. Add schema support for concept-level animation intent.
2. Extend the screenshot manifest with an `animations` list.
3. Update concept and manifest prompts so animation intent flows from orchestrator to concept to manifest.
4. Add a Playwright animation capture module that records frames, target crops, bboxes, and CSSOM over a timeline.
5. Add motion scoring with bbox IoU and movement-weighted motion delta.
6. Add color scoring with target-box pixelmatch and CSSOM color comparison.
7. Package public animation evidence in Harbor as contact sheets/frame strips while keeping scoring internals private.

The first implementation should not change the existing static visual block score. It should add animation-aware artifacts and metrics alongside the current evaluation outputs.
