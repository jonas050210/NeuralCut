"""Phase 6 self-improvement: evaluation, feedback, experiments, promotion.

Safety invariants (enforced in code, not just documented):

- Benchmarks run only against synthetic fixture projects created inside
  isolated temporary directories -- never against user projects or the
  application's real data directory.
- Feedback collection is opt-in (``improvement.feedback_enabled``) and
  refuses to store anything while disabled.
- Candidates are *configurations* (model route / planner profile), never
  code. Nothing here executes generated or untrusted code.
- Promotion is never automatic: it requires evaluation gates to pass AND
  an explicit human spot-check attestation, and rollback is one call.
- Fine-tuning is prepared (config, dataset validation, dry-run job spec)
  but intentionally not executed by this package.
"""

from neuralcut.backend.improvement.benchmark import BenchmarkRunner
from neuralcut.backend.improvement.datasets import (
    DATASET_VERSION,
    build_cases,
    build_manifest,
)
from neuralcut.backend.improvement.feedback import FeedbackStore
from neuralcut.backend.improvement.registry import ImprovementRegistry
from neuralcut.backend.improvement.training import (
    TrainingPreparer,
    validate_dataset_for_training,
)

__all__ = [
    "DATASET_VERSION",
    "BenchmarkRunner",
    "FeedbackStore",
    "ImprovementRegistry",
    "TrainingPreparer",
    "build_cases",
    "build_manifest",
    "validate_dataset_for_training",
]
