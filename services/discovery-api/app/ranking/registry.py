"""Local immutable model metadata registry.

The registry records references to model artifacts, never artifact contents. It
is deliberately in-memory and provider-neutral; persistence and serving belong
to later packets.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field, model_validator

_ID = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$"
_VERSION = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
_CHECKSUM = r"^[0-9a-f]{64}$"
_MAX_EVIDENCE = 32


class _RegistryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, protected_namespaces=())


class ModelState(str, Enum):
    DRAFT = "draft"
    CANDIDATE = "candidate"
    APPROVED = "approved"
    DEPRECATED = "deprecated"


class ModelCompatibility(_RegistryModel):
    """Versions that must agree with the online ranking contract."""

    dataset_version: str = Field(min_length=1, max_length=128, pattern=_VERSION)
    feature_version: str = Field(min_length=1, max_length=128, pattern=_VERSION)
    policy_version: str = Field(min_length=1, max_length=128, pattern=_VERSION)
    ranking_version: str = Field(min_length=1, max_length=128, pattern=_VERSION)
    artifact_checksum: str = Field(pattern=_CHECKSUM)
    training_manifest_checksum: str = Field(pattern=_CHECKSUM)


class ModelEvidence(_RegistryModel):
    """Redacted references proving that a model is ready for promotion."""

    evaluation_checksum: str = Field(pattern=_CHECKSUM)
    evidence_ids: tuple[str, ...] = Field(min_length=1, max_length=_MAX_EVIDENCE)
    approved_by: str | None = Field(default=None, min_length=1, max_length=128, pattern=_ID)

    @model_validator(mode="after")
    def validate_ids(self) -> "ModelEvidence":
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("evidence_ids must be unique")
        return self


class ModelRecord(_RegistryModel):
    """An immutable model version and its compatibility receipt."""

    model_name: str = Field(min_length=1, max_length=128, pattern=_ID)
    model_version: str = Field(min_length=1, max_length=128, pattern=_VERSION)
    state: ModelState = ModelState.DRAFT
    compatibility: ModelCompatibility
    evidence: ModelEvidence | None = None
    created_at: datetime
    metadata_checksum: str = Field(pattern=_CHECKSUM)

    @model_validator(mode="after")
    def validate_time(self) -> "ModelRecord":
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        if self.state is ModelState.APPROVED and self.evidence is None:
            raise ValueError("approved models require promotion evidence")
        return self

    def serialize(self) -> str:
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=True, separators=(",", ":"), sort_keys=True)


class RegistryAudit(_RegistryModel):
    """Append-only, redacted evidence for a registry mutation."""

    audit_id: str = Field(pattern=_CHECKSUM)
    action: str = Field(min_length=1, max_length=32, pattern=r"^[a-z_]+$")
    model_name: str = Field(min_length=1, max_length=128, pattern=_ID)
    model_version: str = Field(min_length=1, max_length=128, pattern=_VERSION)
    previous_state: ModelState | None = None
    next_state: ModelState
    reason: str = Field(min_length=1, max_length=256)
    compatibility_checksum: str = Field(pattern=_CHECKSUM)
    evidence_checksum: str | None = Field(default=None, pattern=_CHECKSUM)
    occurred_at: datetime


class ModelRegistry:
    """Deterministic local registry with explicit promotion and rollback gates."""

    _TRANSITIONS = {
        ModelState.DRAFT: {ModelState.CANDIDATE},
        ModelState.CANDIDATE: {ModelState.APPROVED},
        ModelState.APPROVED: {ModelState.DEPRECATED},
        ModelState.DEPRECATED: set(),
    }

    def __init__(self, *, expected: ModelCompatibility) -> None:
        self._expected = expected
        self._records: dict[tuple[str, str], ModelRecord] = {}
        self._audits: list[RegistryAudit] = []

    @property
    def audits(self) -> tuple[RegistryAudit, ...]:
        return tuple(self._audits)

    def register(self, record: ModelRecord) -> ModelRecord:
        key = (record.model_name, record.model_version)
        if key in self._records:
            raise ValueError("model version already exists")
        self._check_compatibility(record.compatibility)
        if record.state is not ModelState.DRAFT:
            raise ValueError("new models must start in draft state")
        self._records[key] = record
        self._append_audit(record, "register", None, ModelState.DRAFT, "registered")
        return record

    def promote(self, model_name: str, model_version: str, target: ModelState, *, evidence: ModelEvidence | None = None, reason: str = "promoted") -> ModelRecord:
        record = self._get(model_name, model_version)
        if target not in self._TRANSITIONS[record.state]:
            raise ValueError(f"invalid transition {record.state.value}->{target.value}")
        self._check_compatibility(record.compatibility)
        if target is ModelState.CANDIDATE and evidence is None:
            raise ValueError("candidate promotion requires evidence")
        if target is ModelState.APPROVED and evidence is None:
            raise ValueError("approval requires evidence")
        updated = record.model_copy(update={"state": target, "evidence": evidence or record.evidence})
        self._records[(model_name, model_version)] = updated
        self._append_audit(updated, "promote", record.state, target, reason, evidence or record.evidence)
        return updated

    def deprecate(self, model_name: str, model_version: str, *, reason: str = "deprecated") -> ModelRecord:
        return self.promote(model_name, model_version, ModelState.DEPRECATED, reason=reason)

    def active(self, model_name: str) -> ModelRecord:
        approved = [record for record in self._records.values() if record.model_name == model_name and record.state is ModelState.APPROVED]
        if not approved:
            raise LookupError("no approved model is active")
        return max(approved, key=lambda record: record.model_version)

    def rollback(self, model_name: str, model_version: str, *, reason: str = "rollback") -> ModelRecord:
        target = self._get(model_name, model_version)
        if target.state is not ModelState.DEPRECATED:
            raise ValueError("rollback target must be deprecated")
        self._check_compatibility(target.compatibility)
        previous = self.active(model_name)
        self.promote(model_name, previous.model_version, ModelState.DEPRECATED, reason=reason)
        restored = target.model_copy(update={"state": ModelState.APPROVED})
        self._records[(model_name, model_version)] = restored
        self._append_audit(restored, "rollback", ModelState.DEPRECATED, ModelState.APPROVED, reason, restored.evidence)
        return restored

    def _get(self, model_name: str, model_version: str) -> ModelRecord:
        try:
            return self._records[(model_name, model_version)]
        except KeyError as exc:
            raise LookupError("unknown model version") from exc

    def _check_compatibility(self, compatibility: ModelCompatibility) -> None:
        if compatibility != self._expected:
            raise ValueError("model compatibility does not match registry contract")

    def _append_audit(self, record: ModelRecord, action: str, previous: ModelState | None, next_state: ModelState, reason: str, evidence: ModelEvidence | None = None) -> None:
        evidence_checksum = evidence.evaluation_checksum if evidence is not None else None
        payload = f"{action}|{record.model_name}|{record.model_version}|{previous}|{next_state}|{reason}|{len(self._audits)}"
        audit_id = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        compatibility_checksum = hashlib.sha256(record.compatibility.model_dump_json().encode("utf-8")).hexdigest()
        self._audits.append(RegistryAudit(audit_id=audit_id, action=action, model_name=record.model_name, model_version=record.model_version, previous_state=previous, next_state=next_state, reason=reason, compatibility_checksum=compatibility_checksum, evidence_checksum=evidence_checksum, occurred_at=datetime.now(timezone.utc)))


def checksum_for(values: Iterable[str]) -> str:
    """Return a deterministic receipt for redacted metadata identifiers."""
    return hashlib.sha256("\n".join(sorted(values)).encode("utf-8")).hexdigest()
