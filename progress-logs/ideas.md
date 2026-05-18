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

## Tuesday, 19 May 2026

### Renderer-state contract for metrics

One important issue showed up with the visual-block score: some metrics do their own internal render of the HTML instead of only looking at the already-captured screenshot.

That means the metric must render the exact same state as the screenshot manifest. If the screenshot was taken after hover, click, focus, scroll, or some other interaction, then the internal metric render also has to perform the same interaction before extracting blocks or DOM/CSSOM information.

The concrete failure case:

- `home.desktop.work-dropdown` screenshot has the `Work` dropdown open.
- `home.desktop.work-section` screenshot is scrolled to the work section.
- The visual-block metric internally rendered `index.html` again, but it rendered the default page state.
- It did not hover the dropdown and did not scroll to the work section.
- So the helper render and the screenshot were not the same state.
- The metric found zero text blocks and returned zero.

That zero should be treated as evaluator failure / not applicable, not as evidence that the candidate design is bad.

The fix is to make every render-based metric consume the same capture contract:

```text
capture id
page path
viewport
actions: hover / click / focus / scroll / wait / etc.
screenshot mode: full page or viewport
```

For visual block specifically, the internal flow should be:

1. Take the reference HTML and create the color-mutated helper HTML.
2. Open that helper HTML in Playwright with the manifest viewport.
3. Replay the reference capture actions, such as `hover .dropdown`.
4. Take the helper screenshot with the same `fullPage` setting as the real reference screenshot.
5. Do the same for the second color-mutated reference helper HTML.
6. Repeat the same process for the candidate HTML, using the candidate manifest actions/selectors.
7. Extract blocks from helper screenshots whose state and geometry now match the real screenshots.

If the candidate cannot provide an equivalent state, that should be a missing-state or unsupported-state signal. It should not silently become a zero visual-block score unless we explicitly want to penalize missing interaction coverage.

This matters for React/Solid/etc. too. The robust input to render-based metrics should eventually be "render this app to this manifest state, then extract screenshot + DOM/CSSOM", not "parse raw HTML and hope it represents the same state."

## Tuesday, 19 May 2026, 2:19 AM IST

### Metric pruning and reward hierarchy

We should stop treating every metric as equally useful. The current experiments suggest a narrower hierarchy.

DreamSim should stay as the main global perceptual signal. SSIM, MSE, and MAE should not be part of the main reward surface. They are too noisy for website screenshots, especially when full-page heights, crops, or small layout shifts differ.

Pixelmatch and visual diff should not be first-pass metrics. A better hierarchy is:

```text
first: DreamSim
then: WebCode2M-style VLM
then, only if those are good enough: pixelmatch / diff-style local checks
```

The intuition is that if the page is globally not close, pixel-level differences do not add much. If the page is globally close, pixelmatch or diff can become useful for catching smaller residual differences.

CLIP does not look valuable enough for the main scoring path. It is semantic and broad, and in the toy examples it did not separate good and bad reproductions with enough confidence. Keep it as optional research/debug at most.

The metrics that still look worth keeping in the main scoring discussion:

- DreamSim score / distance
- WebCode2M-style VLM judge
- visual block core scores: size, text, position, text color
- block/bbox geometry: bbox score, IoU, area similarity, center similarity
- CSSOM/block style scores
- HTML text and DOM metrics, with the future caveat that these should move from raw source HTML to rendered DOM for React/Solid/etc.

The metrics that should move out of the main scoring report:

- SSIM
- MSE
- MAE
- global CLIP
- WebCoderBench-style diagnostics
- WebCode2M bbox tree inventory table
- WebSee-style diff cluster inventory

Render sanity is still useful, but only as a validity guard: did the screenshot render, is it blank, did the capture fail? It is not a reward metric.

The next question is redundancy inside the narrower set. For example:

- DreamSim vs VLM: do both add signal, or is one enough?
- visual block position vs bbox geometry: are they measuring the same thing?
- visual block text vs HTML/rendered-DOM text: how much overlap is there?
- CSSOM layout/style vs bbox geometry: does CSSOM add signal beyond geometry?

For now, the record is: prune aggressively, keep the promising metrics, and treat the next phase as redundancy testing rather than metric accumulation.

### Future matcher: rendered elements beyond text blocks

Another important limitation: the current WebCode2M/Design2Code visual-block coverage is not full element coverage. It is mostly text-block coverage.

The OCR-free extractor works by associating rendered pixels with text/color extracted from HTML. That makes it strong for headings, paragraphs, nav labels, and text buttons, but weak for:

- central hero images
- icon-only controls
- form controls with little visible text
- background shapes, gradients, cards, and decorative panels
- canvas/video/SVG-heavy interfaces
- pages or states with very little text

So `visual_block.size`, `PM Coverage`, and `CSSOM Coverage` should be interpreted as coverage over detected text-ish visual blocks, not coverage over every meaningful UI element.

The future direction should keep the research-backed assignment shape from Design2Code/WebCode2M but replace/augment the element universe:

```text
extract rendered reference elements
extract rendered candidate elements
compute all pairwise similarities
run maximum-weight one-to-one assignment
report matched elements, missing reference elements, and extra candidate elements
```

The rendered element representation should include multiple channels:

- semantic: tag, role, accessible name, visible text, input type
- geometry: bbox, center, area, aspect ratio, viewport-normalized location
- style: computed typography, color, background, spacing, border, radius, shadow, opacity
- visual: screenshot crop pixel stats, perceptual hash, optional CLIP/DreamSim/DINO crop embedding
- context: parent/section membership, sibling order, nearby text, child summary

Matching should be type-aware rather than hardcoded:

```text
text nodes: text/name + bbox + style
buttons/links/inputs/selects/radios: role + accessible name + bbox + style
images/svg/icons/video/canvas: media tag + bbox/aspect + crop similarity + context
cards/sections/containers: child summary + bbox + background/style
decorative visual regions: bbox + color/gradient/crop similarity
```

The matcher should be hierarchical where possible:

```text
page regions -> components/cards -> leaf controls/text/media
```

This avoids matching the wrong repeated "Learn more" or repeated card element across distant page sections.

This should become an experimental `rendered_element_match_score` later. It should not replace `visual_block_score`; it should sit beside it and give a second coverage/matching substrate for DOM/CSSOM, bbox, and element-pixel scores when the page is image-heavy or control-heavy.

### Screenshot size as a separate signal

Full-page screenshots can have different heights even when the viewport is fixed. In this prototype the desktop full-page captures are `1440px` wide, but their heights depend on each page's rendered document height.

That matters because pixel-level metrics usually resize or pad before comparison:

- pixelmatch, MSE, SSIM, and CLIP resize the candidate to the reference dimensions in the current scorer.
- MAE pads to a shared larger canvas before resizing.
- VLM judges see the raw image sizes/aspect ratios, so a taller page can make all content look compressed relative to a fixed-viewport crop.

The insight is that page-height mismatch should not only leak through pixelmatch/MSE/SSIM or VLM perception. It should be surfaced explicitly as a diagnostic:

```text
screenshot_size_match_score
  width_score  = min(widths) / max(widths)
  height_score = min(heights) / max(heights)
  score        = width_score * height_score
```

Then full-page captures can be used for content/section completeness, while fixed-viewport captures remain better for local layout, scale, typography, and VLM judging.
