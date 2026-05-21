# Framework-Aware Candidate Evaluation

This note defines how React/Solid/HTML candidate tasks should be instructed and
evaluated. The goal is to support framework diversity without changing the core
screenshot, DOM, CSSOM, visual block, bbox, and animation metrics.

## Current Finding

The evaluator is already framework-agnostic after a candidate app is built. It
serves a prepared candidate root with a local static server, opens routes in
Playwright, waits for rendered browser state, then captures screenshots and
rendered DOM. A Vite React build works when the prepared candidate root points
at `dist/`.

The main issue is routing. Static HTML candidates usually expose files such as
`/minerals.html`. Vite React/Solid single-page apps usually build one
`dist/index.html` and render idiomatic client routes such as `/minerals` through
the JS router.

## Scope

This is candidate-evaluation support, not oracle-generation support.

The generator can continue producing the existing oracle sites and frozen
reference screenshots. A task may ask the candidate agent to reproduce those
screenshots using HTML, React, or Solid, regardless of how the hidden oracle site
was implemented.

The evaluator's job is therefore:

1. prepare the candidate output according to the requested framework contract
2. serve the prepared output correctly through Playwright
3. run the same manifest planning, replay, screenshot, DOM, CSSOM, visual-block,
   bbox, DreamSim, and VLM scoring paths as before

No metric should depend on whether the candidate source was written as static
HTML, React, or Solid. After the page is rendered in the browser, everything
should be evaluated as browser state.

## Task Contract

Each task should carry a framework field:

```json
{
  "candidate_framework": "html"
}
```

Allowed V1 values:

```text
html
react
solid
```

HTML tasks use the submitted folder directly. React/Solid tasks require a
buildable static app.

In Harbor, submitted candidate source should live under:

```text
/app/site/
  package.json
  src/
  index.html
```

For React/Solid, production build output must live under:

```text
/app/site/dist/
  index.html
  assets/
```

The verifier evaluates `/app/site/dist`, not `/app/site`.

This contract should be enforced mostly through prompting. The evaluator should
avoid broad output guessing. If the task asks for React/Solid, the verifier runs
the declared package build when `/app/site/dist/index.html` is absent. If the
package cannot be built or the build does not emit `dist/index.html`, the
verifier should fail with a clear `build_failed`, `build_not_attempted`, or
`dist_missing` status and include diagnostic hints about files that were
present.

Bounded diagnostics are useful, but they should not silently change the contract.
For example, the verifier may report that it saw `/app/site/build/index.html` or
`/app/site/out/index.html`, but V1 should not start evaluating those paths unless
the task contract explicitly allows alternate prepared roots.

The point is to keep the candidate instructions simple and the evaluator
deterministic: build in `/app/site`, emit `/app/site/dist`, then Playwright
evaluates `/app/site/dist`.

For the first local implementation pass, the verifier runs `npm install` or
`npm ci` followed by `npm run build` directly when a React/Solid candidate has no
existing `dist/index.html`. This is functional but not fully hardened. The
long-term Harbor implementation should move the same build step into a
no-secret build sandbox.

## Oracle And Screenshots

The oracle site and public screenshots do not need framework variants.

For a React/Solid candidate task, the agent still receives the same numbered
screenshots under `/app/reference/screenshots`. The only difference is the task
instruction: the agent is told to implement the reproduction in React or Solid
and produce a static build.

This lets one oracle dataset produce multiple candidate task variants:

```text
same oracle screenshots + candidate_framework=html
same oracle screenshots + candidate_framework=react
same oracle screenshots + candidate_framework=solid
```

The hidden oracle manifest remains the reference-side source of truth. Framework
support changes only candidate preparation, serving, and candidate-side manifest
planning.

## Candidate Instructions

For `candidate_framework = "react"`:

```text
Build the website using React.

Your submission must include:
- package.json
- source files under the submitted site folder
- a build script available as npm run build

For React, `/app/site/index.html` is the Vite application entry file. It is not
a requirement to create one final HTML file per route. `npm run build` must
create a production static build in `/app/site/dist/`.

The production site must work without `npm run dev`, a long-running development
server, or runtime CDN scripts. Use normal client-side routes if helpful. All
pages, interaction states, and animations must work in the production build.
```

For `candidate_framework = "solid"`, the same contract applies with Solid.

`npm run dev` is only for human preview. Evaluation should not call it.

## Build Isolation

Candidate install/build commands execute candidate-controlled code. The local
functional path currently runs those commands in the verifier wrapper. For
production Harbor hardening, they must not run in the normal verifier context
where API keys, private oracle files, or `tests/private/oracle-site` are
mounted.

The hardened build should happen in a separate disposable sandbox with:

- no `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or other evaluator secrets
- no `tests/private/`
- no oracle site
- no private oracle manifest
- no writable access to verifier artifacts except the declared build output

The hardened build sandbox emits only a static artifact folder, for example
`/app/site/dist`. The verifier then mounts/evaluates that static build folder in
the normal evaluation phase.

## Evaluator Build Flow

Before the existing evaluator runs, the packaged verifier prepares the candidate
root:

```text
if candidate_framework == "html":
  prepared_candidate_root = /app/site
  serve_mode = "static"

if candidate_framework in {"react", "solid"}:
  if /app/site/dist/index.html exists:
    use it directly
  else:
    run npm ci when package-lock.json exists, otherwise npm install
    run npm run build
    require /app/site/dist/index.html
  prepared_candidate_root = /app/site/dist
  serve_mode = "spa"
```

Production-hardened version, once a separate no-secret build sandbox is wired:

```text
if candidate_framework in {"react", "solid"}:
  run dependency install in no-secret build sandbox
  run npm run build in no-secret build sandbox
  copy only the resulting static build artifact into verifier evaluation
```

Build failures should be reported separately from visual score failures:

```text
build_failed
dist_missing
route_not_rendered
selector_not_found
action_failed
screenshot_scored
```

Package-manager policy:

```text
if package-lock.json exists:
  npm ci
else:
  npm install
```

Both install and build need explicit timeouts and captured stdout/stderr. The
build artifact should include:

- install command
- build command
- exit codes
- logs
- elapsed time
- resolved `prepared_candidate_root`
- sanitized route inventory artifact when route strings are extracted from
  source files

## Static vs SPA Serving

For HTML candidates, the evaluator should keep exact static serving.

For React/Solid candidates, the evaluator should support SPA fallback serving:

```text
requested /minerals
file dist/minerals does not exist
serve dist/index.html
React/Solid router renders the /minerals page
```

This fallback is needed because a normal Vite SPA build usually contains:

```text
dist/
  index.html
  assets/
    index-*.js
    index-*.css
```

It does not usually contain `/minerals.html`, `/glossary.html`, and so on.

SPA fallback must only apply to navigation/page requests. It must not rewrite
missing assets to `index.html`.

Good fallback cases:

```text
GET /minerals              -> dist/index.html
GET /minerals.html         -> dist/index.html, if treated as an oracle-path probe
GET /collections/gems      -> dist/index.html
```

Bad fallback cases:

```text
GET /assets/app.js         -> 404 if missing
GET /assets/app.css        -> 404 if missing
GET /images/hero.png       -> 404 if missing
GET /fonts/site.woff2      -> 404 if missing
```

This matters because a broken build should not look served merely because
missing JS, CSS, image, or font requests received HTML. Asset failures should
remain visible through browser console/network diagnostics and rendered output.

SPA fallback must be used consistently everywhere that inspects or replays the
candidate:

- browser inventory for candidate manifest planning
- candidate manifest action/selector validation
- evaluator replay/capture
- animation replay/capture

If candidate planning inventories `/minerals` with SPA fallback but evaluator
replay later serves `/minerals` as a static 404, planning and scoring will
disagree. The static server should therefore take the same `serve_mode` for both
inventory generation and replay.

## Candidate Manifest Planning

Framework-aware evaluation should continue to use the candidate manifest
planner. The planner receives:

- oracle manifest
- reference/oracle evidence
- candidate rendered route inventory using the same `serve_mode` as replay
- sanitized source-derived route candidates when available
- oracle-path-derived route probes
- candidate framework and serve mode

For React/Solid, the planner prompt should explicitly say:

```text
The candidate is a React/Solid SPA. Routes may be idiomatic, such as /minerals
instead of /minerals.html. Map oracle paths, actions, and selectors to
equivalent rendered candidate routes, actions, and selectors.
```

Example mapping:

```json
{
  "id": "minerals-card-hover-jewel-tone",
  "oracle_path": "/minerals.html",
  "candidate_path": "/minerals",
  "actions": [
    { "type": "hover", "selector": "[data-card-id='beryl']" }
  ]
}
```

The candidate manifest planner handles path, selector, and interaction
differences. The metrics still compare the rendered result.

For SPAs, rendered route discovery should not rely only on `<a href>` links.
Some routes are reachable through button handlers, router config, or source
constants. The planner input should include multiple route candidate sources:

```text
browser-discovered links/forms/buttons
sanitized source-derived route strings from candidate files
oracle path probes, for example:
  /minerals.html -> /minerals
  /glossary.html -> /glossary
  /index.html -> /
```

Each probe should be opened through the SPA fallback server and summarized with
title, visible text, controls, sections, and route status.

Source-derived route extraction must happen in the no-secret build/prep sandbox,
not in the normal verifier context. The verifier-side planner should receive
only a sanitized artifact such as:

```json
{
  "source_route_candidates": [
    { "path": "/", "source": "router-string" },
    { "path": "/minerals", "source": "router-string" },
    { "path": "/glossary", "source": "router-string" }
  ]
}
```

The planner should not freely inspect arbitrary candidate source while API keys,
private oracle files, or hidden manifests are mounted.

## Route Coverage Metadata

Route coverage metadata should distinguish guessed fallback from intentional
candidate manifest mapping. This can feed manifest coverage/reward later, but
the core distinction is metadata first.

Without a candidate manifest:

```text
oracle path: /minerals.html
candidate exact file: missing
evaluator fallback: /index.html
route resolution: deterministic fallback
coverage: penalized
```

The penalty is correct because the evaluator guessed.

With a candidate manifest:

```text
oracle path: /minerals.html
candidate manifest path: /minerals
SPA server serves dist/index.html
React router renders the Minerals page
route resolution: candidate-manifest mapped
coverage: full route coverage
```

The URL spelling difference should not be penalized when it is an explicit
candidate-manifest mapping and the route loads successfully. This only means
full route-resolution coverage. It does not mean the capture is correct. Capture
correctness remains governed by actual evidence:

- wrong rendered content
- selector/action failure
- visual mismatch
- DOM/text mismatch
- CSSOM/style mismatch
- animation mismatch

Bad case:

```text
candidate manifest maps /minerals.html -> /minerals
SPA loads /minerals
React still renders the homepage
selector is missing or content is wrong
route spelling is not penalized, but content/action/visual metrics score badly
```

## Animation Evaluation

Animation scoring is unchanged after the route is loaded, hydrated, and stable.
The candidate manifest planner maps the oracle animation trigger and target onto
candidate routes and selectors.

Example:

```json
{
  "id": "gem-card-jewel-shift",
  "path": "/minerals",
  "trigger": { "type": "hover", "selector": "[data-card-id='beryl']" },
  "targets": [
    { "selector": "[data-card-id='beryl']", "channels": ["color"] }
  ]
}
```

The evaluator then records frames and target artifacts exactly as it does for
HTML candidates.

React/Solid add two timing requirements:

- wait for route/hydration stability before static captures
- for animation captures, start the animation timeline only after the trigger
  and target selectors exist and the pre-trigger state is stable

For V1, "stable" should mean:

```text
page load has completed
network is idle or mostly idle within the configured timeout
the route URL/state expected by the manifest is active
two requestAnimationFrame ticks have passed
the DOM has had a quiet mutation window before capture
required trigger/target selectors are attached and visible
```

If route transitions are animated, the capture setup must wait for the route
transition to settle before firing the manifest animation trigger. Otherwise the
animation metric may compare route transition motion instead of the intended
element animation.

## Implementation Order

1. Add `candidate_framework` and `serve_mode` to task metadata.
2. Update candidate instructions for React/Solid build output.
3. Add prepared candidate root resolution:
   run install/build for React/Solid when needed, then require
   `/app/site/dist/index.html`.
4. Pass `prepared_candidate_root` and `serve_mode` into evaluator.
5. Extract sanitized source-route candidates in the build/prep step.
6. Add asset-safe SPA fallback mode to the shared static server used by both
   inventory and replay.
7. Pass framework/serve-mode, sanitized source routes, and route probes into
   candidate manifest planning.
8. Treat candidate-manifest mapped routes as intentional route-resolution
   coverage only.
9. Preserve penalties for unplanned deterministic fallbacks.

## Non-Goals For V1

- Do not support Next.js yet.
- Do not require React candidates to emit `/page.html` files.
- Do not use `npm run dev` in evaluation.
- Do not change the core metric set solely because the candidate used a
  framework.
