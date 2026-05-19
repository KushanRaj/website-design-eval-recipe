from __future__ import annotations

import json
from typing import Any

from .models import ConceptCandidate, GenerationRequest, SiteSeed, VerifierReport


ORCHESTRATOR_SYSTEM = """You are the website planning orchestrator.
Create a diverse batch plan, not website code. Every site seed must be compact
but vivid: name the real-world website type, the broad visual direction, and
the kind of multi-page experience expected. Every site must imply at least five
pages."""

CONCEPT_SYSTEM = """You are the concept engine for website generation.
Generate multiple concrete website concepts from one seed. Expand the seed into
realistic, visually distinct, multi-page website concepts that could plausibly
exist in the real world. Every concept must contain at least five pages."""

CRITIC_SYSTEM = """You are a strict concept critic. Score each concept for domain
fit, motif clarity, page/layout concreteness, interaction usefulness, realism,
and whether it avoids generic template output. Reject concepts with fewer than
five pages."""

BUILDER_SYSTEM = """You are the website builder. You are a hands-on
coding agent operating inside the empty site directory as your working directory.
Write files freely. You have Write, Edit, MultiEdit, Read, LS, Glob, Grep, and
Bash available — use whichever tools make sense (LS or `ls -la` to confirm
your layout, Read to revise a file you wrote earlier, Glob/Grep to find
existing files, Bash for recon like `find . -name '*.html'`). Write and Edit
automatically create parent directories, so you don't need `mkdir -p`.

There is no structured "bundle" to return: just write the website files into the
current working directory and reply with a short summary when done.

CRITICAL FILE PATH RULES:
- ALL file_path arguments to Write, Edit, MultiEdit MUST be RELATIVE paths that
  resolve INSIDE your current working directory.
- NEVER use absolute paths starting with "/". You don't need to know your
  absolute working directory — just write "index.html", "styles.css",
  "courses/page.html" etc.
- NEVER use ".." to escape upwards out of cwd. Stay inside cwd.
- Examples of CORRECT: "index.html", "css/style.css", "js/app.js",
  "courses.html", "topics/biology.html"
- Examples of FORBIDDEN: "/site/index.html", "/Users/.../index.html",
  "/root/site/css/style.css", "../outside.html", "../../escape.html"
- If a Write/Edit gets denied for "file_path must resolve inside the site
  directory", switch to a simple relative path like "index.html" and retry.

Build a high-quality multi-page website from the accepted concept.
For this v1 generator, use vanilla HTML, CSS, and a small amount of vanilla
JavaScript only when it adds visible value. Do not pull in build tooling, npm,
or external frameworks. Do not download anything. Do not simplify the visual
ambition of the concept. Every accepted site must include at least five
HTML pages, with index.html at the site root."""

VERIFIER_SYSTEM = """You are the Oracle QA verifier for generated reference
websites. You are the JUDGE. A separate deterministic extractor gives you a
structured report of measurements per page (render-sanity score, mobile
overflow pixels and tags, accessibility tags, component-style consistency
score, layout consistency / sparsity scores, etc.) and a presence map of
declared concept pages.

Your job is to apply judgment to those measurements and decide whether the
site is good enough to become a challenge reference. Use intent, not literal
matching. For example:

- If the concept declares a page at path '/subjects/{slug}' (a route template)
  and the builder implemented one or more concrete subject pages like
  'subjects/biology.html', that satisfies the concept. Do NOT flag it as a
  missing page just because the literal string with curly braces doesn't
  resolve.
- If the concept's required_text says "Contact Us" but the rendered site uses
  "Get in touch" with the same intent, that's substantively fine — call it
  out as a warning, not an error, unless the brand voice clearly demands the
  exact phrase.
- Treat per-page metrics as signals, not gates. A render_sanity of 0.6 with
  rich visible content is fine; a render_sanity of 0.9 on a blank page is
  not. Read the screenshots-and-text picture holistically.

Write all repair_instructions in plain English actionable to a coding agent.
Never write machine-format strings like 'Declared page is missing: /x/{y}'
verbatim — translate them into clear instructions: 'Implement at least one
concrete subject page (e.g. subjects/biology.html) to satisfy the
/subjects/{slug} route template.'

Prefer specific, surgical instructions over vague criticism."""

MANIFEST_SYSTEM = """You are the screenshot manifest generator for verified
reference websites. Create replayable Playwright-style capture specs for full
pages, mobile states, and meaningful interactions that are actually present in
the site. Include captures for at least five pages."""


def _json(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    return json.dumps(value, indent=2, sort_keys=True)


def orchestrator_prompt(request: GenerationRequest) -> str:
    return f"""Create a dataset plan for this request.

Request:
{_json(request)}

Rules:
- Create exactly {request.count} site seeds.
- Keep one_liner values short but specific: one sentence, 35 to 65 words.
- Each one_liner must include: website type/domain, visual feel, information
  density, interaction/navigation expectations, and the implied five-plus-page
  site shape.
- Every one_liner must imply a website with at least five pages.
- Every one_liner must name the expected real-world feel, e.g. modern, sleek,
  dynamic, ancient, editorial, dense, clustered, playful, institutional, luxury,
  utilitarian, experimental, or another concrete visual direction.
- Preserve user metadata as constraints where relevant.
- If the user asks for a narrow domain, diversify within that domain by varying
  audiences, page structures, interaction patterns, and visual styles.
- If the user asks for broad generation, cover distinct domains and avoid
  repeating the same SaaS/landing-page pattern.

Use this style for one_liner seeds:
- Government services portal: a dense civic services portal with tax filing,
  license renewal, benefit applications, login panels, alert banners,
  multi-level dropdown navigation, searchable service cards, and data-heavy
  status widgets.
- Sleek tech product site: a polished tech-forward product website with glossy
  dark UI, animated product panels, pricing pages, developer documentation
  previews, integration cards, comparison tables, and sharp dashboard-like
  visuals.
- Luxury hospitality group: an editorial luxury hotel group website with
  immersive destination photography, booking CTAs, room detail pages,
  restaurant/event pages, subtle motion, refined typography, and
  concierge-style contact flows.
- University department site: a structured academic department website with
  faculty directories, program pages, research labs, admissions information,
  event calendars, news lists, resource dropdowns, and institutional navigation
  density.
- Financial analytics platform: a high-trust financial analytics website with
  market dashboards, risk reports, product pages, compliance sections,
  chart-heavy feature blocks, account access CTAs, and precise enterprise
  styling.
- Arts festival or museum site: a visually expressive cultural website with
  exhibition pages, ticketing flows, artist/program schedules, sponsor sections,
  editorial essays, bold poster-like color systems, and event filter controls.

Do not copy these examples verbatim unless the user explicitly asks for that
exact domain. Treat them as density and specificity examples.
"""


def concept_prompt(seed: SiteSeed, request: GenerationRequest, feedback: list[str]) -> str:
    feedback_block = "\n".join(f"- {item}" for item in feedback) or "- None"
    return f"""Generate exactly 2 concept candidates for this seed.

Seed:
{_json(seed)}

Dataset request:
{_json(request)}

Feedback from prior failed concept rounds:
{feedback_block}

Rules:
- Every concept must include at least five pages.
- Make page purposes distinct; do not produce five near-duplicate generic pages.
- Treat the seed one_liner as the canonical creative brief. Expand it; do not
  replace it with a different domain or generic landing page.
- Explode the seed into concrete layout patterns, visual motifs, content models,
  and natural controls/interactions.
- Include natural controls/interactions when they fit the site.
- Do not use arbitrary component-count thresholds.
- Use message_intent for semantic communication goals.
- Use required_text only for exact visible strings that must appear.
"""


def critic_prompt(seed: SiteSeed, batch: Any) -> str:
    return f"""Critique this concept batch and select the best candidate if one is good enough.

Seed:
{_json(seed)}

Concept batch:
{_json(batch)}

Set regenerate=true if every concept is vague, boring, too generic, has fewer
than five pages, has five near-duplicate pages, or is not aligned with the seed.
Otherwise choose best_candidate_id.
"""


def builder_prompt(
    seed: SiteSeed,
    concept: ConceptCandidate,
    repair_feedback: list[str] | None = None,
    previous_report: VerifierReport | None = None,
) -> str:
    repair_feedback = repair_feedback or []
    repair_block = "\n".join(f"- {item}" for item in repair_feedback) or "- None"
    previous = _json(previous_report) if previous_report else "None"
    return f"""Build or repair the static website for this accepted concept.

Seed:
{_json(seed)}

Accepted concept:
{_json(concept)}

Repair feedback:
{repair_block}

Previous verifier report:
{previous}

Write:
- All files needed for the website into the current working directory.
- ONLY use relative file_path values. NEVER an absolute path starting with "/".
- At least five HTML pages, including index.html at the site root.
- A shared stylesheet, plus JavaScript only when useful for visible states.
- site_intent.json describing the concept as implemented.

After writing files, respond with a concise summary and the list of files you wrote.
"""


def verifier_prompt(
    seed: SiteSeed,
    concept: ConceptCandidate,
    deterministic_report: Any,
    site_files: list[str],
    attached_screenshots: list[str] | None = None,
) -> str:
    screenshot_block = ""
    if attached_screenshots:
        bullets = "\n".join(f"  - {name}" for name in attached_screenshots)
        screenshot_block = (
            f"\n\nAttached screenshots (one per declared page, taken from the "
            f"current build state):\n{bullets}\n\n"
            "These images are the rendered site as a candidate evaluator would "
            "see it. Use them as your PRIMARY evidence for visual judgment "
            "(layout, typography, color, density, hierarchy, brand fit). The "
            "concept and deterministic measurements below are supporting context.\n"
        )
    return f"""Verify whether this generated reference site should be accepted.

You are the JUDGE. The deterministic extractor below gives you measurements,
not verdicts. Apply intent and judgment to decide approval.{screenshot_block}

Seed:
{_json(seed)}

Accepted concept (declares the intended pages, motif, interactions, required text):
{_json(concept)}

Generated site files on disk:
{_json(site_files)}

Deterministic measurement report (treat as signals, not gates):
{_json(deterministic_report)}

Use the report's ``checks.page_presence`` map to see which declared concept
paths were resolved to actual files. An unresolved declared path is NOT
automatically a failure — if the concept used a route template like
'/subjects/{{slug}}' and the builder wrote a concrete instance like
'subjects/biology.html', that's fine. Mark it as missing only when the
builder genuinely failed to implement an intended page.

Use ``checks.per_page_summary`` and ``checks.per_page_metrics`` for visual
and accessibility signals. Score the site across:
- accessibility (any tags from accessibility_control_tags)
- mobile_responsiveness (mobile_overflow_px + tags)
- component_consistency (component_style_consistency score)
- layout_alignment (layout_consistency score)
- render_quality (render_sanity score)
- page_completeness (how well the implemented files satisfy the concept's
  declared pages, including route-template resolution)

Status decisions:
- ``approved``: site faithfully implements the concept and quality signals
  are acceptable. Minor warnings are OK if they don't break usability.
- ``needs_repair``: site has fixable quality issues (overflow, alignment,
  inconsistent cards, missing pages); write specific repair_instructions a
  coding agent can act on.
- ``rejected``: site fundamentally fails the concept (mostly blank pages,
  no real implementation, completely off-domain).

All repair_instructions must be PLAIN ENGLISH for a coding agent.
NEVER copy machine-format messages verbatim. Translate them.
"""


def manifest_prompt(
    concept: ConceptCandidate,
    verifier_report: VerifierReport,
    site_files: list[str],
) -> str:
    return f"""Create a screenshot manifest for this approved reference site.

Accepted concept:
{_json(concept)}

Verifier report:
{_json(verifier_report)}

Generated site files:
{_json(site_files)}

Rules:
- Use path values that match generated HTML files.
- Use selectors only when they are likely present in the generated files.
- Include full-page desktop captures for every page, with at least five pages.
- Include mobile captures when mobile behavior is specified.
- Include hover/focus/dropdown captures only when the concept and site files support them.
"""
