# Idea Repository

## Monday, 18 May 2026, 5:10 PM IST

### Asset handoff rule

If the website generation pipeline uses image generation tools, downloaded assets, generated illustrations, photographs, videos, Lottie files, or any asset that cannot reasonably be reconstructed from CSS/SVG primitives, then the task must pass those assets to the agent directly.

The agent should receive:

- screenshots of the target website
- the actual assets used by the reference website
- an asset manifest describing where those assets appear

This keeps the task focused on design-to-code replication instead of testing whether the model can invent or regenerate the same image.

For simple assets, like basic logos, geometric illustrations, icon-like marks, abstract patterns, charts, or CSS/SVG shapes, it is reasonable to ask the model to recreate them. For non-trivial assets, provide them.

### Screenshot manifest

The website generator should not only produce the website. It should also produce a screenshot manifest.

Because the generator knows what it created, it should describe the important visual states that need to be captured:

- which pages exist
- which viewport sizes matter
- whether each capture is a full-page screenshot or only the visible viewport
- which dropdowns, menus, modals, tabs, hover states, focused fields, scrolled sections, or clicked states should be shown
- what action is needed to enter that state: hover, click, focus, scroll, wait, etc.

This matters because one screenshot per page misses important UI states. For example, a landing page may have a `Work` dropdown. The agent needs to see what the dropdown looks like, so the reference screenshots should include a dropdown-open state.

The manifest becomes a shared contract:

1. The reference site is rendered using the manifest.
2. The candidate site is rendered using the same manifest.
3. The grader compares the same page/state/viewport pairs.

Example manifest:

```json
{
  "baseUrl": "http://127.0.0.1:8001",
  "outputDir": "screenshots",
  "captures": [
    {
      "name": "home-desktop-viewport",
      "path": "/index.html",
      "viewport": { "width": 1440, "height": 900 },
      "screenshot": { "fullPage": false }
    },
    {
      "name": "home-desktop-full",
      "path": "/index.html",
      "viewport": { "width": 1440, "height": 900 },
      "screenshot": { "fullPage": true }
    },
    {
      "name": "home-work-dropdown",
      "path": "/index.html",
      "viewport": { "width": 1440, "height": 900 },
      "actions": [
        { "type": "hover", "selector": ".dropdown" },
        { "type": "wait", "ms": 200 }
      ],
      "screenshot": { "fullPage": false }
    },
    {
      "name": "contact-focused-email",
      "path": "/contact.html",
      "viewport": { "width": 1440, "height": 900 },
      "actions": [
        { "type": "click", "selector": "input[name='email']" },
        { "type": "wait", "ms": 100 }
      ],
      "screenshot": { "fullPage": false }
    },
    {
      "name": "home-mobile-viewport",
      "path": "/index.html",
      "viewport": { "width": 390, "height": 844 },
      "screenshot": { "fullPage": false }
    }
  ]
}
```

Example screenshot runner:

```js
import fs from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright";

const manifestPath = process.argv[2] ?? "screenshot-manifest.json";
const manifest = JSON.parse(await fs.readFile(manifestPath, "utf8"));

await fs.mkdir(manifest.outputDir, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage();

async function runAction(action) {
  if (action.type === "hover") {
    await page.hover(action.selector);
    return;
  }

  if (action.type === "click") {
    await page.click(action.selector);
    return;
  }

  if (action.type === "focus") {
    await page.focus(action.selector);
    return;
  }

  if (action.type === "scroll") {
    await page.evaluate(({ x = 0, y = 0 }) => window.scrollTo(x, y), action);
    return;
  }

  if (action.type === "wait") {
    await page.waitForTimeout(action.ms);
    return;
  }

  throw new Error(`Unknown screenshot action: ${action.type}`);
}

for (const capture of manifest.captures) {
  await page.setViewportSize(capture.viewport);

  const url = new URL(capture.path, manifest.baseUrl).toString();
  await page.goto(url, { waitUntil: "networkidle" });

  for (const action of capture.actions ?? []) {
    await runAction(action);
  }

  const outputPath = path.join(manifest.outputDir, `${capture.name}.png`);
  await page.screenshot({
    path: outputPath,
    fullPage: Boolean(capture.screenshot?.fullPage)
  });
}

await browser.close();
```

Future note: for animations, the same manifest can grow a `recording` or `frames` section. For example, record a 3-second video after hovering, or capture frames at `0ms`, `500ms`, `1000ms`, and `1500ms`.

## Monday, 18 May 2026, 6:06 PM IST

### Disclosure and evaluation policies

There is another axis here: how much information we show the agent.

In a 100% coverage setup, the agent gets everything:

- all pages
- full-page screenshots
- viewport screenshots
- mobile screenshots
- dropdown states
- hover states
- focused states
- scrolled states

In a lower-coverage setup, we deliberately remove some information. For example, we may only give the main full-page screenshots and not show dropdowns, mobile views, or hover states.

This means we should separate three things:

1. **Canonical manifest**: everything the website generator knows how to capture.
2. **Disclosure manifest**: what the agent actually sees.
3. **Evaluation manifest**: what the grader actually scores.

For normal fair replication, evaluation should match disclosure. If we never showed the dropdown, we should not grade the model on whether the dropdown looks exactly right. Otherwise we are not testing replication; we are testing inference from hidden information.

So:

```text
faithful replication mode:
  disclosure manifest = evaluation manifest
```

There can also be a harder generalization mode:

```text
generalization mode:
  disclosure manifest = visible subset
  evaluation manifest = visible subset + withheld states
```

In that case, withheld-state performance should be reported separately. For example:

```json
{
  "reward": 0.72,
  "shown_visual_score": 0.84,
  "shown_layout_score": 0.79,
  "withheld_visual_score": 0.41,
  "generalization_score": 0.41
}
```

This same idea applies whether the grader compares screenshots, rendered DOM/layout snapshots, CSSOM-derived information, or some broad HTML checks. The grader should know which capture states were disclosed and which were intentionally withheld.

There is also a separate label-disclosure axis. Screenshot names like `home.desktop.work-dropdown.png` reveal a lot. A more hidden task might rename files to `1.png`, `2.png`, etc. That should be a policy choice:

- semantic labels: `home.desktop.work-dropdown.png`
- light labels: `home-1.png`
- anonymous labels: `1.png`, `2.png`
- shuffled anonymous labels: random order with no page/state clues

For now, this is just an abstraction to keep in mind. The important point is: generate a full canonical capture set, then derive both the agent-facing evidence and the grader-facing evaluation set from policy.
