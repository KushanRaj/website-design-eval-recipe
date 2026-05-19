# Animation Evaluation Design

## Goal

Part 2 of the proximal challenge should extend the generated design tasks with deliberate, judgeable animations.

The important constraint is that animation scoring should not try to infer intent from pixels alone. The oracle generation pipeline should know what animation it intended to create, record that intent, and let evaluation check whether the candidate reproduced it.

## Pipeline Roles

### Orchestrator

The orchestrator decides whether a generated page/task should include animation.

Its job is not to pick selectors or inspect implementation details. It should decide at the design-task level:

- whether this website/page needs animation
- which pages should include animation
- what kind of animation is appropriate for the site type
- whether the animation should be simple enough to grade reliably

Examples:

- SaaS dashboard: subtle hover/focus transitions, drawer/modal entrance.
- Education site: card hover, dropdown reveal, scroll reveal.
- Product/portfolio site: hero entrance, carousel, feature card motion.
- Entertainment/game-like site: more expressive color/motion effects.

### Concept Generator

The concept generator must explicitly specify the animation intent.

It should not only say "make this page animated." It should emit a precise animation spec:

- animation id/name
- page
- target description
- trigger
- channel type
- duration
- timing/easing, if important
- intended start/end states
- whether the animation reverses
- whether the animation repeats

Example:

```json
{
  "id": "home.feature-card-hover",
  "page": "home",
  "target": "primary feature card in the hero section",
  "trigger": { "type": "hover", "description": "hover the card" },
  "channels": ["motion"],
  "durationMs": 220,
  "intent": "card lifts upward by about 8px and settles smoothly",
  "expected": {
    "motion": {
      "translateY": { "from": 0, "to": -8 },
      "easing": "ease-out"
    }
  }
}
```

For a color animation:

```json
{
  "id": "pricing.cta-color-hover",
  "page": "pricing",
  "target": "primary CTA button",
  "trigger": { "type": "hover", "description": "hover the CTA" },
  "channels": ["color"],
  "durationMs": 180,
  "intent": "button background shifts from blue to green",
  "expected": {
    "color": {
      "background-color": { "from": "#2563eb", "to": "#16a34a" }
    }
  }
}
```

For a mixed animation:

```json
{
  "id": "home.demo-card-open",
  "page": "home",
  "target": "interactive demo card",
  "trigger": { "type": "click", "description": "click the demo card" },
  "channels": ["motion", "size", "color"],
  "durationMs": 600,
  "intent": "card moves toward the center, grows, then changes accent color"
}
```

The concept generator's responsibility is to make the animation **declarative and testable**. If it cannot describe what changes and when, the evaluator cannot reliably score it.

### Oracle Site Generator

The oracle site generator implements the animation in the reference site.

It should preserve the concept animation spec and ideally write implementation notes into the generated metadata:

- target element description
- trigger element description
- expected selector, if known
- channels implemented
- duration/easing implemented

The oracle can be raw HTML/CSS, React, React + Tailwind, Solid + Tailwind, or another supported frontend stack. The grading substrate must remain the browser-rendered result, not the source framework.

### Manifest Generator

The manifest generator maps animation intent to concrete browser-replayable captures.

Its job is to resolve the concept-level description into:

- page path
- viewport
- trigger selector or trigger resolution signature
- target selector or target resolution signature
- sample timeline
- tracked channels
- tracked CSS/computed properties where useful

Example manifest shape:

```json
{
  "id": "home.demo-card-open",
  "kind": "animation",
  "page": "home",
  "path": "/index.html",
  "viewport": { "width": 1440, "height": 900 },
  "trigger": {
    "type": "click",
    "selector": "#demo-card",
    "settleBeforeMs": 100
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
      "name": "demo card",
      "selector": "#demo-card",
      "channels": ["motion", "size", "color"],
      "track": ["transform", "background-color", "border-top-color", "box-shadow"]
    }
  ]
}
```

The manifest should identify **what to observe**, not how the candidate implemented it.

## Animation Channels

Animation scoring should be channel-specific. We should not use one universal animation score for every animation type.

### Motion

For motion, use only:

- `bbox_iou`
- `motion_delta`

`bbox_iou` checks whether the candidate target occupies the same region as the oracle at each sampled timestamp.

`motion_delta` checks frame-to-frame movement:

```text
oracle center movement from t[i] to t[i+1]
vs
candidate center movement from t[i] to t[i+1]
```

This should be weighted by oracle movement distance so idle periods do not give fake credit to static candidates.

Do not use CLIP, DreamSim, pixelmatch, or full-page similarity as primary motion scores. A static object can look visually similar while failing to move.

### Size

Size can be treated as part of the motion/layout family when needed.

For first implementation, size can be represented through `bbox_iou` because IoU is sensitive to both position and size. If grow/shrink animations need more direct reporting later, add a `bbox_area_ratio` diagnostic, but keep the primary motion score simple.

### Color

For color, use:

- target-box pixelmatch
- CSSOM color comparison

Pixelmatch catches visual color differences inside the target region.

CSSOM color comparison is more interpretable and can report which computed color property diverged:

- `background-color`
- `color`
- `border-*-color`
- color-bearing shadow/effect properties where parseable

CLIP and DreamSim are too forgiving for simple color changes and should stay secondary diagnostics, not primary color scores.

### Visual/Effects Fallback

Some effects are not cleanly captured by bbox or simple CSS color:

- complex shadows
- filters
- blur
- gradient shimmer
- SVG/path morphs
- canvas/WebGL/Lottie/video effects

For those, target-region frame metrics may be used as fallback diagnostics. They should be explicitly tied to a `visual` or `effect` channel rather than included for every animation.

## Evaluation Flow

For each animation capture:

1. Load the reference page in Playwright.
2. Set the manifest viewport.
3. Wait for hydration/settle.
4. Resolve trigger and target selectors.
5. Replay the trigger.
6. Sample the timeline at the manifest timestamps.
7. Store reference frames and target timeline artifacts.
8. Load the candidate page in Playwright.
9. Resolve equivalent candidate trigger and target elements.
10. Replay the same trigger.
11. Sample the same timeline.
12. Compute channel-specific scores.

Artifacts should include:

```text
artifacts/reference/animations/<id>/
  frames/frame-000.png
  frames/frame-100.png
  timeline.json

artifacts/candidate/animations/<id>/
  frames/frame-000.png
  frames/frame-100.png
  timeline.json

metrics:
  animation channel scores
  target resolution diagnostics
  trigger replay diagnostics
  contact sheet for debugging
```

The evaluator should report sub-scores, not only a single aggregate:

```json
{
  "animation": {
    "id": "home.demo-card-open",
    "target_resolution": 1.0,
    "trigger_replay": 1.0,
    "channels": {
      "motion": {
        "bbox_iou": 0.95,
        "motion_delta": 0.96
      },
      "color": {
        "target_pixelmatch": 0.91,
        "cssom_color": 0.88
      }
    }
  }
}
```

Aggregation can be decided later. The important thing is to expose clean channel-level signals.

## Candidate Evaluation And Target Resolution

Reference selectors may not exist in the candidate implementation.

Candidate target resolution should therefore follow the same principle as manifest-aware validation:

1. Try exact selector.
2. Use role/text/accessibility signature.
3. Use element type and nearby text.
4. Use bounding-box / visual-region matching from static captures.
5. Mark unresolved if confidence is too low.

Animation scoring should be gated by target resolution and trigger replay. If the evaluator cannot find the target or cannot replay the trigger, the animation metric should be unsupported or low-confidence, not silently treated as a visual mismatch.

## Framework Handling

The animation evaluator should be framework-agnostic.

Raw HTML/CSS, React, React + Tailwind, and Solid + Tailwind should all be evaluated the same way:

```text
serve app
open in Playwright
wait for rendered browser state
replay manifest trigger
sample frames, bbox, CSSOM
score browser-observed behavior
```

The evaluator should not parse React components, Solid signals, Tailwind classes, or source files to determine animation correctness.

Differences by framework are operational only:

- React/Solid may require a build step before serving.
- React/Solid may need hydration settle time before sampling.
- Tailwind classes are implementation details; computed styles are what matter.
- Dynamic DOM insertion/removal must be observed from the live browser DOM.

This is the same design direction as the browser-state scoring substrate: the rendered page state is the source of truth.

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
- Motion delta must be weighted by oracle movement distance so idle frames do not inflate static candidates.

Current preferred first implementation:

```text
motion channel:
  bbox_iou
  movement-weighted motion_delta

color channel:
  target_box_pixelmatch
  cssom_color
```

This keeps the scorer narrow, interpretable, and aligned with the animation intent emitted by the concept generator.
