from __future__ import annotations

from pathlib import Path

from . import prompts
from .io import list_site_files, write_json
from .manifest import run_manifest_capture, write_manifest
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
from .runtime import AgentRuntime
from .verification import deterministic_verify, verifier_report_from_deterministic


class PipelineError(RuntimeError):
    pass


class GeneratorPipeline:
    def __init__(
        self,
        runtime: AgentRuntime,
        *,
        output_root: str | Path = "Generator/output",
        repo_root: str | Path | None = None,
        run_browser_checks: bool = False,
    ) -> None:
        self.runtime = runtime
        self.output_root = Path(output_root)
        self.repo_root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[1]
        self.run_browser_checks = run_browser_checks

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
            batch = await self.runtime.run_json(
                agent_name="concept",
                system_prompt=prompts.CONCEPT_SYSTEM,
                user_prompt=prompts.concept_prompt(seed, request, feedback),
                output_model=ConceptBatch,
            )
            latest_batch = batch
            write_json(self.output_root / seed.id / f"concept-batch-round-{round_index + 1}.json", batch)

            critique = await self.runtime.run_json(
                agent_name="concept_critic",
                system_prompt=prompts.CRITIC_SYSTEM,
                user_prompt=prompts.critic_prompt(seed, batch),
                output_model=ConceptCritique,
            )
            latest_critique = critique
            write_json(self.output_root / seed.id / f"critic-round-{round_index + 1}.json", critique)

            if not critique.regenerate and critique.best_candidate_id:
                accepted_ids = {
                    candidate.candidate_id
                    for candidate in critique.candidates
                    if candidate.accept
                }
                if critique.best_candidate_id in accepted_ids:
                    concept = self._find_concept(batch, critique.best_candidate_id)
                    write_json(self.output_root / seed.id / "accepted-concept.json", concept)
                    return concept, critique
            feedback = critique.feedback_for_regeneration or ["No concept passed the critic."]

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

        for attempt in range(request.max_builder_repair_rounds + 1):
            build_report = await self.runtime.build_site(
                agent_name="website_builder" if attempt == 0 else "website_builder_repair",
                site_id=seed.id,
                system_prompt=prompts.BUILDER_SYSTEM,
                user_prompt=prompts.builder_prompt(seed, concept, repair_feedback, previous_report),
                site_dir=site_dir,
            )
            write_json(self.output_root / seed.id / f"build-report-attempt-{attempt + 1}.json", build_report)

            deterministic_report = deterministic_verify(
                site_dir,
                concept,
                run_browser_checks=self.run_browser_checks,
            )
            write_json(self.output_root / seed.id / f"deterministic-report-attempt-{attempt + 1}.json", deterministic_report)

            if not deterministic_report.passed:
                verifier_report = verifier_report_from_deterministic(deterministic_report)
            else:
                verifier_report = await self.runtime.run_json(
                    agent_name="verifier",
                    system_prompt=prompts.VERIFIER_SYSTEM,
                    user_prompt=prompts.verifier_prompt(
                        seed,
                        concept,
                        deterministic_report,
                        list_site_files(site_dir),
                    ),
                    output_model=VerifierReport,
                )
                if not verifier_report.deterministic_checks:
                    verifier_report.deterministic_checks = deterministic_report.model_dump()

            previous_report = verifier_report
            write_json(self.output_root / seed.id / f"verifier-report-attempt-{attempt + 1}.json", verifier_report)

            if verifier_report.status == "approved":
                manifest = await self.runtime.run_json(
                    agent_name="manifest",
                    system_prompt=prompts.MANIFEST_SYSTEM,
                    user_prompt=prompts.manifest_prompt(concept, verifier_report, list_site_files(site_dir)),
                    output_model=ScreenshotManifest,
                )
                manifest_path = write_manifest(site_dir, manifest)
                if request.replay_manifest:
                    run_manifest_capture(manifest_path, repo_root=self.repo_root)
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
        plan = await self.create_plan(request)
        write_json(self.output_root / "dataset-plan.json", plan)

        packages: list[AcceptedWebsitePackage] = []
        for seed in plan.site_seeds:
            write_json(self.output_root / seed.id / "seed.json", seed)
            concept, critique = await self.create_concept(seed, request)
            package = await self.build_verify_manifest(seed, concept, critique, request)
            packages.append(package)

        result = GenerationResult(request=request, dataset_plan=plan, packages=packages)
        write_json(self.output_root / "generation-result.json", result)
        return result

    @staticmethod
    def _find_concept(batch: ConceptBatch, candidate_id: str) -> ConceptCandidate:
        for concept in batch.concepts:
            if concept.candidate_id == candidate_id:
                return concept
        raise PipelineError(f"Critic selected missing candidate_id: {candidate_id}")
