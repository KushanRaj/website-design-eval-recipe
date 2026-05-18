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
