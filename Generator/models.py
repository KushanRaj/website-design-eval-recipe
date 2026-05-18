from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GenerationRequest(StrictModel):
    count: int = Field(default=1, ge=1, le=500)
    prompt: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    output_root: str = "Generator/output"
    max_concept_rounds: int = Field(default=2, ge=1, le=10)
    max_builder_repair_rounds: int = Field(default=2, ge=0, le=10)
    replay_manifest: bool = True
    model: str | None = None

    @field_validator("output_root")
    @classmethod
    def output_root_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("output_root cannot be empty")
        return value


class SiteSeed(StrictModel):
    id: str = Field(min_length=1)
    one_liner: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DatasetPlan(StrictModel):
    dataset_size: int = Field(ge=1)
    global_constraints: dict[str, Any] = Field(default_factory=dict)
    data_plan: dict[str, Any] = Field(default_factory=dict)
    site_seeds: list[SiteSeed] = Field(min_length=1)

    @model_validator(mode="after")
    def dataset_size_matches_seed_count(self) -> "DatasetPlan":
        if self.dataset_size != len(self.site_seeds):
            raise ValueError("dataset_size must match number of site_seeds")
        return self


class PageSpec(StrictModel):
    id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    layout_pattern: str = Field(min_length=1)
    sections: list[str] = Field(default_factory=list)


class ConceptCandidate(StrictModel):
    candidate_id: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    site_goal: str = Field(min_length=1)
    audience: list[str] = Field(default_factory=list)
    description: str = Field(min_length=1)
    motif: str = Field(min_length=1)
    pages: list[PageSpec] = Field(min_length=5)
    message_intent: list[str] = Field(default_factory=list)
    required_text: list[str] = Field(default_factory=list)
    content_model: list[str] = Field(default_factory=list)
    interactions: list[str] = Field(default_factory=list)
    asset_needs: list[str] = Field(default_factory=list)
    mobile_behavior: str = "responsive single-column mobile layout"
    difficulty: Literal["easy", "medium", "hard"] = "medium"


class ConceptBatch(StrictModel):
    seed_id: str = Field(min_length=1)
    concepts: list[ConceptCandidate] = Field(min_length=1, max_length=10)


class CriticCandidateScore(StrictModel):
    candidate_id: str = Field(min_length=1)
    score: float = Field(ge=0.0, le=1.0)
    accept: bool
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)


class ConceptCritique(StrictModel):
    candidates: list[CriticCandidateScore] = Field(min_length=1)
    best_candidate_id: str | None = None
    regenerate: bool = False
    feedback_for_regeneration: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def best_candidate_must_exist(self) -> "ConceptCritique":
        if self.best_candidate_id is None:
            return self
        ids = {candidate.candidate_id for candidate in self.candidates}
        if self.best_candidate_id not in ids:
            raise ValueError("best_candidate_id must reference a scored candidate")
        return self


class WebsiteFile(StrictModel):
    path: str = Field(min_length=1)
    content: str
    kind: Literal["html", "css", "js", "json", "svg", "txt", "md"] | None = None


class AssetSpec(StrictModel):
    id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    role: str = Field(min_length=1)


class WebsiteBundle(StrictModel):
    site_id: str = Field(min_length=1)
    files: list[WebsiteFile] = Field(min_length=1)
    assets: list[AssetSpec] = Field(default_factory=list)
    reference_spec: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class BuildReport(StrictModel):
    site_id: str = Field(min_length=1)
    site_dir: str = Field(min_length=1)
    files_written: list[str] = Field(default_factory=list)
    summary: str = ""
    notes: list[str] = Field(default_factory=list)


class RepairIssue(StrictModel):
    type: str = Field(min_length=1)
    message: str = Field(min_length=1)
    severity: Literal["info", "warning", "error"] = "error"
    path: str | None = None


class DeterministicCheckReport(StrictModel):
    passed: bool
    issues: list[RepairIssue] = Field(default_factory=list)
    checks: dict[str, Any] = Field(default_factory=dict)


class VerifierReport(StrictModel):
    status: Literal["approved", "needs_repair", "rejected"]
    issues: list[RepairIssue] = Field(default_factory=list)
    scores: dict[str, float] = Field(default_factory=dict)
    repair_instructions: list[str] = Field(default_factory=list)
    deterministic_checks: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def non_approved_reports_need_issue_context(self) -> "VerifierReport":
        if self.status != "approved" and not self.issues and not self.repair_instructions:
            raise ValueError("non-approved verifier reports need issues or repair_instructions")
        return self


class CaptureAction(StrictModel):
    type: str = Field(min_length=1)
    selector: str | None = None
    value: str | None = None
    key: str | None = None
    ms: int | None = Field(default=None, ge=0)
    settleMs: int | None = Field(default=None, ge=0)
    state: str | None = None
    timeoutMs: int | None = Field(default=None, ge=0)
    x: int | None = None
    y: int | None = None


class CaptureSpec(StrictModel):
    id: str = Field(min_length=1)
    page: str | None = None
    state: str | None = None
    path: str = Field(min_length=1)
    viewport: dict[str, int] = Field(default_factory=lambda: {"width": 1440, "height": 900})
    actions: list[CaptureAction] = Field(default_factory=list)
    screenshot: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class ScreenshotManifest(StrictModel):
    schemaVersion: int = 1
    site: dict[str, Any] = Field(default_factory=dict)
    outputDir: str = "./screenshots/reference"
    cleanOutputDir: bool = True
    defaults: dict[str, Any] = Field(default_factory=dict)
    captures: list[CaptureSpec] = Field(min_length=5)


class AcceptedWebsitePackage(StrictModel):
    site_id: str = Field(min_length=1)
    concept_seed: SiteSeed
    accepted_concept: ConceptCandidate
    critic_report: ConceptCritique
    website_path: str
    verifier_report: VerifierReport
    screenshot_manifest_path: str
    reference_screenshots_dir: str


class GenerationResult(StrictModel):
    request: GenerationRequest
    dataset_plan: DatasetPlan
    packages: list[AcceptedWebsitePackage] = Field(default_factory=list)


def write_model_json(path: str | Path, model: BaseModel) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(model.model_dump_json(indent=2), encoding="utf-8")


def read_model_json(path: str | Path, model_type: type[BaseModel]) -> BaseModel:
    return model_type.model_validate_json(Path(path).read_text(encoding="utf-8"))
