"""Provider-neutral candidate contracts."""

from app.candidates.contracts import (
    Candidate,
    CandidateBatch,
    CandidateSourceResult,
    CandidateTrace,
    Degradation,
    SourceQuota,
)

__all__ = ["Candidate", "CandidateBatch", "CandidateSourceResult", "CandidateTrace", "Degradation", "SourceQuota"]
