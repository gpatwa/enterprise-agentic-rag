"""Point-in-time, exposure-aware training dataset contracts."""

from app.training.examples import (
    CandidatePool,
    ExposureState,
    LabelKind,
    TimeSplitBoundaries,
    TrainingDataset,
    TrainingExampleBuilder,
    build_training_examples,
)

__all__ = [
    "CandidatePool",
    "ExposureState",
    "LabelKind",
    "TimeSplitBoundaries",
    "TrainingDataset",
    "TrainingExampleBuilder",
    "build_training_examples",
]
