# React vs HTML Evaluation Notes

Date: 2026-05-21

## Question

Can the same screenshot-to-code task be evaluated fairly when the candidate
implementation is plain HTML versus React?

## Current Answer

Yes, for the static website reproduction path. The evaluator now treats the
browser-rendered page state as the substrate:

- HTML candidates are served directly from `/app/site`.
- React candidates are built first, then served from `/app/site/dist` with SPA
  fallback.
- Candidate manifest planning maps oracle intents onto the rendered candidate
  app.
- Scoring consumes screenshots, rendered `outerHTML`, CSSOM, bbox geometry, VLM
  scores, DreamSim, pixelmatch, and capture coverage from the browser state.

This means the reward does not inspect React components as React components. It
scores what the browser renders after build, routing, hydration, and manifest
state replay.

## Four-Site Comparison

The report comparison uses four completed proper-full React evaluations against
the same oracle screenshots as the HTML run.

| Site | HTML reward | React reward | Read |
|---|---:|---:|---|
| Botanical garden nursery | 0.607 | 0.143 | React covered only part of the manifest and missed substantial content/style fidelity. |
| K-12 education | 0.678 | 0.133 | React failed many candidate states and content/layout checks. |
| Regional credit union | 0.569 | 0.582 | React slightly beat HTML; coverage was complete for both. |
| Curling federation | 0.414 | 0.304 | React had high global visual similarity but weaker rendered content. |

The result is mixed rather than categorical. React is not automatically worse;
the regional credit union candidate did slightly better in React. The K-12 React
candidate failed because the generated app did not reproduce enough routes and
states, not because the evaluator cannot handle React.

## Reward Interpretation

The comparison is useful because the reward surfaces different failure modes:

- `coverage` catches missing candidate states.
- rendered HTML catches wrong copy/content/structure.
- VLM and DreamSim measure broader visual plausibility.
- bbox and CSSOM measure local layout/style fidelity after visual-block matching.
- pixelmatch can be high even when content is wrong, so it is not enough on its
  own.

The Curling React candidate is the clearest example: DreamSim, VLM, pixelmatch,
and screenshot size are all strong, but rendered HTML is weak. The reward stays
low enough to reflect that it is visually plausible but not a faithful
reproduction.

## Data Files

Compact comparison data:

```text
docs/reports/data/react-vs-html-comparison.json
```

Report image panels:

```text
docs/reports/assets/framework-react-html-botanical-garden-nursery.jpg
docs/reports/assets/framework-react-html-site-01-education-k12.jpg
docs/reports/assets/framework-react-html-regional-credit-union.jpg
docs/reports/assets/framework-react-html-curling-federation.jpg
```

Primary source artifacts:

```text
harbor-report-data/ec2-local-harbor-full-reward-12-20260520-120454/tables/summary.json
/tmp/wde-pr-1/metrics-results/react-smoke-proper-full-modal-react-smoke-4-20260521-023358/*/reward.json
```

## Caveats

This is still a small sample. The current read is mixed rather than categorical:
React clearly failed two tasks, slightly beat HTML on one, and trailed on one
despite stronger broad visual metrics.

React visual-block aggregate score is not a reward component. The reward uses
visual-block matching logic for bbox/CSSOM where available, while
`visual_block.score` itself remains diagnostic.
