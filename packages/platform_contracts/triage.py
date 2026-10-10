"""Root-cause taxonomy and triage records for recorded feedback (ADS-051).

A triage record is a derived fact about one feedback record: where the fault most likely lies,
which deterministic rule said so, and what evidence it rested on. It is not an instruction and it
changes nothing. Free-text notes are never an input to triage.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TRIAGE_RULES_VERSION = "triage-rules-v1"
_HEX64 = r"^[0-9a-f]{64}$"

RootCause = Literal[
    "retrieval",
    "ontology",
    "intent",
    "semantic",
    "policy",
    "execution",
    "prose",
    "none",
    "undetermined",
]
BasisKind = Literal["system_evidence", "reporter_claim", "both", "none"]
FAULT_CATEGORIES: tuple[str, ...] = ("retrieval", "ontology", "intent", "semantic", "policy", "execution", "prose")


class TriageRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    triage_version: Literal["v1"] = "v1"
    triage_id: str = Field(min_length=1, max_length=255)
    tenant_id: str = Field(min_length=1, max_length=255)
    feedback_id: str = Field(min_length=1, max_length=255)
    run_id: str = Field(min_length=1, max_length=255)
    purpose: str = Field(min_length=1, max_length=255)
    rules_version: str = Field(min_length=1, max_length=64)
    category: RootCause
    rule_id: str = Field(min_length=1, max_length=64)
    basis_kind: BasisKind
    evidence_basis: tuple[str, ...] = ()
    alternates: tuple[RootCause, ...] = ()
    conflict: bool = False
    evidence_fingerprint: str = Field(pattern=_HEX64)
    feedback_fingerprint: str = Field(pattern=_HEX64)
    decision_fingerprint: str = Field(pattern=_HEX64)
    triaged_at: datetime

    @model_validator(mode="after")
    def consistent(self) -> "TriageRecord":
        if self.triaged_at.tzinfo is None:
            raise ValueError("triaged_at must include a timezone")
        if self.category == "undetermined" and not self.alternates and self.basis_kind != "none":
            raise ValueError("an undetermined triage must list its candidate causes")
        if self.category == "none" and self.conflict:
            raise ValueError("a 'none' triage cannot conflict")
        return self


def decision_fingerprint(
    *, rules_version: str, category: str, rule_id: str, basis_kind: str, evidence_basis, alternates, conflict: bool
) -> str:
    """Digest of the decision itself, so a changed rule set under the same version is detectable."""
    payload = [rules_version, category, rule_id, basis_kind, list(evidence_basis), list(alternates), conflict]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()
