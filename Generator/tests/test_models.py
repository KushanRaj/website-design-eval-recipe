from __future__ import annotations

import unittest

from pydantic import ValidationError

from Generator.models import (
    ConceptCandidate,
    ConceptCritique,
    CriticCandidateScore,
    DatasetPlan,
    PageSpec,
    SiteSeed,
)


class ModelTests(unittest.TestCase):
    def _pages(self) -> list[PageSpec]:
        return [
            PageSpec(id="home", path="index.html", layout_pattern="hero"),
            PageSpec(id="about", path="about.html", layout_pattern="story"),
            PageSpec(id="work", path="work.html", layout_pattern="cards"),
            PageSpec(id="careers", path="careers.html", layout_pattern="list"),
            PageSpec(id="contact", path="contact.html", layout_pattern="form"),
        ]

    def test_dataset_plan_size_must_match_seeds(self) -> None:
        with self.assertRaises(ValidationError):
            DatasetPlan(dataset_size=2, site_seeds=[SiteSeed(id="site-1", one_liner="One")])

    def test_critique_best_candidate_must_reference_candidate(self) -> None:
        with self.assertRaises(ValidationError):
            ConceptCritique(
                candidates=[CriticCandidateScore(candidate_id="a", score=0.5, accept=False)],
                best_candidate_id="missing",
            )

    def test_concept_candidate_minimal_valid(self) -> None:
        concept = ConceptCandidate(
            candidate_id="concept-1",
            domain="education",
            site_goal="Explain programs",
            description="Institutional education website",
            motif="warm highlights",
            pages=self._pages(),
        )
        self.assertEqual(concept.pages[0].path, "index.html")
        self.assertEqual(concept.difficulty, "medium")

    def test_concept_candidate_requires_at_least_five_pages(self) -> None:
        with self.assertRaises(ValidationError):
            ConceptCandidate(
                candidate_id="concept-1",
                domain="education",
                site_goal="Explain programs",
                description="Institutional education website",
                motif="warm highlights",
                pages=[PageSpec(id="home", path="index.html", layout_pattern="hero")],
            )


if __name__ == "__main__":
    unittest.main()
