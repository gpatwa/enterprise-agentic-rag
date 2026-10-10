"""Deterministic change-proposal generation from triaged feedback (ADS-052)."""

from app.proposals.dbt_project import DbtProject, DbtProjectError
from app.proposals.dbt_rules import DbtFacts, DbtSpec, NoDbtProposal, decide_dbt
from app.proposals.dbt_service import DbtProposalService
from app.proposals.rules import NoProposal, ProposalFacts, ProposalSpec, decide
from app.proposals.service import (
    GenerationResult,
    ProposalConflictError,
    ProposalError,
    ProposalService,
    ProposalStore,
)

__all__ = [
    "DbtFacts",
    "DbtProject",
    "DbtProjectError",
    "DbtProposalService",
    "DbtSpec",
    "NoDbtProposal",
    "decide_dbt",
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
