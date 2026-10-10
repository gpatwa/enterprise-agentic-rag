"""Change proposals generated from triaged feedback (ADS-052; shared with ADS-053 and ADS-054).

A proposal is inert data: a request and, where it can be written down mechanically, a patch to a
*draft* copy of a contract. It is never applied by the generator and can never be `certified`; the
status is always `proposed`. Anything after that (review, approval, promotion) is a later packet.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PROPOSAL_VERSION = "v1"
PROPOSAL_RULES_VERSION = "proposal-rules-v1"
_HEX64 = r"^[0-9a-f]{64}$"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:,-]{0,254}$")

ProposalKind = Literal["semantic_context", "dbt", "prompt_candidate"]
ProposalOperation = Literal["flag_definition_for_review", "add_context_edge", "review_label_collision"]
TargetKind = Literal["metric", "dimension", "field", "dataset", "ontology_label"]

# A semantic-context patch may only touch these paths of a registry document, and may only produce a
# draft: it can never change a definition, a policy, or a lifecycle other than "draft".
ALLOWED_PATCH_PATHS = ("/lifecycle", "/contract/version", "/contract/metadata")


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PatchOperation(_Frozen):
    op: Literal["add", "replace"]
    path: str = Field(min_length=1, max_length=255)
    value: Any

    @model_validator(mode="after")
    def constrained(self) -> "PatchOperation":
        if self.path not in ALLOWED_PATCH_PATHS:
            raise ValueError(f"patch path {self.path!r} is not allowed for a change proposal")
        if self.path == "/lifecycle" and self.value != "draft":
            raise ValueError("a proposal can only produce a draft; it can never certify")
        return self


class ChangeProposal(_Frozen):
    proposal_version: Literal["v1"] = PROPOSAL_VERSION
    proposal_id: str = Field(min_length=1, max_length=255)
    tenant_id: str = Field(min_length=1, max_length=255)
    kind: ProposalKind
    operation: ProposalOperation
    target_kind: TargetKind
    target_id: str = Field(min_length=1, max_length=255)
    parameters: dict[str, str] = Field(default_factory=dict)
    base_contract: str = Field(min_length=1, max_length=512)
    base_contract_fingerprint: str = Field(pattern=_HEX64)
    draft_version: str | None = Field(default=None, max_length=255)
    draft_patch: tuple[PatchOperation, ...] = ()
    patch_note: str | None = Field(default=None, max_length=500)
    rationale_codes: tuple[str, ...] = Field(min_length=1)
    origin_triage_id: str = Field(min_length=1, max_length=255)
    origin_feedback_id: str = Field(min_length=1, max_length=255)
    origin_run_id: str = Field(min_length=1, max_length=255)
    rules_version: str = Field(min_length=1, max_length=64)
    status: Literal["proposed"] = "proposed"
    created_by: Literal["system:proposal-generator"] = "system:proposal-generator"
    created_at: datetime
    content_fingerprint: str = Field(pattern=_HEX64)

    @field_validator("target_id")
    @classmethod
    def identifiers_only(cls, value: str) -> str:
        if not _ID.match(value):
            raise ValueError("a proposal target must be an identifier, not an expression")
        return value

    @model_validator(mode="after")
    def consistent(self) -> "ChangeProposal":
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must include a timezone")
        if self.draft_patch and not self.draft_version:
            raise ValueError("a patch needs the draft version it creates")
        if self.draft_patch and not any(op.path == "/lifecycle" for op in self.draft_patch):
            raise ValueError("a patch must explicitly set the lifecycle to draft")
        return self


def proposal_fingerprint(
    *,
    kind: str,
    operation: str,
    target_kind: str,
    target_id: str,
    parameters: dict[str, str],
    base_contract: str,
    base_contract_fingerprint: str,
    rules_version: str,
) -> str:
    """Digest of what the proposal asks for, so equal requests deduplicate whoever raised them."""
    payload = [
        kind,
        operation,
        target_kind,
        target_id,
        sorted(parameters.items()),
        base_contract,
        base_contract_fingerprint,
        rules_version,
    ]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


def apply_patch(document: dict[str, Any], patch: tuple[PatchOperation, ...]) -> dict[str, Any]:
    """Return a patched copy for preview and tests. Never writes anywhere."""
    result = json.loads(json.dumps(document))
    for operation in patch:
        node: Any = result
        *parents, leaf = [part for part in operation.path.split("/") if part]
        for part in parents:
            node = node[part]
        node[leaf] = operation.value
    return result
