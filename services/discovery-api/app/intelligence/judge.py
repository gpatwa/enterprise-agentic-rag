"""Offline, provenance-preserving relevance judge contracts.

This module deliberately has no model SDK, network, route, or ranking import.
Judge output is a proposal artifact; golden and human labels remain separate.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

PROMPT_VERSION = "imd-relevance-judge-prompt-v1"
FAKE_PROVIDER_VERSION = "deterministic-fake-v1"
MODEL_OFF_VERSION = "model-off-v1"
MAX_EVIDENCE_REFERENCES = 8
MAX_BATCH_SIZE = 100
_ID = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$"


class _JudgeContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class RelevanceLabel(StrEnum):
    """Three-point graded relevance plus an explicit non-relevant grade."""

    NONE = "0"
    RELATED = "1"
    GOOD = "2"
    IDEAL = "3"


class JudgeInput(_JudgeContract):
    """Redacted query/candidate material supplied to an offline judge."""

    query_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    candidate_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    query_text: str = Field(min_length=1, max_length=512)
    candidate_text: str = Field(min_length=1, max_length=1024)
    evidence_references: tuple[str, ...] = Field(min_length=1, max_length=MAX_EVIDENCE_REFERENCES)

    @model_validator(mode="after")
    def validate_safe_text(self) -> "JudgeInput":
        for field_name in ("query_text", "candidate_text"):
            value = getattr(self, field_name)
            if any(not character.isprintable() for character in value):
                raise ValueError(f"{field_name} must contain printable text only")
        if len(set(self.evidence_references)) != len(self.evidence_references):
            raise ValueError("evidence references must be unique")
        return self

    def digest(self) -> str:
        """Return a stable input digest without exposing the snippets in output."""
        material = "|".join(
            (self.query_id, self.candidate_id, self.query_text, self.candidate_text, *self.evidence_references)
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()


class JudgeDecision(_JudgeContract):
    """Untrusted, provider-shaped decision validated before proposal creation."""

    label: RelevanceLabel
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1, max_length=256)


class JudgeProvenance(_JudgeContract):
    """Evidence needed to reproduce and review one judge proposal."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, protected_namespaces=())

    source: Literal["offline_relevance_judge"] = "offline_relevance_judge"
    prompt_version: str = Field(min_length=1, max_length=128, pattern=_ID)
    provider_version: str = Field(min_length=1, max_length=128, pattern=_ID)
    model_version: str = Field(min_length=1, max_length=128, pattern=_ID)
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    human_label_authoritative: Literal[True] = True


class JudgeProposal(_JudgeContract):
    """A reviewable suggestion that never mutates ground truth."""

    proposal_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    query_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    candidate_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    evidence_references: tuple[str, ...] = Field(min_length=1, max_length=MAX_EVIDENCE_REFERENCES)
    label: RelevanceLabel
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1, max_length=256)
    provenance: JudgeProvenance


class HumanLabel(_JudgeContract):
    """Authoritative review data kept separate from judge proposals."""

    proposal_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    label: RelevanceLabel
    review_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    notes: str | None = Field(default=None, max_length=512)


class RelevanceReview(_JudgeContract):
    """Mergeable review artifact; human labels are never overwritten by proposals."""

    proposals: tuple[JudgeProposal, ...] = Field(max_length=MAX_BATCH_SIZE)
    human_labels: tuple[HumanLabel, ...] = Field(default_factory=tuple, max_length=MAX_BATCH_SIZE)

    @model_validator(mode="after")
    def validate_review(self) -> "RelevanceReview":
        proposal_ids = tuple(proposal.proposal_id for proposal in self.proposals)
        if len(proposal_ids) != len(set(proposal_ids)):
            raise ValueError("proposal IDs must be unique")
        if any(label.proposal_id not in proposal_ids for label in self.human_labels):
            raise ValueError("human label must reference a proposal")
        label_ids = tuple(label.proposal_id for label in self.human_labels)
        if len(label_ids) != len(set(label_ids)):
            raise ValueError("one authoritative human label is allowed per proposal")
        return self

    def authoritative_labels(self) -> dict[str, RelevanceLabel]:
        """Return human labels only; absent reviews remain unresolved."""
        return {label.proposal_id: label.label for label in self.human_labels}


class RelevanceJudge(Protocol):
    """Provider boundary for offline scripted implementations only."""

    def generate(self, item: JudgeInput) -> object:
        """Return untrusted decision data for one redacted case."""


class ScriptedRelevanceJudge:
    """Deterministic fake judge for local evaluation and demo evidence."""

    provider_version = FAKE_PROVIDER_VERSION
    model_version = FAKE_PROVIDER_VERSION

    def __init__(self, labels: Mapping[tuple[str, str], RelevanceLabel] | None = None) -> None:
        self.labels = dict(labels or {})
        self.calls = 0

    def generate(self, item: JudgeInput) -> object:
        self.calls += 1
        label = self.labels.get((item.query_id, item.candidate_id))
        if label is None:
            query_words = set(re.findall(r"[a-z0-9]+", item.query_text.lower()))
            candidate_words = set(re.findall(r"[a-z0-9]+", item.candidate_text.lower()))
            overlap = len(query_words & candidate_words)
            label = RelevanceLabel.GOOD if overlap else RelevanceLabel.NONE
        confidence = 0.95 if label is RelevanceLabel.IDEAL else 0.8 if label is RelevanceLabel.GOOD else 0.6
        return {"label": label, "confidence": confidence, "rationale": "deterministic scripted evaluation"}


class OfflineRelevanceJudge:
    """Run bounded proposals without an online ranking dependency."""

    def __init__(self, provider: RelevanceJudge | None = None, *, prompt_version: str = PROMPT_VERSION) -> None:
        self.provider = provider
        self.prompt_version = prompt_version

    def evaluate(self, items: Sequence[JudgeInput], *, run_id: str) -> RelevanceReview:
        if not run_id or not re.fullmatch(_ID, run_id):
            raise ValueError("run_id must be a valid bounded identifier")
        if len(items) > MAX_BATCH_SIZE:
            raise ValueError(f"judge batches cannot exceed {MAX_BATCH_SIZE} items")
        if self.provider is None:
            return RelevanceReview(proposals=())
        proposals: list[JudgeProposal] = []
        for item in items:
            try:
                decision = JudgeDecision.model_validate(self.provider.generate(item))
            except Exception:
                continue
            proposal_id = f"{run_id}:{item.query_id}:{item.candidate_id}"
            provenance = JudgeProvenance(
                prompt_version=self.prompt_version,
                provider_version=getattr(self.provider, "provider_version", FAKE_PROVIDER_VERSION),
                model_version=getattr(self.provider, "model_version", FAKE_PROVIDER_VERSION),
                input_digest=item.digest(),
            )
            proposals.append(
                JudgeProposal(
                    proposal_id=proposal_id,
                    query_id=item.query_id,
                    candidate_id=item.candidate_id,
                    evidence_references=item.evidence_references,
                    label=decision.label,
                    confidence=decision.confidence,
                    rationale=decision.rationale,
                    provenance=provenance,
                )
            )
        return RelevanceReview(proposals=tuple(proposals))
