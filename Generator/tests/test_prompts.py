from __future__ import annotations

import unittest

from Generator.models import GenerationRequest
from Generator.prompts import orchestrator_prompt


class PromptTests(unittest.TestCase):
    def test_orchestrator_prompt_contains_seed_line_contract(self) -> None:
        prompt = orchestrator_prompt(GenerationRequest(count=2, prompt="generate websites"))
        self.assertIn("website type/domain", prompt)
        self.assertIn("visual feel", prompt)
        self.assertIn("information", prompt)
        self.assertIn("five-plus-page", prompt)
        self.assertIn("Do not copy these examples verbatim", prompt)

    def test_orchestrator_prompt_contains_distinct_example_archetypes(self) -> None:
        prompt = orchestrator_prompt(GenerationRequest(count=2, prompt="generate websites"))
        self.assertIn("Government services portal", prompt)
        self.assertIn("Sleek tech product site", prompt)
        self.assertIn("Luxury hospitality group", prompt)
        self.assertIn("University department site", prompt)
        self.assertIn("Financial analytics platform", prompt)
        self.assertIn("Arts festival or museum site", prompt)


if __name__ == "__main__":
    unittest.main()
