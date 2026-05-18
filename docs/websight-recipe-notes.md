# WebSight Recipe Notes

Focused notes from `research/papers/text/websight_synthetic_webpage_screenshot_html_dataset.txt`.

## What WebSight Is Really Saying

WebSight's main contribution is not a metric. It is a data-generation recipe for screenshot-to-HTML learning:

```text
diverse website concept
  -> code-specialized LLM writes standalone HTML/Tailwind
  -> Playwright renders full-page screenshot
  -> filter weak/generated samples
  -> train/evaluate screenshot-to-code model
```

For our challenge, the useful part is the controlled reference-generation pipeline. WebSight argues against using arbitrary crawled web HTML as the primary source because real web code is noisy, long, dependency-heavy, and often not self-contained. That maps directly to our recipe: generate clean standalone reference sites, then evaluate rendered behavior rather than raw source similarity.

## Spec Design Implications

### 1. Use two-stage reference generation

WebSight first generates diverse website concepts, then asks a code-specialized model to implement one concept.

For us:

```text
stage 1: design brief generator
  industry/domain
  layout archetype
  unique design element
  color direction
  image/content requirements
  responsive/state requirements

stage 2: reference site builder
  implement exact site
  produce assets
  produce screenshot manifest
  produce hidden checklist
```

This is better than asking one model to "make a nice website" because the design space becomes inspectable and controllable.

### 2. Make every task self-contained

WebSight chooses synthetic standalone HTML/Tailwind because web-crawl HTML has external scripts, stylesheets, assets, and excessive length.

For our challenge:

- reference websites should be runnable without network access
- non-trivial media should be copied into an asset manifest
- candidate agents should receive the same assets when the task is about layout/code, not image invention
- source code similarity should stay diagnostic only

### 3. Control text, image placement, and page complexity

WebSight explicitly says prompt constraints can control topic, text length, and image placement. It also filters pages with insufficient text, generic content, and image/topic mismatch.

For us, the hidden spec should include:

- target visible text
- repeated-element counts
- required sections/components
- image roles and placements
- complexity labels: simple, medium, complex
- page length and viewport expectations

This gives us knobs for making easier/harder tasks without changing the grader.

### 4. Freeze images instead of using dynamic image URLs

WebSight uses Unsplash-style keyword image URLs to create visually rich synthetic pages. That is fine for dataset generation, but not deterministic enough for our evaluator.

For us:

```json
{
  "assets": [
    {
      "id": "hero-photo",
      "file": "assets/hero-photo.jpg",
      "role": "home hero background",
      "appears_in": ["home.desktop.full"]
    }
  ]
}
```

If the reference generator uses a photo, illustration, video, or generated bitmap, the candidate should receive that exact asset unless the task is explicitly testing asset recreation.

### 5. Keep Tailwind optional, not default

WebSight adopts Tailwind because it makes visually diverse, standalone pages concise. But it also reports Tailwind-specific failures: elements can fail to appear due to syntax issues or styling mistakes, and Tailwind was less common in the base model's pretraining than traditional CSS.

For us:

- start with vanilla HTML/CSS/JS as the cleanest baseline
- add Tailwind as a separate challenge mode
- do not mix "can match design" with "can write valid Tailwind" unless that is intentional

## Prompting Implications

WebSight's implementation prompt contains several useful constraints:

- build a complete website
- use a concrete styling system
- write real content, not lorem ipsum
- control image source and dimensions
- keep output standalone

Our first-pass prompt should do the same, but with deterministic assets:

```text
Build a complete static website matching the supplied screenshots.
Use only HTML, CSS, and JS.
Use the provided assets exactly where they appear in the screenshots.
Preserve every visible string in the visible text list.
Replicate repeated elements completely; do not use placeholder comments.
Match layout, spacing, typography, colors, borders, shadows, and responsive behavior.
Output complete runnable files only.
```

For screenshot-only hard mode, omit the visible text list. For normal fair mode, include it. WebSight says OCR is one of the core model prerequisites; providing text separately lets us decide whether the challenge is testing OCR or layout/code generation.

## Metric Feedback Implications

WebSight's failure cases map well to our metrics:

| WebSight failure | Our signal | Feedback to candidate |
| --- | --- | --- |
| Complex layout not replicated | `visual_block_score.position`, `bbox_geometry_score`, `presentation_diff_tags` | Fix layout/spacing/alignment in named capture. |
| Excessive text causes errors | `html_text_score`, `visual_block_score.text`, visible text diff | Restore missing/incorrect strings; reduce hallucinated text. |
| Elements present in code but not visible | `render_sanity_score`, `visual_block_coverage_score`, CSSOM color/effects | Make hidden/invisible elements render visibly; check color, display, opacity, z-index. |
| Text same color as background | `cssom_block_style_score.color`, accessibility contrast checks later | Fix foreground/background contrast for affected text. |
| Image/topic mismatch | asset manifest check, future media-quality tags | Use provided asset in the specified region. |
| Tailwind syntax/styling issues | render sanity, visual block coverage, CSSOM style groups | Fix invalid classes or switch to explicit CSS if allowed. |

The repair loop should therefore be:

```text
render candidate
  -> compare screenshot/text/block/CSSOM
  -> produce scoped issue report
  -> ask candidate to repair only affected capture/section
  -> recapture and rescore
```

## What WebSight Does Not Give Us

WebSight does not give a strong scoring method. It mainly uses qualitative inspection and notes that validation loss did not predict real-world code quality well.

So for us:

- do not treat model loss or one global similarity score as sufficient
- keep the metric vector we built
- use WebSight to improve task/spec generation, not to replace Design2Code/WebCode2M/WebCoderBench-style evaluation

## Immediate Recipe Change

Add a `reference_spec.json` artifact to generated tasks:

```json
{
  "concept": {
    "domain": "education platform",
    "layout_archetype": "hero + three-column cards + dropdown nav",
    "unique_design_element": "muted yellow text highlight strips",
    "style": "warm institutional, polished, accessible"
  },
  "content": {
    "visible_text": ["BrightPath", "Work with governments", "Work with enterprises"],
    "repeated_counts": { "program_cards": 3, "footer_columns": 4 }
  },
  "assets": [],
  "captures": [],
  "complexity": {
    "layout": "medium",
    "text_density": "medium",
    "states": ["dropdown", "focus", "mobile"]
  }
}
```

This is the bridge from WebSight's synthetic data recipe to our challenge recipe.

## Concrete Website Generation Recipe

Use WebSight as the backbone, but make it deterministic and evaluable.

### Step 1: Generate A Structured Concept

Do not start by generating code. First generate a compact concept with explicit design knobs.

Prompt template:

```text
Generate 10 diverse website challenge concepts.

Each concept must include:
- domain
- target audience
- page count
- layout archetype
- unique visual element
- color direction
- typography direction
- required content density: low / medium / high
- image/media requirements
- required interaction states
- mobile/responsive requirement
- difficulty: easy / medium / hard

Avoid generic SaaS landing pages. Make each concept visually inspectable and reproducible.
Return JSON only.
```

Good concept example:

```json
{
  "domain": "local architecture studio",
  "target_audience": "homeowners planning renovations",
  "page_count": 3,
  "layout_archetype": "editorial hero, split project grid, sticky side navigation",
  "unique_visual_element": "thin blueprint-style line dividers behind section headings",
  "color_direction": "warm white, charcoal, muted moss, pale steel blue",
  "typography_direction": "large serif headings, compact sans-serif metadata",
  "content_density": "medium",
  "image_media_requirements": ["hero studio photo", "six project thumbnails"],
  "interaction_states": ["nav hover", "project filter tabs", "contact input focus"],
  "responsive_requirement": "single-column mobile with no horizontal overflow",
  "difficulty": "medium"
}
```

This mirrors WebSight's first stage: make many diverse concepts before writing code.

### Step 2: Expand Concept Into `reference_spec.json`

The concept should become a hidden canonical spec. This is the source of truth for the reference builder and grader.

Required fields:

```json
{
  "id": "architecture-studio-medium-001",
  "concept": {},
  "pages": [
    {
      "id": "home",
      "path": "/index.html",
      "sections": ["hero", "services", "featured_projects", "contact_cta"]
    }
  ],
  "content": {
    "visible_text": [],
    "repeated_counts": {},
    "forbidden_text": ["Lorem ipsum"]
  },
  "design_tokens": {
    "colors": {},
    "typography": {},
    "spacing": {},
    "radius": {},
    "shadows": {}
  },
  "assets": [],
  "interaction_states": [],
  "capture_manifest": [],
  "quality_gates": {},
  "difficulty": {}
}
```

The important WebSight lesson: the prompt should control topic, text length, image placement, and complexity. This spec is where those controls live.

### Step 3: Generate The Reference Site

The reference builder prompt should be strict. It should produce code plus manifests, not just a page.

Prompt template:

```text
You are generating a reference website for a screenshot-to-code challenge.

Input: reference_spec.json.

Build a complete static website using HTML, CSS, and minimal JS.

Requirements:
- The site must run offline from local files.
- Use only assets listed in the asset manifest.
- Do not use external scripts, fonts, CSS CDNs, dynamic image URLs, analytics, or network requests.
- Write real, domain-specific copy. Never use Lorem ipsum or placeholder comments.
- Implement every page, section, repeated item count, and interaction state from the spec.
- Keep selectors stable enough for screenshot capture.
- Include accessible names for buttons, links, form inputs, and controls.
- Ensure desktop and mobile screenshots have no accidental horizontal overflow.

Output:
- site files
- assets/
- reference_spec.json
- screenshot-manifest.json
- asset-manifest.json
```

This differs from WebSight in one key way: WebSight can use dynamic Unsplash URLs for scale; our grader should freeze assets for determinism.

### Step 4: Render And Filter The Reference

Before a generated reference becomes a challenge, run quality gates.

Recommended gates:

| Gate | Why it exists | Check |
| --- | --- | --- |
| Render sanity | Avoid broken references | all captures nonblank and correct dimensions |
| Offline determinism | Avoid network variance | no external `src`, `href`, CSS imports, or scripts except local files |
| Text sufficiency | WebSight filters insufficient/generic text | visible text count above threshold; no lorem/placeholder comments |
| Asset validity | Avoid image mismatch | all manifest assets exist and render |
| State replay | Make hidden UI states reproducible | screenshot manifest actions all succeed |
| Mobile validity | Avoid accidental bad reference | no unintended mobile overflow |
| Accessibility baseline | Avoid bad controls as reference | no missing accessible names for obvious controls |
| Complexity target | Keep tasks calibrated | visual block count, DOM element count, page count, capture count within target band |

This is where our current metrics already help:

```text
render_sanity_score
mobile_overflow_tags
accessibility_control_tags
presentation_diff_tags for detecting accidental blank/unstable captures
visual_block_score block count / text count once reference screenshots exist
```

### Step 5: Package Candidate-Facing Evidence

The candidate should not receive `reference_spec.json` by default. They receive a derived task package based on the disclosure mode.

Disclosure modes:

| Mode | Candidate sees | What it tests |
| --- | --- | --- |
| screenshot-only | screenshots + assets | OCR, layout, code reconstruction |
| screenshot + visible text | screenshots + text list + assets | layout/code reconstruction without OCR bottleneck |
| screenshot + state labels | screenshots with semantic capture names | faithful state replication |
| full implementation brief | screenshots + text + assets + page/state brief | implementation skill, less reverse engineering |

For fair replication, evaluation captures should match disclosed captures. Withheld states should be a separate generalization track.

## Difficulty Knobs

Use these knobs to generate a balanced challenge set:

| Knob | Easy | Medium | Hard |
| --- | --- | --- | --- |
| Page count | 1 page | 2-4 pages | 5+ pages |
| Layout | single-column sections | grids/split layouts | nested grids, sticky regions, asymmetry |
| Text density | short headings/cards | mixed cards/forms | long tables/articles/dense nav |
| Assets | simple icons/shapes | several fixed images | many images/video/canvas-like visuals |
| States | hover/focus only | dropdowns/tabs/forms | modal flows, filters, scroll states |
| Responsiveness | one desktop capture | desktop + mobile | multiple breakpoints and state captures |
| Styling system | vanilla CSS | CSS variables/tokens | Tailwind/framework mode |

WebSight reports failures on complex layouts, excessive text, divergent styles, invisible elements, and Tailwind syntax. These are exactly the axes we should vary deliberately, not accidentally.

## Candidate Repair Feedback Recipe

Once a candidate fails, repair feedback should be produced from metric evidence.

Feedback prompt shape:

```text
You are repairing the candidate site. Do not rewrite unrelated sections.

Failing capture: {capture_id}
Reference evidence:
- missing visible text: ...
- layout/position issue: ...
- color/style issue: ...
- mobile/accessibility issue: ...

Required repair:
1. ...
2. ...

Preserve:
- ...
```

Metric-to-feedback mapping:

| Signal | Candidate feedback |
| --- | --- |
| low text score | list exact missing/hallucinated strings |
| low visual block coverage | list missing blocks/sections/states |
| low position score | name capture/region and ask for layout adjustment |
| low CSSOM typography/color/spacing/shape | ask for targeted style token fixes |
| mobile overflow tag | ask for responsive width/wrapping fix |
| accessibility tag | ask for labels/names on controls |
| render sanity failure | ask to fix build/render first |

The WebSight-specific point is that model outputs can include code for elements that never appear visually. So feedback should be based on rendered evidence, not source inspection alone.

## Best Current Recipe

For the first serious challenge batch, use:

```text
10 medium-complexity reference sites
HTML/CSS/JS only
2-4 pages each
desktop full-page + desktop viewport + mobile viewport captures
1-3 interaction states per site
provided assets frozen locally
candidate gets screenshots + assets + visible text
grader keeps reference_spec + capture_manifest
```

This isolates the challenge to layout/code reconstruction. Later we can remove visible text to create an OCR-heavy mode, add Tailwind/framework modes, or add withheld states for generalization.

## Rough Design Plan: Oracle Generation Pipeline

This is the current working plan for the first-hour challenge generator. The implementation target is a `Generator/` package that will use the cloud agents SDK. Any old sample code should be treated as stale until checked against current SDK docs.

### 1. User Request

The user enters a batch request:

```text
Generate 5 / 10 / 100 websites.
Optional metadata: domains, difficulty, page count, modalities, target audience, style families, or other constraints.
```

The orchestrator should treat this as a dataset-generation request, not as one website prompt.

### 2. Orchestrator Dataset Plan

The orchestrator first creates a big dataset plan.

This plan should specify:

- requested dataset size
- user-specified constraints
- broad data mix: domains, modalities, difficulty bands, page counts, and styles
- one-line concept seeds for every requested website
- per-site metadata that the concept engine can use

Example orchestrator output:

```json
{
  "dataset_size": 100,
  "global_constraints": {
    "stack": "static HTML/CSS/JS",
    "offline": true
  },
  "data_plan": {
    "domains": ["education", "finance", "healthcare", "civic services"],
    "modalities": ["landing page", "dashboard", "form-heavy flow", "editorial site"],
    "difficulty_mix": { "easy": 20, "medium": 60, "hard": 20 }
  },
  "site_seeds": [
    {
      "id": "site-001",
      "one_liner": "Education company landing site with audience-specific pages and a Work dropdown.",
      "metadata": {
        "domain": "education",
        "modality": "landing page",
        "difficulty": "medium"
      }
    }
  ]
}
```

The one-liner is not the final concept. It is the seed for the concept engine.

### 3. Concept Engine

For each site seed, the concept engine generates five to six candidate concept schemas in JSON mode.

A concept schema is the pre-code design object. It should be concrete enough for a website builder and verifier to use.

Schema fields:

- `domain`
- `site_goal`
- `audience`
- `description`
- `motif`
- `pages`
- layout pattern per page
- `message_intent`
- `required_text`
- content model
- natural controls/interactions
- asset needs
- mobile behavior

Controls are included when they are natural to the concept. The goal is not arbitrary thresholds like "at least five component types." The goal is a website that is interesting, coherent, and challenge-relevant.

Example concept schema shape:

```json
{
  "domain": "education",
  "site_goal": "Present an education company that works with governments, enterprises, schools, and students.",
  "audience": ["school administrators", "government education teams", "enterprise learning teams"],
  "description": "A polished institutional education site with a strong landing page and audience-specific pages.",
  "motif": "warm institutional design with impact metrics, soft highlight bands, and civic trust cues",
  "pages": [
    {
      "id": "home",
      "path": "index.html",
      "layout_pattern": "hero + impact metrics + audience cards + outcomes section"
    },
    {
      "id": "governments",
      "path": "governments.html",
      "layout_pattern": "policy-focused hero + program cards + outcomes"
    }
  ],
  "message_intent": [
    "Communicate that the company is a trusted education partner.",
    "Communicate measurable education impact."
  ],
  "required_text": ["Work", "Careers", "Contact Us", "With governments", "With enterprises", "With schools"],
  "content_model": ["impact statistics", "audience cards", "program cards", "contact details"],
  "interactions": ["Work dropdown", "contact form focus state", "mobile nav state"],
  "asset_needs": ["optional hero image or abstract education illustration"],
  "mobile_behavior": "single-column mobile layout with collapsed navigation"
}
```

### 4. Concept Critic Loop

A critic reviews the proposed concepts and ranks them.

Critique questions:

- Does the concept match the one-liner and metadata?
- Is the concept concrete enough to build?
- Is the concept visually and structurally interesting?
- Does the concept have a clear motif?
- Does it avoid a generic landing-page/template feel?
- Does it imply screenshot-worthy states or meaningful page structure?
- Is it feasible as a static/offline front-end website?

The critic outputs structured scores and feedback:

```json
{
  "candidates": [
    {
      "candidate_id": "concept-1",
      "score": 0.82,
      "accept": true,
      "strengths": ["clear audience-specific navigation", "good screenshot states"],
      "weaknesses": ["motif could be more distinctive"]
    }
  ],
  "best_candidate_id": "concept-1",
  "regenerate": false,
  "feedback_for_regeneration": []
}
```

If no concept is good enough, the feedback goes back to the concept engine for another batch. The critic reviews the new batch again. Once a concept passes the threshold, the best concept is propagated forward.

After this stage, the dataset should have one accepted concept schema for every requested website.

### 5. Website Builder Agent

Each accepted concept schema is passed to a website builder agent.

The website builder produces:

- static site files
- local assets
- `reference_spec.json`
- `asset-manifest.json`

The reference site should be deterministic, offline, and self-contained.

At this point, the builder may also propose screenshot state ideas, but the final screenshot manifest should be generated after verification.

### 6. Verifier / VLA Judge

The verifier takes the accepted concept schema, the generated website, rendered screenshots, DOM/CSSOM facts, and local metric outputs. Its job is Oracle QA: verify that the reference website matches the concept and is good enough to become a challenge.

The verifier can use:

- deterministic render checks
- DOM/control inventory
- CSSOM/style extraction
- accessibility and mobile tags
- screenshot captures
- VLA/VLM judgment for domain, motif, and interest

#### Contract Validation

Objective checks:

- all declared pages exist and render
- preliminary smoke captures can be taken for declared pages/states
- declared state ideas create visible UI changes when manually triggered
- required assets exist and render
- required content structures are present
- declared controls/interactions are present when specified
- no blank pages
- no placeholder text such as Lorem ipsum
- no accidental mobile overflow
- controls have accessible names where applicable

This uses the local browser runner, DOM/CSSOM extraction, accessibility tags, mobile overflow tags, and screenshot smoke checks. Full manifest replay happens after the snapshot manifest is generated.

#### Concept Fidelity Validation

VLA/VLM checks:

- Does the rendered site match the domain?
- Does it express the motif?
- Is it interesting rather than generic?
- Does each page match its stated purpose?
- Are the interactions meaningful rather than decorative?
- Does the visual design feel coherent enough to be a strong reference?

This is not the final candidate reward. It is Oracle QA.

The verifier outputs one of:

```json
{
  "status": "approved",
  "issues": [],
  "scores": {
    "contract": 0.96,
    "concept_fidelity": 0.91,
    "render_quality": 1.0
  }
}
```

or:

```json
{
  "status": "needs_repair",
  "issues": [
    {
      "type": "concept_mismatch",
      "message": "The Work dropdown was specified but is not visible in the rendered site."
    }
  ],
  "repair_instructions": [
    "Implement the Work dropdown with With governments, With enterprises, and With schools."
  ]
}
```

### 7. Builder Repair Loop

Failures should route to the right stage:

- concept is boring/vague: regenerate concept
- site omitted concept requirements: send back to website builder
- reference has render/mobile/accessibility problems: repair reference
- site is too similar to already accepted sites: later dataset-level diversity auditor

If the verifier returns `needs_repair`, the repair instructions go back to the website builder. The repaired site is rendered and verified again. If the site cannot pass after a retry budget, reject the concept or regenerate the site.

### 8. Snapshot Manifest Generator

Once the verifier approves the website, a snapshot manifest generator creates the screenshot manifest from the accepted concept and verified site.

The manifest generator decides:

- full-page captures
- viewport captures
- mobile captures
- hover states
- focus states
- dropdown-open states
- tab/accordion states
- scroll-position captures

Example manifest item:

```json
{
  "id": "home.desktop.work-dropdown",
  "path": "/index.html",
  "viewport": { "width": 1440, "height": 900 },
  "actions": [
    { "type": "hover", "selector": "[data-capture='work-menu']" },
    { "type": "wait", "ms": 200 }
  ],
  "screenshot": { "fullPage": false },
  "expected_visible_text": ["With governments", "With enterprises", "With schools"]
}
```

The manifest itself must be tested by replaying every capture. A website is not accepted until the manifest captures all required screenshots successfully.

### 9. Final Accepted Website Package

For each accepted website, store:

- concept seed
- accepted concept schema
- critic scores and feedback
- website source
- local assets
- verifier scores and feedback
- `reference_spec.json`
- `asset-manifest.json`
- `screenshot-manifest.json`
- rendered reference screenshots

### 10. Dataset-Level Diversity Auditor

Dataset-level diversity is important, but it is secondary to per-site quality right now.

Later, after enough websites are accepted, a dataset auditor can check:

- domain diversity
- layout diversity
- visual motif diversity
- component/control diversity
- screenshot embedding similarity
- overused palettes/templates

This should not block the first implementation of the per-site generation loop.

### Schema Language Decision

Use `message_intent` for flexible copywriting meaning, and `required_text` for exact visible strings.

Example:

```json
{
  "message_intent": [
    "Communicate that the company is a trusted education partner.",
    "Communicate that it works with governments, enterprises, schools, and students.",
    "Communicate measurable education impact.",
    "Encourage visitors to explore audience-specific pages."
  ],
  "required_text": [
    "Work",
    "Careers",
    "Contact Us",
    "With governments",
    "With enterprises",
    "With schools"
  ]
}
```

`message_intent` means the semantic communication goal. It does not require exact wording. `required_text` means strings that must appear exactly.
