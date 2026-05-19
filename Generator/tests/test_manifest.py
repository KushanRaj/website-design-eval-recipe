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

    async def test_manifest_replay_prunes_failed_optional_captures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.html").write_text(
                """
                <!doctype html>
                <html>
                  <body>
                    <main><h1>Replay pruning fixture</h1></main>
                    <button id="offscreen" style="position:fixed;bottom:0;right:0;transform:translateY(100%);">
                      Dismiss
                    </button>
                  </body>
                </html>
                """,
                encoding="utf-8",
            )
            captures = [
                {
                    "id": f"full-{index}",
                    "path": "/index.html",
                    "viewport": {"width": 800, "height": 600},
                    "actions": [],
                    "screenshot": {"fullPage": False},
                }
                for index in range(5)
            ]
            captures.append(
                {
                    "id": "bad-dismiss-state",
                    "path": "/index.html",
                    "viewport": {"width": 800, "height": 600},
                    "actions": [
                        {"type": "click", "selector": "#offscreen", "timeoutMs": 100},
                    ],
                    "screenshot": {"fullPage": False},
                }
            )
            manifest_path = root / "screenshot-manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "site": {"name": "fixture", "root": "."},
                        "outputDir": "./screenshots/reference",
                        "cleanOutputDir": True,
                        "defaults": {
                            "viewport": {"width": 800, "height": 600},
                            "deviceScaleFactor": 1,
                            "waitUntil": "load",
                            "timeoutMs": 30000,
                            "actionTimeoutMs": 100,
                            "screenshot": {"fullPage": False},
                        },
                        "captures": captures,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            completed = run_manifest_capture(
                manifest_path,
                prune_failed=True,
                timeout_seconds=30,
            )

            self.assertEqual(completed.returncode, 0)
            pruned = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertNotIn(
                "bad-dismiss-state",
                {capture["id"] for capture in pruned["captures"]},
            )
            self.assertEqual(len(pruned["captures"]), 5)
            report = json.loads(
                (root / "screenshots" / "reference" / "_replay-report.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(report["droppedCaptures"], ["bad-dismiss-state"])


if __name__ == "__main__":
    unittest.main()
