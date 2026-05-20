from __future__ import annotations

import unittest

from scripts.package_harbor_task import _instruction_md, _serve_mode_for_framework, _task_toml


class HarborFrameworkPackagingTests(unittest.TestCase):
    def test_react_instruction_requests_buildable_production_site(self) -> None:
        instruction = _instruction_md(has_animations=False, candidate_framework="react")

        self.assertIn("/app/site/dist/", instruction)
        self.assertIn("Vite app entry", instruction)
        self.assertIn("npm run build", instruction)
        self.assertIn("without `npm run dev`", instruction)
        self.assertNotIn("evaluator", instruction.lower())

    def test_html_instruction_keeps_static_entrypoint(self) -> None:
        instruction = _instruction_md(has_animations=False, candidate_framework="html")

        self.assertIn("/app/site/index.html", instruction)
        self.assertIn("separate HTML files", instruction)
        self.assertNotIn("/app/site/dist/index.html", instruction)

    def test_task_toml_records_framework_and_serve_mode(self) -> None:
        task_toml = _task_toml(
            "proximal/example",
            has_animations=False,
            animation_count=0,
            candidate_framework="solid",
        )

        self.assertIn('candidate_framework = "solid"', task_toml)
        self.assertIn('serve_mode = "spa"', task_toml)
        self.assertEqual(_serve_mode_for_framework("html"), "static")
        self.assertEqual(_serve_mode_for_framework("react"), "spa")


if __name__ == "__main__":
    unittest.main()
