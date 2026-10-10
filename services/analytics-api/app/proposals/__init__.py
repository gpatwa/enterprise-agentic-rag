"""Deterministic change-proposal generation from triaged feedback (ADS-052)."""

from app.proposals.rules import NoProposal, ProposalFacts, ProposalSpec, decide
from app.proposals.service import (
    GenerationResult,
    ProposalConflictError,
    ProposalError,
    ProposalService,
    ProposalStore,
)

__all__ = [
    "GenerationResult",
    "NoProposal",
    "ProposalConflictError",
    "ProposalError",
    "ProposalFacts",
    "ProposalService",
    "ProposalSpec",
    "ProposalStore",
    "decide",
]
