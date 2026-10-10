"""Strict, provider-neutral contracts for online ranking.

These models describe the data crossing a ranker boundary. They intentionally
do not contain eligibility decisions: policy is evaluated before ranking and
the ranker may only score the supplied eligible candidate batch.
"""
from __future__ import annotations

from enum import Enum
from math import isfinite
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

_ID = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$"
_VERSION = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
_NAME = r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$"
_MAX_FEATURES = 128
_MAX_CANDIDATES = 500
_MAX_REASON_CODES = 8
_MAX_TEXT = 256
_MAX_NUMERIC = 1_000_000_000.0


class _RankingModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        protected_namespaces=(),
        strict=True,
    )


class FeatureKind(str, Enum):
    USER = "user"
    ITEM = "item"
    CONTEXT = "context"
    CROSS = "cross"


class MissingReason(str, Enum):
    NOT_AVAILABLE = "not_available"
    CONSENT_DENIED = "consent_denied"
    COLD_START = "cold_start"
    STALE = "stale"
    VERSION_MISMATCH = "version_mismatch"


class FeatureValue(_RankingModel):
    """One typed, bounded feature with explicit missingness semantics."""

    name: str = Field(min_length=1, max_length=128, pattern=_NAME)
    kind: Literal["numeric", "boolean", "categorical"]
    numeric_value: float | None = Field(default=None, ge=-_MAX_NUMERIC, le=_MAX_NUMERIC, allow_inf_nan=False)
    boolean_value: bool | None = None
    categorical_value: str | None = Field(default=None, min_length=1, max_length=_MAX_TEXT)
    missing_reason: MissingReason | None = None

    @model_validator(mode="after")
    def validate_typed_value(self) -> "FeatureValue":
        values = (self.numeric_value, self.boolean_value, self.categorical_value)
        if self.missing_reason is not None:
            if any(value is not None for value in values):
                raise ValueError("missing features cannot contain a value")
            return self
        if sum(value is not None for value in values) != 1:
            raise ValueError("exactly one typed feature value is required")
        if self.kind == "numeric" and self.numeric_value is None:
            raise ValueError("numeric features require numeric_value")
        if self.kind == "boolean" and self.boolean_value is None:
            raise ValueError("boolean features require boolean_value")
        if self.kind == "categorical" and self.categorical_value is None:
            raise ValueError("categorical features require categorical_value")
        if self.kind != "numeric" and self.numeric_value is not None:
            raise ValueError("numeric_value has the wrong feature kind")
        if self.kind != "boolean" and self.boolean_value is not None:
            raise ValueError("boolean_value has the wrong feature kind")
        if self.kind != "categorical" and self.categorical_value is not None:
            raise ValueError("categorical_value has the wrong feature kind")
        return self


class FeatureSet(_RankingModel):
    """Versioned features for one ranking subject or interaction."""

    subject_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    feature_kind: FeatureKind
    feature_version: str = Field(min_length=1, max_length=128, pattern=_VERSION)
    features: tuple[FeatureValue, ...] = Field(min_length=1, max_length=_MAX_FEATURES)

    @model_validator(mode="after")
    def validate_features(self) -> "FeatureSet":
        names = tuple(feature.name for feature in self.features)
        if len(set(names)) != len(names):
            raise ValueError("feature names must be unique within a feature set")
        return self


class RankingContext(_RankingModel):
    """The complete provider-neutral input envelope for one ranking call."""

    tenant_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    request_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    ranking_version: str = Field(min_length=1, max_length=128, pattern=_VERSION)
    user: FeatureSet | None = None
    context: FeatureSet
    candidates: tuple[FeatureSet, ...] = Field(min_length=1, max_length=_MAX_CANDIDATES)

    @model_validator(mode="after")
    def validate_batch(self) -> "RankingContext":
        if self.context.feature_kind is not FeatureKind.CONTEXT:
            raise ValueError("context feature set must have context kind")
        if self.user is not None and self.user.feature_kind is not FeatureKind.USER:
            raise ValueError("user feature set must have user kind")
        versions = {self.context.feature_version}
        if self.user is not None:
            versions.add(self.user.feature_version)
        versions.update(candidate.feature_version for candidate in self.candidates)
        if len(versions) != 1:
            raise ValueError("all feature sets must use one feature version")
        candidate_ids = tuple(candidate.subject_id for candidate in self.candidates)
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ValueError("candidate identities must be unique")
        if any(candidate.feature_kind is not FeatureKind.ITEM for candidate in self.candidates):
            raise ValueError("candidate feature sets must have item kind")
        return self


class Prediction(_RankingModel):
    """One model score; it does not grant eligibility or policy approval."""

    candidate_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    stage: str = Field(min_length=1, max_length=64, pattern=_NAME)
    model_version: str = Field(min_length=1, max_length=128, pattern=_VERSION)
    score: float = Field(ge=-_MAX_NUMERIC, le=_MAX_NUMERIC, allow_inf_nan=False)
    uncertainty: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    score_missing_reason: MissingReason | None = None
    reason_codes: tuple[str, ...] = Field(default_factory=tuple, max_length=_MAX_REASON_CODES)

    @model_validator(mode="after")
    def validate_prediction(self) -> "Prediction":
        if self.score_missing_reason is not None and self.uncertainty is None:
            raise ValueError("missing predictions must include uncertainty")
        if any(not code or len(code) > 64 for code in self.reason_codes):
            raise ValueError("reason codes must be non-empty and bounded")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("reason codes must be unique")
        if not isfinite(self.score):
            raise ValueError("score must be finite")
        return self


class PredictionBatch(_RankingModel):
    """Predictions constrained to the candidate identities in the input batch."""

    ranking_version: str = Field(min_length=1, max_length=128, pattern=_VERSION)
    model_version: str = Field(min_length=1, max_length=128, pattern=_VERSION)
    predictions: tuple[Prediction, ...] = Field(max_length=_MAX_CANDIDATES)
    candidate_ids: tuple[str, ...] = Field(min_length=1, max_length=_MAX_CANDIDATES)

    @model_validator(mode="after")
    def validate_predictions(self) -> "PredictionBatch":
        if len(set(self.candidate_ids)) != len(self.candidate_ids):
            raise ValueError("candidate identities must be unique")
        prediction_ids = tuple(prediction.candidate_id for prediction in self.predictions)
        if len(set(prediction_ids)) != len(prediction_ids):
            raise ValueError("prediction identities must be unique")
        if any(candidate_id not in self.candidate_ids for candidate_id in prediction_ids):
            raise ValueError("prediction candidate is outside supplied batch")
        if any(prediction.model_version != self.model_version for prediction in self.predictions):
            raise ValueError("prediction model versions must match batch version")
        return self
