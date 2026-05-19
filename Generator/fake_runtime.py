from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from .manifest import manifest_from_concept
from .models import (
    BuildReport,
    ConceptBatch,
    ConceptCandidate,
    ConceptCritique,
    CriticCandidateScore,
    DatasetPlan,
    PageSpec,
    RepairIssue,
    ScreenshotManifest,
    SiteSeed,
    VerifierReport,
)

T = TypeVar("T", bound=BaseModel)


def _first_json_object(text: str) -> dict:
    start = text.find("{")
    if start < 0:
        return {}
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : index + 1])
                except json.JSONDecodeError:
                    return {}
    return {}


class FakeRuntime:
    """Deterministic runtime for tests and local dry runs."""

    def __init__(self, *, concept_reject_rounds: int = 0, verifier_repair_rounds: int = 0) -> None:
        self.concept_reject_rounds = concept_reject_rounds
        self.verifier_repair_rounds = verifier_repair_rounds
        self._concept_calls = 0
        self._verifier_calls = 0
        self.last_concept: ConceptCandidate | None = None

    async def run_json(
        self,
        *,
        agent_name: str,
        system_prompt: str,
        user_prompt: str,
        output_model: type[T],
        image_paths: list[Path] | None = None,
    ) -> T:
        del system_prompt, image_paths
        if output_model is DatasetPlan:
            return self._plan(user_prompt)  # type: ignore[return-value]
        if output_model is ConceptBatch:
            return self._concept_batch(user_prompt)  # type: ignore[return-value]
        if output_model is ConceptCritique:
            return self._critique()  # type: ignore[return-value]
        if output_model is VerifierReport:
            return self._verifier_report()  # type: ignore[return-value]
        if output_model is ScreenshotManifest:
            concept = self.last_concept or self._default_concept("site-001")
            return manifest_from_concept(concept, site_name="fake-site")  # type: ignore[return-value]
        raise AssertionError(f"FakeRuntime does not know how to build {output_model.__name__}")

    def _plan(self, prompt: str) -> DatasetPlan:
        request = _first_json_object(prompt)
        count = int(request.get("count", 1))
        base_prompt = str(request.get("prompt", "website"))
        seeds = [
            SiteSeed(
                id=f"site-{index + 1:03d}",
                one_liner=(
                    f"{base_prompt.strip()} reference website variant {index + 1}: "
                    "a modern institutional five-page experience with dense cards and clear navigation"
                ),
                metadata={"difficulty": "medium"},
            )
            for index in range(count)
        ]
        return DatasetPlan(
            dataset_size=count,
            global_constraints={"minimum_pages_per_site": 5},
            data_plan={"difficulty_mix": {"medium": count}},
            site_seeds=seeds,
        )

    def _seed_id(self, prompt: str) -> str:
        match = re.search(r'"id"\s*:\s*"([^"]+)"', prompt)
        return match.group(1) if match else "site-001"

    def _default_concept(self, seed_id: str) -> ConceptCandidate:
        pages = [
            PageSpec(id="home", path="index.html", layout_pattern="hero, impact metrics, audience cards", sections=["hero", "metrics", "audiences"]),
            PageSpec(id="governments", path="governments.html", layout_pattern="policy hero, program grid, proof points", sections=["hero", "programs", "outcomes"]),
            PageSpec(id="schools", path="schools.html", layout_pattern="school hero, classroom cards, implementation timeline", sections=["hero", "cards", "timeline"]),
            PageSpec(id="enterprises", path="enterprises.html", layout_pattern="enterprise hero, workforce panels, results", sections=["hero", "panels", "results"]),
            PageSpec(id="contact", path="contact.html", layout_pattern="contact hero, address block, form", sections=["hero", "address", "form"]),
        ]
        return ConceptCandidate(
            candidate_id="concept-1",
            domain="education",
            site_goal="Present a polished education organization reference site.",
            audience=["school administrators", "program leads"],
            description="A compact education landing page with clear navigation and visible controls.",
            motif="warm institutional layout with strong highlight bands and cards",
            pages=pages,
            message_intent=["Communicate trust", "Communicate measurable impact"],
            required_text=["Contact Us", "Work", "Learning programs"],
            content_model=["hero copy", "feature cards", "contact form"],
            interactions=["nav hover", "email focus"],
            asset_needs=["simple inline SVG motif"],
            mobile_behavior="single-column mobile layout with no horizontal overflow",
            difficulty="medium",
        )

    def _concept_batch(self, prompt: str) -> ConceptBatch:
        seed_id = self._seed_id(prompt)
        self._concept_calls += 1
        concepts = []
        for index in range(2):
            concept = self._default_concept(seed_id)
            concept.candidate_id = f"concept-{index + 1}"
            concept.description = f"{concept.description} Candidate {index + 1}."
            concepts.append(concept)
        self.last_concept = concepts[0]
        return ConceptBatch(seed_id=seed_id, concepts=concepts)

    def _critique(self) -> ConceptCritique:
        if self._concept_calls <= self.concept_reject_rounds:
            return ConceptCritique(
                candidates=[
                    CriticCandidateScore(
                        candidate_id="concept-1",
                        score=0.2,
                        accept=False,
                        weaknesses=["too generic"],
                    )
                ],
                regenerate=True,
                feedback_for_regeneration=["Make the motif and interaction states more concrete."],
            )
        return ConceptCritique(
            candidates=[
                CriticCandidateScore(
                    candidate_id="concept-1",
                    score=0.88,
                    accept=True,
                    strengths=["clear structure", "good interaction states"],
                )
            ],
            best_candidate_id="concept-1",
            regenerate=False,
        )

    async def build_site(
        self,
        *,
        agent_name: str,
        site_id: str,
        system_prompt: str,
        user_prompt: str,
        site_dir: str | Path,
    ) -> BuildReport:
        del agent_name, system_prompt, user_prompt
        concept = self.last_concept or self._default_concept("site-001")
        root = Path(site_dir)
        root.mkdir(parents=True, exist_ok=True)
        css = """:root { color: #26312f; background: #fffaf0; font-family: Inter, Arial, sans-serif; }
body { margin: 0; }
.site-header { display: flex; justify-content: space-between; align-items: center; padding: 18px 48px; background: #ffffff; border-bottom: 1px solid #d8e0d7; position: sticky; top: 0; z-index: 2; }
.brand { font-weight: 800; color: #26312f; text-decoration: none; }
nav { display: flex; gap: 22px; align-items: center; }
nav a, button { color: #26312f; font: inherit; }
button { background: #f2c14e; border: 1px solid #b78c1b; border-radius: 6px; padding: 8px 12px; }
.dropdown { position: relative; }
.menu { display: none; position: absolute; top: 100%; right: 0; min-width: 190px; background: white; border: 1px solid #d8e0d7; box-shadow: 0 12px 28px rgba(38, 49, 47, 0.14); }
.dropdown:hover .menu { display: grid; }
.menu a { padding: 10px 12px; text-decoration: none; }
.hero { padding: 96px 48px; background: linear-gradient(120deg, #fff1bd, #d9efe6); }
.eyebrow { text-transform: uppercase; letter-spacing: 0.08em; font-size: 0.82rem; }
h1 { max-width: 760px; font-size: 52px; line-height: 1.02; margin: 0 0 20px; }
.button { display: inline-block; margin-top: 18px; padding: 12px 16px; background: #26312f; color: white; text-decoration: none; border-radius: 6px; }
.cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px; padding: 48px; }
article, .contact, .panel { background: white; border: 1px solid #d8e0d7; border-radius: 8px; padding: 24px; }
.contact { margin: 0 48px 64px; }
input { display: block; margin-top: 8px; padding: 10px; border: 2px solid #b7c8bd; border-radius: 6px; }
input:focus { outline: 3px solid #f2c14e; border-color: #26312f; }
@media (max-width: 700px) {
  .site-header, nav { align-items: flex-start; flex-direction: column; }
  .site-header, .hero, .cards { padding: 24px; }
  h1 { font-size: 36px; }
  .cards { grid-template-columns: 1fr; }
  .contact { margin: 0 24px 40px; }
}
"""
        (root / "styles.css").write_text(css, encoding="utf-8")
        for page in concept.pages:
            title = page.id.replace("-", " ").title()
            html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} | Learning programs</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <header class="site-header">
    <a class="brand" href="index.html">Learning programs</a>
    <nav>
      <div class="dropdown" data-capture="work-menu">
        <button aria-haspopup="true">Work</button>
        <div class="menu">
          <a href="schools.html">With schools</a>
          <a href="governments.html">With governments</a>
          <a href="enterprises.html">With enterprises</a>
        </div>
      </div>
      <a href="contact.html">Contact Us</a>
    </nav>
  </header>
  <main>
    <section class="hero">
      <p class="eyebrow">Evidence-led education</p>
      <h1>{title}: Learning programs for public and private institutions</h1>
      <p>{page.layout_pattern}. Trusted education teams use this reference site to communicate measurable impact.</p>
      <a class="button" href="contact.html">Contact Us</a>
    </section>
    <section class="cards" id="schools">
      <article><h2>For schools</h2><p>Implementation support and classroom tools.</p></article>
      <article><h2>For governments</h2><p>Policy-ready programs and progress reporting.</p></article>
      <article><h2>For enterprises</h2><p>Workforce learning and skills pathways.</p></article>
    </section>
    <section id="contact" class="contact">
      <label>Email <input name="email" type="email" placeholder="team@example.org"></label>
    </section>
  </main>
</body>
</html>
"""
            (root / page.path).write_text(html, encoding="utf-8")
        (root / "reference_spec.json").write_text(concept.model_dump_json(indent=2), encoding="utf-8")
        files = sorted(str(path.relative_to(root)).replace("\\", "/") for path in root.rglob("*") if path.is_file())
        return BuildReport(
            site_id=site_id,
            site_dir=str(root),
            files_written=files,
            summary="Generated a deterministic five-page fake site.",
            notes=["Generated by FakeRuntime."],
        )

    def _verifier_report(self) -> VerifierReport:
        self._verifier_calls += 1
        if self._verifier_calls <= self.verifier_repair_rounds:
            return VerifierReport(
                status="needs_repair",
                issues=[
                    RepairIssue(
                        type="missing_interaction",
                        message="The fake verifier requested one repair round.",
                    )
                ],
                scores={"contract": 0.6, "concept_fidelity": 0.7},
                repair_instructions=["Make the dropdown and contact input focus state visible."],
            )
        return VerifierReport(
            status="approved",
            issues=[],
            scores={"contract": 1.0, "concept_fidelity": 0.9, "render_quality": 1.0},
            deterministic_checks={},
        )
