from __future__ import annotations

import asyncio
import contextlib
import logging
import subprocess
import time
from pathlib import Path

from . import prompts
from .io import list_site_files, write_json
from .manifest import generate_oracle_manifest, manifest_from_browser_inventory, run_manifest_capture, write_manifest
from .models import (
    AcceptedWebsitePackage,
    ConceptBatch,
    ConceptCandidate,
    ConceptCritique,
    DatasetPlan,
    GenerationRequest,
    GenerationResult,
    ScreenshotManifest,
    SiteSeed,
    VerifierReport,
)
from .runtime import ACCOUNTING, AgentRuntime
from .verification import deterministic_verify, verifier_report_from_deterministic

logger = logging.getLogger("Generator.pipeline")


@contextlib.contextmanager
def _stage(seed_id: str, stage: str, **fields):
    """Log a per-seed pipeline stage boundary. Failures inside the stage are
    surfaced where they happen (not deferred to whoever catches them upstream)."""

    started = time.monotonic()
    detail = " ".join(f"{k}={v}" for k, v in fields.items())
    logger.info("seed=%s stage=%s START %s", seed_id, stage, detail)
    try:
        yield
    except BaseException as exc:
        elapsed = time.monotonic() - started
        logger.exception(
            "seed=%s stage=%s FAILED elapsed=%.0fs %s: %s",
            seed_id,
            stage,
            elapsed,
            type(exc).__name__,
            exc,
        )
        raise
    elapsed = time.monotonic() - started
    logger.info("seed=%s stage=%s DONE elapsed=%.0fs %s", seed_id, stage, elapsed, detail)


class PipelineError(RuntimeError):
    pass


class GeneratorPipeline:
    def __init__(
        self,
        runtime: AgentRuntime,
        *,
        output_root: str | Path = "Generator/output",
        repo_root: str | Path | None = None,
        run_browser_checks: bool = True,
        use_llm_manifest: bool | None = None,
    ) -> None:
        self.runtime = runtime
        self.output_root = Path(output_root)
        self.repo_root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[1]
        self.run_browser_checks = run_browser_checks
        self.use_llm_manifest = use_llm_manifest if use_llm_manifest is not None else runtime.__class__.__name__ != "FakeRuntime"

    async def create_plan(self, request: GenerationRequest) -> DatasetPlan:
        return await self.runtime.run_json(
            agent_name="orchestrator",
            system_prompt=prompts.ORCHESTRATOR_SYSTEM,
            user_prompt=prompts.orchestrator_prompt(request),
            output_model=DatasetPlan,
        )

    async def create_concept(self, seed: SiteSeed, request: GenerationRequest) -> tuple[ConceptCandidate, ConceptCritique]:
        feedback: list[str] = []
        latest_critique: ConceptCritique | None = None
        latest_batch: ConceptBatch | None = None

        for round_index in range(request.max_concept_rounds):
            round_no = round_index + 1
            if round_no > 1:
                logger.info(
                    "seed=%s concept round=%d feedback=%s",
                    seed.id,
                    round_no,
                    feedback,
                )
            with _stage(seed.id, "concept", round=round_no):
                batch = await self.runtime.run_json(
                    agent_name="concept",
                    system_prompt=prompts.CONCEPT_SYSTEM,
                    user_prompt=prompts.concept_prompt(seed, request, feedback),
                    output_model=ConceptBatch,
                )
                latest_batch = batch
                write_json(self.output_root / seed.id / f"concept-batch-round-{round_no}.json", batch)

            with _stage(seed.id, "critic", round=round_no):
                critique = await self.runtime.run_json(
                    agent_name="concept_critic",
                    system_prompt=prompts.CRITIC_SYSTEM,
                    user_prompt=prompts.critic_prompt(seed, batch),
                    output_model=ConceptCritique,
                )
                latest_critique = critique
                write_json(self.output_root / seed.id / f"critic-round-{round_no}.json", critique)

            if not critique.regenerate and critique.best_candidate_id:
                accepted_ids = {
                    candidate.candidate_id
                    for candidate in critique.candidates
                    if candidate.accept
                }
                if critique.best_candidate_id in accepted_ids:
                    concept = self._find_concept(batch, critique.best_candidate_id)
                    write_json(self.output_root / seed.id / "accepted-concept.json", concept)
                    logger.info(
                        "seed=%s concept ACCEPTED candidate_id=%s round=%d",
                        seed.id,
                        critique.best_candidate_id,
                        round_no,
                    )
                    return concept, critique
            feedback = critique.feedback_for_regeneration or ["No concept passed the critic."]
            logger.info(
                "seed=%s concept REJECTED round=%d regenerate=%s feedback_items=%d",
                seed.id,
                round_no,
                critique.regenerate,
                len(feedback),
            )

        raise PipelineError(
            f"No acceptable concept for {seed.id} after {request.max_concept_rounds} rounds. "
            f"Last critique: {latest_critique}; last batch: {latest_batch}"
        )

    async def build_verify_manifest(
        self,
        seed: SiteSeed,
        concept: ConceptCandidate,
        critique: ConceptCritique,
        request: GenerationRequest,
    ) -> AcceptedWebsitePackage:
        site_dir = self.output_root / seed.id / "site"
        repair_feedback: list[str] = []
        previous_report: VerifierReport | None = None
        # Canonical manifest is generated on attempt 1 and reused across
        # repair attempts. The screenshots under site/screenshots/reference
        # are re-replayed on every attempt because the file content changes.
        manifest: ScreenshotManifest | None = None
        manifest_path: Path | None = None
        screenshots_dir = site_dir / "screenshots" / "reference"

        for attempt in range(request.max_builder_repair_rounds + 1):
            attempt_no = attempt + 1
            agent_name = "website_builder" if attempt == 0 else "website_builder_repair"
            with _stage(seed.id, "builder", attempt=attempt_no, agent=agent_name):
                build_report = await self.runtime.build_site(
                    agent_name=agent_name,
                    site_id=seed.id,
                    system_prompt=prompts.BUILDER_SYSTEM,
                    user_prompt=prompts.builder_prompt(seed, concept, repair_feedback, previous_report),
                    site_dir=site_dir,
                )
                write_json(self.output_root / seed.id / f"build-report-attempt-{attempt_no}.json", build_report)

            with _stage(seed.id, "validate_files", attempt=attempt_no):
                self._validate_written_files(site_dir)

            with _stage(seed.id, "deterministic_verify", attempt=attempt_no):
                # Playwright sync API can't run on the asyncio loop, so offload
                # the sync verification (and its browser screenshot capture) to a thread.
                deterministic_report = await asyncio.to_thread(
                    deterministic_verify,
                    site_dir,
                    concept,
                    run_browser_checks=self.run_browser_checks,
                )
                write_json(self.output_root / seed.id / f"deterministic-report-attempt-{attempt_no}.json", deterministic_report)
                logger.info(
                    "seed=%s deterministic passed=%s issue_count=%d error_count=%d",
                    seed.id,
                    deterministic_report.passed,
                    len(deterministic_report.issues),
                    sum(1 for i in deterministic_report.issues if i.severity == "error"),
                )

            # Deterministic is purely informational — it never gates. The
            # LLM verifier always runs and is the sole judge. (Hard physical
            # impossibilities like a missing site dir or no index.html are
            # already caught upstream by _validate_written_files, which
            # raises PipelineError before we reach this point.)
            if not deterministic_report.passed:
                logger.warning(
                    "seed=%s deterministic report passed=False but proceeding to LLM verifier anyway (issues=%d)",
                    seed.id,
                    len(deterministic_report.issues),
                )

            # Manifest is generated ONCE on the first attempt and reused.
            # The screenshots themselves get re-captured on every attempt
            # because the file content changes during repair.
            if manifest is None:
                with _stage(seed.id, "manifest", attempt=attempt_no):
                    manifest = await self._produce_manifest(seed, concept, None, site_dir)
                    manifest_path = write_manifest(site_dir, manifest)
                    logger.info(
                        "seed=%s manifest written to %s (captures=%d)",
                        seed.id,
                        manifest_path,
                        len(manifest.captures),
                    )

            if request.replay_manifest and manifest_path is not None:
                with _stage(seed.id, "replay_manifest", attempt=attempt_no):
                    manifest = self._replay_manifest_or_raise(seed, manifest_path)

            verifier_screenshots = self._select_verifier_screenshots(manifest, screenshots_dir)

            with _stage(seed.id, "verifier", attempt=attempt_no, images=len(verifier_screenshots)):
                verifier_report = await self.runtime.run_json(
                    agent_name="verifier",
                    system_prompt=prompts.VERIFIER_SYSTEM,
                    user_prompt=prompts.verifier_prompt(
                        seed,
                        concept,
                        deterministic_report,
                        list_site_files(site_dir),
                        attached_screenshots=[p.name for p in verifier_screenshots],
                    ),
                    output_model=VerifierReport,
                    image_paths=verifier_screenshots,
                )
                if not verifier_report.deterministic_checks:
                    verifier_report.deterministic_checks = deterministic_report.model_dump()

            previous_report = verifier_report
            write_json(self.output_root / seed.id / f"verifier-report-attempt-{attempt_no}.json", verifier_report)
            logger.info(
                "seed=%s verifier status=%s attempt=%d issues=%d",
                seed.id,
                verifier_report.status,
                attempt_no,
                len(verifier_report.issues),
            )

            if verifier_report.status == "approved":
                # Invariant: accepted-package.json must only be written after
                # the FINAL accepted DOM has a replayed manifest and frozen
                # screenshots on disk. If repair fired, the manifest/screenshots
                # we generated on attempt 1 are against a stale DOM — regenerate
                # against the final DOM and re-replay before packaging.
                if attempt_no > 1:
                    with _stage(seed.id, "manifest_revalidate", attempt=attempt_no):
                        logger.info(
                            "seed=%s repair fired (attempt=%d) — revalidating manifest against final DOM",
                            seed.id,
                            attempt_no,
                        )
                        # generate_oracle_manifest auto-reads the existing
                        # screenshot-manifest.json as 'existing_manifest_prior'
                        # and edits-not-regenerates against the final DOM.
                        manifest = await self._produce_manifest(seed, concept, verifier_report, site_dir)
                        manifest_path = write_manifest(site_dir, manifest)
                    if request.replay_manifest:
                        with _stage(seed.id, "replay_manifest_final", attempt=attempt_no):
                            manifest = self._replay_manifest_or_raise(seed, manifest_path)

                assert manifest_path is not None
                # Enforce the contract Harbor packaging relies on: every
                # enabled manifest capture must have a frozen PNG on disk.
                # We only enforce this when replay is actually expected to
                # have happened — when the user opted out of replay
                # (--no-replay / dry-run tests), we warn instead so they
                # know the resulting package is not Harbor-ready.
                if request.replay_manifest:
                    self._assert_manifest_screenshots_complete(manifest, screenshots_dir)
                else:
                    logger.warning(
                        "seed=%s replay_manifest=False — accepted package will have empty "
                        "screenshots dir; Harbor packaging will fail until you re-replay",
                        seed.id,
                    )

                package = AcceptedWebsitePackage(
                    site_id=seed.id,
                    concept_seed=seed,
                    accepted_concept=concept,
                    critic_report=critique,
                    website_path=str(site_dir),
                    verifier_report=verifier_report,
                    screenshot_manifest_path=str(manifest_path),
                    reference_screenshots_dir=str(site_dir / "screenshots" / "reference"),
                )
                write_json(self.output_root / seed.id / "accepted-package.json", package)
                return package

            repair_feedback = verifier_report.repair_instructions or [
                issue.message for issue in verifier_report.issues
            ]

        raise PipelineError(
            f"Site {seed.id} did not pass verification after "
            f"{request.max_builder_repair_rounds + 1} build attempts."
        )

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self.output_root = Path(request.output_root)
        self.output_root.mkdir(parents=True, exist_ok=True)
        run_started_at = time.monotonic()
        plan = await self.create_plan(request)
        write_json(self.output_root / "dataset-plan.json", plan)
        logger.info(
            "generate START seeds=%d max_parallel_sites=%d running_cost=$%.4f",
            len(plan.site_seeds),
            request.max_parallel_sites,
            ACCOUNTING.total_cost_usd,
        )

        # Orchestrator is serial (one dataset plan). Each seed's loop
        # (concept→critic→builder→verifier→manifest) runs concurrently,
        # bounded by max_parallel_sites so we don't fan out Chromium /
        # Claude sessions past what the host can handle.
        semaphore = asyncio.Semaphore(request.max_parallel_sites)
        failures: list[tuple[str, BaseException]] = []

        async def _run_seed(seed: SiteSeed) -> AcceptedWebsitePackage | None:
            async with semaphore:
                seed_start = time.monotonic()
                logger.info("seed=%s START parallel pipeline", seed.id)
                write_json(self.output_root / seed.id / "seed.json", seed)
                try:
                    concept, critique = await self.create_concept(seed, request)
                    package = await self.build_verify_manifest(
                        seed, concept, critique, request
                    )
                except BaseException as exc:
                    # Log immediately — do not wait for asyncio.gather to resolve,
                    # otherwise a fast-failing seed sits invisible while a slow
                    # sibling runs for tens of minutes.
                    elapsed = time.monotonic() - seed_start
                    logger.exception(
                        "seed=%s FAILED after %.0fs: %s: %s",
                        seed.id,
                        elapsed,
                        type(exc).__name__,
                        exc,
                    )
                    failures.append((seed.id, exc))
                    return None
                elapsed = time.monotonic() - seed_start
                logger.info(
                    "seed=%s DONE parallel pipeline elapsed=%.0fs running_cost=$%.2f",
                    seed.id,
                    elapsed,
                    ACCOUNTING.total_cost_usd,
                )
                return package

        # gather without return_exceptions: every exception is captured inside
        # _run_seed and returned as None, so gather always resolves cleanly.
        results = await asyncio.gather(*(_run_seed(seed) for seed in plan.site_seeds))
        packages = [result for result in results if result is not None]

        partial_result = GenerationResult(
            request=request, dataset_plan=plan, packages=packages
        )
        write_json(self.output_root / "generation-result.json", partial_result)

        elapsed = time.monotonic() - run_started_at
        logger.info(
            "generate DONE seeds=%d succeeded=%d failed=%d elapsed=%.0fs total_cost=$%.2f per_agent=%s",
            len(plan.site_seeds),
            len(packages),
            len(failures),
            elapsed,
            ACCOUNTING.total_cost_usd,
            ACCOUNTING.per_agent_cost,
        )

        if failures and not packages:
            # Everything failed — surface the first exception so the user sees a stack.
            raise failures[0][1]
        if failures:
            logger.warning(
                "generation finished with partial failure: failed_seeds=%s",
                [seed_id for seed_id, _ in failures],
            )
        return partial_result

    def _assert_manifest_screenshots_complete(
        self,
        manifest: ScreenshotManifest,
        screenshots_dir: Path,
    ) -> None:
        """Invariant: every enabled capture in the canonical manifest must have
        a frozen PNG on disk. This is the contract Harbor packaging relies on
        (it only copies — never regenerates). If this assertion fails,
        accepted-package.json must NOT be written; the seed is incomplete.
        """

        missing: list[str] = []
        for capture in manifest.captures:
            if not capture.enabled:
                continue
            png = screenshots_dir / f"{capture.id}.png"
            if not png.exists():
                missing.append(capture.id)
        if missing:
            raise PipelineError(
                f"Manifest is missing frozen PNGs for {len(missing)} enabled captures: {missing}. "
                f"Harbor packaging only copies — never regenerates — screenshots, so this seed "
                f"cannot be packaged. Replay the manifest at {screenshots_dir.parent.parent} / "
                f"screenshot-manifest.json or mark those captures enabled=false before retrying."
            )
        logger.info(
            "manifest screenshots complete: %d enabled captures all present under %s",
            sum(1 for c in manifest.captures if c.enabled),
            screenshots_dir,
        )

    def _select_verifier_screenshots(
        self,
        manifest: ScreenshotManifest,
        screenshots_dir: Path,
    ) -> list[Path]:
        """Pick which manifest screenshots to attach to the verifier prompt.

        One screenshot per declared page — the highest-weight capture for
        that page. No artificial ceiling: if the concept declared 12 pages,
        the verifier gets 12 images. Hover/focus/scroll-detail captures are
        still skipped (they're for the eventual grader, not the judge).
        """

        if not screenshots_dir.exists():
            return []

        # Sort captures by weight descending so we prefer high-signal frames.
        captures = sorted(
            (c for c in manifest.captures if c.enabled),
            key=lambda c: (c.weight or 0.0, c.page or ""),
            reverse=True,
        )

        seen_pages: set[str] = set()
        selected: list[Path] = []
        for capture in captures:
            page_key = capture.page or capture.id
            if page_key in seen_pages:
                continue
            png = screenshots_dir / f"{capture.id}.png"
            if not png.exists():
                logger.debug("manifest capture %s has no PNG at %s — skipping for verifier", capture.id, png)
                continue
            selected.append(png)
            seen_pages.add(page_key)

        logger.info(
            "verifier screenshots selected: %d (from %d manifest captures)",
            len(selected),
            len(manifest.captures),
        )
        return selected

    @staticmethod
    def _find_concept(batch: ConceptBatch, candidate_id: str) -> ConceptCandidate:
        for concept in batch.concepts:
            if concept.candidate_id == candidate_id:
                return concept
        raise PipelineError(f"Critic selected missing candidate_id: {candidate_id}")

    def _validate_written_files(self, site_dir: Path) -> None:
        """Cheap path-hygiene sanity over what the builder agent wrote."""

        from .io import SitePathError, normalize_bundle_path

        files = list_site_files(site_dir)
        logger.info("validating site_dir=%s files=%d", site_dir, len(files))
        if not files:
            raise PipelineError(f"Builder produced no files in {site_dir}")
        if "index.html" not in files:
            raise PipelineError(
                f"Builder did not produce index.html in {site_dir}. Files present: {files}"
            )
        bad: list[str] = []
        for relative in files:
            if relative.startswith("screenshots/"):
                continue
            try:
                normalize_bundle_path(relative)
            except SitePathError as exc:
                bad.append(f"{relative}: {exc}")
        if bad:
            raise PipelineError(
                "Builder wrote files with disallowed paths or types:\n  " + "\n  ".join(bad)
            )
        logger.info("validation OK files=%d index_html=present", len(files))

    async def _produce_manifest(
        self,
        seed: SiteSeed,
        concept: ConceptCandidate,
        verifier_report: VerifierReport | None,
        site_dir: Path,
    ) -> ScreenshotManifest:
        if not self.use_llm_manifest:
            return await asyncio.to_thread(
                manifest_from_browser_inventory,
                site_dir,
                site_name=seed.id,
            )
        return await asyncio.to_thread(
            generate_oracle_manifest,
            site_dir,
            site_name=seed.id,
            concept=concept,
            verifier_report=verifier_report,
            model="opus",
            repo_root=self.repo_root,
            allow_fallback=True,
        )

    def _replay_manifest_or_raise(self, seed: SiteSeed, manifest_path: Path) -> ScreenshotManifest:
        logger.info("replaying manifest %s", manifest_path)
        try:
            completed = run_manifest_capture(
                manifest_path,
                repo_root=self.repo_root,
                prune_failed=True,
            )
        except subprocess.CalledProcessError as exc:
            raise PipelineError(
                f"Manifest replay failed for {seed.id} ({manifest_path}):\n"
                f"stdout:\n{exc.stdout}\nstderr:\n{exc.stderr}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise PipelineError(
                f"Manifest replay timed out for {seed.id} ({manifest_path})"
            ) from exc
        except FileNotFoundError as exc:
            raise PipelineError(f"capture-screenshots.mjs not found: {exc}") from exc
        try:
            updated_manifest = ScreenshotManifest.model_validate_json(
                manifest_path.read_text(encoding="utf-8")
            )
        except Exception as exc:
            raise PipelineError(
                f"Manifest replay completed but produced an invalid manifest for {seed.id}: {manifest_path}"
            ) from exc
        logger.info(
            "manifest replay for %s ok (stdout %d chars, captures=%d)",
            seed.id,
            len(completed.stdout or ""),
            len(updated_manifest.captures),
        )
        return updated_manifest
