from __future__ import annotations

import json
from typing import Any

from .models import ConceptCandidate, GenerationRequest, SiteSeed, VerifierReport


ORCHESTRATOR_SYSTEM = """You are the dataset orchestrator for a synthetic website challenge.
Create a diverse batch plan, not website code. Every site seed must be compact
but vivid: name the real-world website type, the broad visual direction, and
the kind of multi-page experience expected. Every site must imply at least five
pages."""

CONCEPT_SYSTEM = """You are the concept engine for reference website generation.
Generate multiple concrete website concepts from one seed. Expand the seed into
realistic, visually distinct, multi-page website concepts that could plausibly
exist in the real world. Every concept must contain at least five pages."""

CRITIC_SYSTEM = """You are a strict concept critic. Score each concept for domain
fit, motif clarity, page/layout concreteness, interaction usefulness, realism,
and whether it avoids generic template output. Reject concepts with fewer than
five pages."""

BUILDER_SYSTEM = """You are the reference website builder. Write the website files
directly into the current working directory. Build a high-quality multi-page
reference website from the accepted concept. For this v1 generator, use vanilla
HTML, CSS, and JavaScript, but do not simplify the visual ambition of the
concept. Every accepted site must include at least five pages."""

VERIFIER_SYSTEM = """You are the Oracle QA verifier for generated reference
websites. Judge whether the rendered/static site should become a challenge
reference. Prefer concrete issues and repair instructions over vague criticism."""

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
- Keep one_liner values short but specific.
- Every one_liner must imply a website with at least five pages.
- Every one_liner must name the expected real-world feel, e.g. modern, sleek,
  dynamic, ancient, editorial, dense, clustered, playful, institutional, luxury,
  utilitarian, experimental, or another concrete visual direction.
- Preserve user metadata as constraints where relevant.
"""


def concept_prompt(seed: SiteSeed, request: GenerationRequest, feedback: list[str]) -> str:
    feedback_block = "\n".join(f"- {item}" for item in feedback) or "- None"
    return f"""Generate 5 to 6 concept candidates for this seed.

Seed:
{_json(seed)}

Dataset request:
{_json(request)}

Feedback from prior failed concept rounds:
{feedback_block}

Rules:
- Every concept must include at least five pages.
- Make page purposes distinct; do not produce five near-duplicate generic pages.
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
    return f"""Build or repair the static reference website for this accepted concept.

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
- At least five HTML pages, including index.html.
- A shared stylesheet, plus JavaScript only when useful for visible states.
- reference_spec.json describing the concept as implemented.

After writing files, respond with a concise summary and the list of files you wrote.
"""


def verifier_prompt(
    seed: SiteSeed,
    concept: ConceptCandidate,
    deterministic_report: Any,
    site_files: list[str],
) -> str:
    return f"""Verify whether this generated reference site should be accepted.

Seed:
{_json(seed)}

Accepted concept:
{_json(concept)}

Generated site files:
{_json(site_files)}

Deterministic report:
{_json(deterministic_report)}

If deterministic checks failed, do not approve. Return specific repair
instructions that a builder can act on. Do not approve a site with fewer than
five implemented pages.
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
