# Screenshot Capture Prototype

This is the first concrete version of the screenshot-manifest idea.

The manifest lives at:

```text
test-site/screenshot-manifest.json
```

The runner lives at:

```text
scripts/capture-screenshots.mjs
```

## Run

Install the Node dependency:

```bash
npm install
npm run screenshots:install
```

Capture the reference screenshots:

```bash
npm run screenshots
```

By default the runner starts a temporary local static server for the site root declared in the manifest. For this site, screenshots are written to:

```text
test-site/screenshots/reference/
```

You can also point the same manifest at another server:

```bash
node scripts/capture-screenshots.mjs test-site/screenshot-manifest.json --base-url http://127.0.0.1:8001
```

Or change the output directory:

```bash
node scripts/capture-screenshots.mjs test-site/screenshot-manifest.json --out /tmp/brightpath-shots
```

For generator/oracle replay, failed optional interaction states can be pruned
from the manifest:

```bash
node scripts/capture-screenshots.mjs site/screenshot-manifest.json --prune-failed
```

This writes `_replay-report.json` and removes failed optional captures from the
manifest. Required no-action captures still fail the replay. The generator uses
this mode because a flaky or low-value interaction should not poison an
otherwise good reference site.

## Manifest Shape

Each capture has:

- `id`: stable screenshot name
- `page`: logical page name
- `state`: human-readable state description
- `path`: URL path to visit
- `viewport`: browser viewport
- `actions`: optional browser actions before screenshot
- `screenshot`: screenshot options such as `fullPage`

Supported actions right now:

- `hover`
- `click`
- `focus`
- `fill`
- `press`
- `wait`
- `waitForSelector`
- `scroll`
- `scrollBy`

This is enough to capture default page states, dropdowns, focused fields, scrolled sections, and simple click-open UI states.

Each non-default capture should include an `intent` string. The selector/action
is only the oracle replay mechanism; the intent is the browser-visible state the
candidate evaluator should try to reproduce.

Good:

```json
{
  "state": "desktop district menu open",
  "intent": "Reveal the Our District navigation menu with district links and departments."
}
```

Too weak:

```json
{
  "state": "hover button",
  "intent": "Hover Our District"
}
```

## Manifest Generation

The LLM-backed manifest generator lives in:

```text
website_design_eval/manifest_generator.py
```

The CLI entrypoint is:

```bash
uv run website-design-eval generate-manifest \
  --reference-root site \
  --output site/screenshot-manifest.json \
  --backend claude-code \
  --model opus
```

Useful options:

- `--claude-auth subscription`: use the local Claude Code login instead of API keys.
- `--backend openai`: use the OpenAI backend.
- `--max-captures N`: optional explicit cap; by default there is no fixed cap.

The generator first renders the site in Playwright and builds a browser
inventory of routes, visible text, controls, sections, selector candidates, and
layout boxes. The prompt tells the model to use this rendered inventory as the
source of truth, not raw source files.

The model should generate the minimal set of high-information states:

- full-page captures for important unique pages
- hidden navigation panels such as dropdowns, megamenus, and submenus
- tabs, accordions, filters, or alternate layouts only when they reveal
  substantial visible content/data
- no repeated hover-highlight variants for every menu item

## Animation Captures

The manifest can also contain a top-level `animations` list. Static screenshots
remain under `captures`; animation timelines are separate.

Example shape:

```json
{
  "animations": [
    {
      "id": "home.card-hover",
      "kind": "animation",
      "page": "home",
      "path": "/index.html",
      "viewport": { "width": 1440, "height": 900 },
      "trigger": {
        "type": "hover",
        "selector": "[data-wde-animation-trigger='home.card-hover']"
      },
      "timeline": {
        "durationMs": 300,
        "samplesMs": [0, 100, 200, 300],
        "recordFrames": true,
        "recordBoundingBoxes": true,
        "recordComputedStyles": true
      },
      "targets": [
        {
          "name": "animated card",
          "selector": "[data-wde-animation-target='home.card-hover']",
          "channels": ["motion", "color"],
          "track": ["transform", "background-color", "color"]
        }
      ]
    }
  ]
}
```

Animation frame outputs are written under:

```text
screenshots/reference/animations/<animation-id>/
  frames/
  timeline.json
```

Animation expectations must come from concept/oracle intent. Do not infer
animation correctness from pixels alone.

## Container Note

For a future Harbor/Docker setup, the easiest path is probably to use the official Playwright image as the verifier or asset-generation environment:

```Dockerfile
FROM mcr.microsoft.com/playwright:v1.60.0-noble
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
CMD ["npm", "run", "screenshots"]
```

The exact Docker setup can wait. The important thing for now is that the website generator emits a manifest that describes all important visual states, and the screenshot runner can replay those states deterministically.

## Metric Renderer Caveat

Some metrics do not only consume the saved screenshot. Visual-block-style metrics render helper HTML internally so they can recover text blocks, bounding boxes, or DOM/CSSOM information.

Those internal renders must use the same manifest state as the saved screenshot:

- same page path
- same viewport
- same `fullPage` vs viewport screenshot mode
- same actions, such as hover, click, focus, scroll, and wait

If the saved screenshot shows a dropdown open but the metric's helper render does not perform the hover, the metric is looking at the wrong state. If the saved screenshot is a scrolled viewport but the helper render is an unscrolled full page, the coordinate system is wrong.

For now, stateful captures that a metric cannot replay should be reported as `N/A` or `metric_state_mismatch`, not as a true zero score.

The manifest-aware evaluator now follows this principle for visual-block
extraction by replaying the same state in an isolated Playwright page before
doing text-color mutation.
