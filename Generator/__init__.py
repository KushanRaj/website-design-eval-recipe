"""Claude-backed website reference generator.

The package is intentionally importable without a configured Claude runtime.
Real API/CLI work is isolated behind ``ClaudeAgentRuntime``.
"""

import logging
import sys


def _install_package_logging() -> None:
    """Attach a single stderr handler to the package-level ``Generator`` logger
    so all submodules (``Generator.pipeline``, ``Generator.runtime``,
    ``Generator.verification``) emit their INFO lines without each having to
    bring their own handler. Idempotent against repeated imports."""

    pkg_logger = logging.getLogger("Generator")
    if any(
        isinstance(h, logging.StreamHandler) and getattr(h, "_generator_pkg_handler", False)
        for h in pkg_logger.handlers
    ):
        return
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(
        logging.Formatter("[%(asctime)s] %(name)s %(levelname)s: %(message)s")
    )
    handler._generator_pkg_handler = True  # type: ignore[attr-defined]
    pkg_logger.addHandler(handler)
    pkg_logger.setLevel(logging.INFO)
    # Don't let the root logger duplicate our output if the host app set one up.
    pkg_logger.propagate = False


_install_package_logging()


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
]
