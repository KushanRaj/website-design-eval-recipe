"""Claude-backed website reference generator.

The package is intentionally importable without a configured Claude runtime.
Real API/CLI work is isolated behind ``ClaudeAgentRuntime``.
"""

from .models import (
    AcceptedWebsitePackage,
    BuildReport,
    ConceptBatch,
    ConceptCandidate,
    ConceptCritique,
    DatasetPlan,
    GenerationRequest,
    GenerationResult,
    ScreenshotManifest,
    SiteSeed,
    VerifierReport,
    WebsiteBundle,
)
from .pipeline import GeneratorPipeline
from .runtime import AgentRuntime, ClaudeAgentRuntime

__all__ = [
    "AcceptedWebsitePackage",
    "AgentRuntime",
    "BuildReport",
    "ClaudeAgentRuntime",
    "ConceptBatch",
    "ConceptCandidate",
    "ConceptCritique",
    "DatasetPlan",
    "GenerationRequest",
    "GenerationResult",
    "GeneratorPipeline",
    "ScreenshotManifest",
    "SiteSeed",
    "VerifierReport",
    "WebsiteBundle",
]
