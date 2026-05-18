from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Generator.fake_runtime import FakeRuntime
from Generator.models import GenerationRequest
from Generator.pipeline import GeneratorPipeline, PipelineError


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_pipeline_with_fake_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            request = GenerationRequest(
                count=1,
                prompt="Education landing page",
                output_root=tmp,
                replay_manifest=False,
            )
            pipeline = GeneratorPipeline(FakeRuntime(), output_root=tmp)
            result = await pipeline.generate(request)
            self.assertEqual(len(result.packages), 1)
            package = result.packages[0]
            self.assertTrue((Path(package.website_path) / "index.html").exists())
            self.assertTrue(Path(package.screenshot_manifest_path).exists())

    async def test_concept_regeneration_then_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            request = GenerationRequest(
                count=1,
                prompt="Education landing page",
                output_root=tmp,
                max_concept_rounds=2,
                replay_manifest=False,
            )
            pipeline = GeneratorPipeline(FakeRuntime(concept_reject_rounds=1), output_root=tmp)
            result = await pipeline.generate(request)
            self.assertEqual(result.packages[0].accepted_concept.candidate_id, "concept-1")

    async def test_concept_retry_exhaustion_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            request = GenerationRequest(
                count=1,
                prompt="Education landing page",
                output_root=tmp,
                max_concept_rounds=1,
                replay_manifest=False,
            )
            pipeline = GeneratorPipeline(FakeRuntime(concept_reject_rounds=2), output_root=tmp)
            with self.assertRaises(PipelineError):
                await pipeline.generate(request)

    async def test_verifier_repair_then_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            request = GenerationRequest(
                count=1,
                prompt="Education landing page",
                output_root=tmp,
                max_builder_repair_rounds=1,
                replay_manifest=False,
            )
            pipeline = GeneratorPipeline(FakeRuntime(verifier_repair_rounds=1), output_root=tmp)
            result = await pipeline.generate(request)
            self.assertEqual(result.packages[0].verifier_report.status, "approved")


if __name__ == "__main__":
    unittest.main()
