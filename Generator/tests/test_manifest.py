from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from Generator.fake_runtime import FakeRuntime
from Generator.manifest import run_manifest_capture
from Generator.models import GenerationRequest
from Generator.pipeline import GeneratorPipeline


class ManifestSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_fake_site_manifest_replays_with_existing_capture_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            request = GenerationRequest(
                count=1,
                prompt="Education landing page",
                output_root=tmp,
                replay_manifest=False,
            )
            pipeline = GeneratorPipeline(FakeRuntime(), output_root=tmp)
            result = await pipeline.generate(request)
            manifest_path = Path(result.packages[0].screenshot_manifest_path)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertTrue(any(capture.get("actions") for capture in manifest["captures"]))
            self.assertTrue(any(capture.get("intent") for capture in manifest["captures"]))
            completed = run_manifest_capture(manifest_path)
            self.assertEqual(completed.returncode, 0)
            screenshot_dir = manifest_path.parent / "screenshots" / "reference"
            self.assertTrue((screenshot_dir / "home.desktop.full.png").exists())


if __name__ == "__main__":
    unittest.main()
