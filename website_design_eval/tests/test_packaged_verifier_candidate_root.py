from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from scripts.package_harbor_task import _run_eval_py


def _generated_helper(name: str):
    namespace = {"__name__": "generated_run_eval_test"}
    exec(_run_eval_py(), namespace)
    return namespace[name]


def _restore_env(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


def _write_fake_npm(bin_dir: Path) -> Path:
    npm = bin_dir / "npm"
    npm.write_text(
        """#!/usr/bin/env bash
set -e
echo "$@" >> "$FAKE_NPM_LOG"
if [[ "$1" == "install" || "$1" == "ci" ]]; then
  exit 0
fi
if [[ "$1" == "run" && "$2" == "build" ]]; then
  mkdir -p dist
  printf '<!doctype html><div>built</div>' > dist/index.html
  exit 0
fi
exit 42
""",
        encoding="utf-8",
    )
    npm.chmod(0o755)
    return npm


class PackagedVerifierCandidateRootTests(unittest.TestCase):
    def test_react_missing_dist_runs_build_and_returns_dist(self) -> None:
        candidate_root = _generated_helper("_candidate_root")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            site = root / "site"
            logs = root / "logs"
            bin_dir = root / "bin"
            fake_npm_log = root / "fake-npm.log"
            site.mkdir()
            bin_dir.mkdir()
            _write_fake_npm(bin_dir)
            (site / "package.json").write_text('{"scripts":{"build":"vite build"}}', encoding="utf-8")

            old_site_root = os.environ.get("WDE_SITE_ROOT")
            old_path = os.environ.get("PATH")
            old_fake_npm_log = os.environ.get("FAKE_NPM_LOG")
            os.environ["WDE_SITE_ROOT"] = str(site)
            os.environ["PATH"] = f"{bin_dir}{os.pathsep}{old_path or ''}"
            os.environ["FAKE_NPM_LOG"] = str(fake_npm_log)
            try:
                resolved = candidate_root(None, "react", "spa", logs)
            finally:
                _restore_env("WDE_SITE_ROOT", old_site_root)
                _restore_env("PATH", old_path)
                _restore_env("FAKE_NPM_LOG", old_fake_npm_log)

            self.assertEqual(resolved, (site / "dist").resolve())
            diagnostics = json.loads((logs / "candidate-prep-diagnostics.json").read_text())
            self.assertEqual(diagnostics["status"], "built")
            self.assertEqual(diagnostics["candidate_framework"], "react")
            self.assertTrue(diagnostics["dist_index_exists"])
            self.assertTrue(diagnostics["package_json_exists"])
            self.assertEqual(diagnostics["install"]["command"], ["npm", "install"])
            self.assertEqual(diagnostics["build"]["command"], ["npm", "run", "build"])
            self.assertTrue((logs / "candidate-build" / "npm-install.stdout.txt").exists())
            self.assertTrue((logs / "candidate-build" / "npm-run-build.stdout.txt").exists())
            self.assertEqual(fake_npm_log.read_text(encoding="utf-8").splitlines(), ["install", "run build"])

    def test_react_without_package_or_dist_fails_before_build(self) -> None:
        candidate_root = _generated_helper("_candidate_root")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            site = root / "site"
            logs = root / "logs"
            site.mkdir()

            old_site_root = os.environ.get("WDE_SITE_ROOT")
            os.environ["WDE_SITE_ROOT"] = str(site)
            try:
                with self.assertRaises(RuntimeError):
                    candidate_root(None, "react", "spa", logs)
            finally:
                _restore_env("WDE_SITE_ROOT", old_site_root)

            diagnostics = json.loads((logs / "candidate-prep-diagnostics.json").read_text())
            self.assertEqual(diagnostics["status"], "build_not_attempted")
            self.assertEqual(diagnostics["reason"], "package_json_missing")
            self.assertFalse(diagnostics["package_json_exists"])
            self.assertFalse(diagnostics["dist_index_exists"])

    def test_explicit_candidate_root_is_returned(self) -> None:
        candidate_root = _generated_helper("_candidate_root")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            explicit = root / "candidate"
            logs = root / "logs"
            explicit.mkdir()

            resolved = candidate_root(str(explicit), "react", "spa", logs)

            self.assertEqual(resolved, explicit.resolve())
            diagnostics = json.loads((logs / "candidate-prep-diagnostics.json").read_text())
            self.assertEqual(diagnostics["status"], "explicit_candidate_root")


if __name__ == "__main__":
    unittest.main()
