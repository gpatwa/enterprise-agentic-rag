"""Deterministic exposure-aware examples with point-in-time joins.

The builder is intentionally provider-neutral.  It consumes canonical events
and materialized feature records, then emits immutable ranking feature sets.
No event or feature after an impression can enter that impression's example.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import Enum
from typing import Iterable, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.events.models import EventType, InteractionEvent
from app.features.materialization import FeatureKind as MaterializedFeatureKind
from app.features.materialization import FeatureRecord
from app.ranking.contracts import FeatureKind, FeatureSet, FeatureValue, MissingReason

_ID = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$"
_VERSION = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
_MAX_EXAMPLES = 50_000
_MAX_CANDIDATES = 500
_MAX_MISSING = 128


class _TrainingModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, protected_namespaces=())


class ExposureState(str, Enum):
    EXPOSED = "exposed"
    UNEXPOSED = "unexposed"


class LabelKind(str, Enum):
    CLICK = "click"
    QUALIFIED_PLAY = "qualified_play"
    PLAYTIME = "playtime"
    SAVE = "save"
    DISMISS = "dismiss"
    REPORT = "report"
    SKIP = "skip"
    UNEXPOSED = "unexposed"


class TimeSplit(str, Enum):
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"


class CandidatePool(_TrainingModel):
    """Candidate universe for one request, including items not exposed."""

    tenant_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    user_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    request_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    as_of: datetime
    candidate_ids: tuple[str, ...] = Field(min_length=1, max_length=_MAX_CANDIDATES)

    @model_validator(mode="after")
    def validate_pool(self) -> "CandidatePool":
        _aware(self.as_of, "as_of")
        if len(set(self.candidate_ids)) != len(self.candidate_ids):
            raise ValueError("candidate IDs must be unique")
        return self


class TimeSplitBoundaries(_TrainingModel):
    validation_at: datetime
    test_at: datetime

    @model_validator(mode="after")
    def validate_order(self) -> "TimeSplitBoundaries":
        _aware(self.validation_at, "validation_at")
        _aware(self.test_at, "test_at")
        if self.validation_at >= self.test_at:
            raise ValueError("validation_at must be before test_at")
        return self


class TrainingExample(_TrainingModel):
    """One candidate decision with explicit exposure and label semantics."""

    schema_version: Literal["v1"] = "v1"
    example_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    tenant_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    user_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    experience_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    request_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    impression_event_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    impression_at: datetime
    feature_as_of: datetime
    feature_version: str = Field(min_length=1, max_length=128, pattern=_VERSION)
    exposure: ExposureState
    label: LabelKind
    label_value: float = Field(ge=0, le=86_400, allow_inf_nan=False)
    label_event_id: str | None = Field(default=None, max_length=255, pattern=_ID)
    cohort: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    split: TimeSplit
    missing_features: tuple[str, ...] = Field(default_factory=tuple, max_length=_MAX_MISSING)
    feature_sets: tuple[FeatureSet, ...] = Field(min_length=1, max_length=3)
    synthetic: bool

    @model_validator(mode="after")
    def validate_example(self) -> "TrainingExample":
        _aware(self.impression_at, "impression_at")
        _aware(self.feature_as_of, "feature_as_of")
        if self.feature_as_of > self.impression_at:
            raise ValueError("feature_as_of must not be after impression_at")
        if len(set(self.missing_features)) != len(self.missing_features):
            raise ValueError("missing feature names must be unique")
        kinds = {item.feature_kind for item in self.feature_sets}
        if FeatureKind.ITEM not in kinds:
            raise ValueError("examples require item features")
        if self.exposure is ExposureState.UNEXPOSED:
            if self.label is not LabelKind.UNEXPOSED or self.label_event_id is not None or self.label_value != 0.0:
                raise ValueError("unexposed candidates must use the unexposed label")
        elif self.label is LabelKind.UNEXPOSED:
            raise ValueError("exposed candidates cannot use the unexposed label")
        if self.label in {LabelKind.CLICK, LabelKind.QUALIFIED_PLAY, LabelKind.SAVE} and self.label_value not in {0.0, 1.0}:
            raise ValueError("binary labels must be zero or one")
        return self

    def serialize(self) -> str:
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=True, separators=(",", ":"), sort_keys=True)


class TrainingDataset(_TrainingModel):
    """Bounded immutable examples plus a reproducible dataset receipt."""

    schema_version: Literal["v1"] = "v1"
    dataset_version: str = Field(min_length=1, max_length=128, pattern=_VERSION)
    examples: tuple[TrainingExample, ...] = Field(min_length=1, max_length=_MAX_EXAMPLES)
    examples_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest: dict[str, object]

    @model_validator(mode="after")
    def validate_dataset(self) -> "TrainingDataset":
        ids = tuple(item.example_id for item in self.examples)
        if len(set(ids)) != len(ids):
            raise ValueError("example IDs must be unique")
        expected = _checksum(self.examples)
        if expected != self.examples_checksum:
            raise ValueError("examples_checksum does not match examples")
        return self


class TrainingExampleBuilder:
    """Build examples without allowing temporal, tenant, or exposure leakage."""

    def __init__(self, *, dataset_version: str = "v1", cohort: str = "default", max_examples: int = _MAX_EXAMPLES) -> None:
        if not 1 <= max_examples <= _MAX_EXAMPLES:
            raise ValueError(f"max_examples must be between 1 and {_MAX_EXAMPLES}")
        self.dataset_version = dataset_version
        self.cohort = cohort
        self.max_examples = max_examples

    def build(
        self,
        impressions: Sequence[InteractionEvent],
        features: Sequence[FeatureRecord],
        events: Iterable[InteractionEvent] = (),
        candidate_pools: Sequence[CandidatePool] = (),
        *,
        splits: TimeSplitBoundaries,
        observation_end: datetime | None = None,
    ) -> TrainingDataset:
        _aware(splits.validation_at, "validation_at")
        if observation_end is not None:
            _aware(observation_end, "observation_end")
        impression_list = tuple(impressions)
        event_list = tuple(events)
        feature_list = tuple(features)
        self._validate_inputs(impression_list, event_list, feature_list, candidate_pools)
        pools = {(pool.tenant_id, pool.request_id): pool for pool in candidate_pools}
        examples: list[TrainingExample] = []
        for impression in sorted(impression_list, key=lambda item: (item.occurred_at, item.event_id)):
            pool = pools.get((impression.tenant_id, impression.request_id))
            if pool is not None and (pool.user_id != impression.user_id or pool.as_of > impression.occurred_at):
                raise ValueError("candidate pool does not match impression lineage or as-of time")
            candidate_ids = pool.candidate_ids if pool is not None else (impression.experience_id,)
            if impression.experience_id not in candidate_ids:
                raise ValueError("candidate pool must contain the exposed experience")
            for experience_id in candidate_ids:
                exposed = experience_id == impression.experience_id
                label_event = self._label_event(impression, experience_id, event_list, observation_end) if exposed else None
                selected = self._select_features(feature_list, impression, experience_id)
                feature_sets, version, feature_as_of, missing, synthetic = selected
                label, label_value, event_id = self._label_fields(exposed, label_event)
                example_id = f"{impression.event_id}:{experience_id}"
                examples.append(
                    TrainingExample(
                        example_id=example_id,
                        tenant_id=impression.tenant_id,
                        user_id=impression.user_id,
                        experience_id=experience_id,
                        request_id=impression.request_id,
                        impression_event_id=impression.event_id,
                        impression_at=impression.occurred_at,
                        feature_as_of=feature_as_of,
                        feature_version=version,
                        exposure=ExposureState.EXPOSED if exposed else ExposureState.UNEXPOSED,
                        label=label,
                        label_value=label_value,
                        label_event_id=event_id,
                        cohort=self.cohort,
                        split=_split(impression.occurred_at, splits),
                        missing_features=missing,
                        feature_sets=feature_sets,
                        synthetic=synthetic,
                    )
                )
                if len(examples) > self.max_examples:
                    raise ValueError(f"training examples exceed max_examples={self.max_examples}")
        examples.sort(key=lambda item: item.example_id)
        checksum = _checksum(examples)
        manifest = {
            "dataset_version": self.dataset_version,
            "cohort": self.cohort,
            "example_count": len(examples),
            "exposed_count": sum(item.exposure is ExposureState.EXPOSED for item in examples),
            "unexposed_count": sum(item.exposure is ExposureState.UNEXPOSED for item in examples),
            "splits": {split.value: sum(item.split is split for item in examples) for split in TimeSplit},
            "examples_checksum": checksum,
        }
        return TrainingDataset(dataset_version=self.dataset_version, examples=tuple(examples), examples_checksum=checksum, manifest=manifest)

    @staticmethod
    def _validate_inputs(
        impressions: Sequence[InteractionEvent],
        events: Sequence[InteractionEvent],
        features: Sequence[FeatureRecord],
        pools: Sequence[CandidatePool],
    ) -> None:
        if not impressions:
            raise ValueError("at least one impression is required")
        if any(item.event_type is not EventType.IMPRESSION for item in impressions):
            raise ValueError("impressions must contain only impression events")
        if len({item.event_id for item in impressions}) != len(impressions) or len({item.event_id for item in events}) != len(events):
            raise ValueError("event IDs must be unique")
        if set(item.event_id for item in impressions) & {item.event_id for item in events}:
            raise ValueError("impression and action event IDs must be disjoint")
        if len({(item.tenant_id, item.request_id) for item in impressions}) != len(impressions):
            raise ValueError("each request must have one impression record")
        if len({(item.tenant_id, item.subject_type, item.subject_id) for item in features}) != len(features):
            raise ValueError("feature subject snapshots must be unique")
        if len({(item.tenant_id, item.request_id) for item in pools}) != len(pools):
            raise ValueError("candidate pools must be unique per tenant and request")
        if any(not item.synthetic for item in impressions + events + features):
            raise ValueError("training examples accept synthetic records only")

    @staticmethod
    def _label_event(impression: InteractionEvent, experience_id: str, events: Sequence[InteractionEvent], observation_end: datetime | None) -> InteractionEvent | None:
        candidates = [
            event for event in events
            if event.tenant_id == impression.tenant_id
            and event.user_id == impression.user_id
            and event.request_id == impression.request_id
            and event.experience_id == experience_id
            and event.impression_token == impression.impression_token
            and event.occurred_at >= impression.occurred_at
            and (observation_end is None or event.occurred_at <= observation_end)
        ]
        priority = {
            EventType.REPORT: 0, EventType.DISMISS: 1, EventType.QUALIFIED_PLAY: 2,
            EventType.PLAYTIME: 3, EventType.SAVE: 4, EventType.CLICK: 5,
        }
        candidates.sort(key=lambda item: (priority.get(item.event_type, 99), item.occurred_at, item.event_id))
        return candidates[0] if candidates else None

    @staticmethod
    def _label_fields(exposed: bool, event: InteractionEvent | None) -> tuple[LabelKind, float, str | None]:
        if not exposed:
            return LabelKind.UNEXPOSED, 0.0, None
        if event is None:
            return LabelKind.SKIP, 0.0, None
        if event.event_type is EventType.PLAYTIME:
            return LabelKind.PLAYTIME, float(event.payload.duration_seconds), event.event_id
        values = {
            EventType.CLICK: (LabelKind.CLICK, 1.0),
            EventType.QUALIFIED_PLAY: (LabelKind.QUALIFIED_PLAY, 1.0),
            EventType.SAVE: (LabelKind.SAVE, 1.0),
            EventType.DISMISS: (LabelKind.DISMISS, 1.0),
            EventType.REPORT: (LabelKind.REPORT, 1.0),
        }
        label, value = values.get(event.event_type, (LabelKind.SKIP, 0.0))
        return label, value, event.event_id

    @staticmethod
    def _select_features(features: Sequence[FeatureRecord], impression: InteractionEvent, experience_id: str) -> tuple[tuple[FeatureSet, ...], str, datetime, tuple[str, ...], bool]:
        applicable = [item for item in features if item.tenant_id == impression.tenant_id and item.as_of <= impression.occurred_at and item.feature_version]
        selected: dict[MaterializedFeatureKind, FeatureRecord] = {}
        for kind, subject in ((MaterializedFeatureKind.USER, impression.user_id), (MaterializedFeatureKind.CONTEXT, impression.user_id), (MaterializedFeatureKind.ITEM, experience_id)):
            choices = [item for item in applicable if item.subject_type is kind and item.subject_id == subject]
            if choices:
                selected[kind] = max(choices, key=lambda item: item.as_of)
        if not selected:
            raise ValueError("no point-in-time feature snapshot is available")
        versions = {item.feature_version for item in selected.values()}
        if len(versions) != 1:
            raise ValueError("feature snapshots must use one version")
        sets: list[FeatureSet] = []
        missing: list[str] = []
        for materialized_kind, ranking_kind, subject in ((MaterializedFeatureKind.USER, FeatureKind.USER, impression.user_id), (MaterializedFeatureKind.CONTEXT, FeatureKind.CONTEXT, impression.request_id), (MaterializedFeatureKind.ITEM, FeatureKind.ITEM, experience_id)):
            record = selected.get(materialized_kind)
            if record is None:
                missing.append(ranking_kind.value)
                values = (FeatureValue(name="snapshot", kind="numeric", missing_reason=MissingReason.NOT_AVAILABLE),)
            else:
                values = tuple(FeatureValue(name=name, kind="numeric", numeric_value=value) for name, value in sorted(record.values.items())) or (FeatureValue(name="snapshot", kind="numeric", missing_reason=MissingReason.NOT_AVAILABLE),)
            sets.append(FeatureSet(subject_id=subject, feature_kind=ranking_kind, feature_version=next(iter(versions)), features=values))
        chosen_as_of = max(item.as_of for item in selected.values())
        synthetic = all(item.synthetic for item in selected.values())
        return tuple(sets), next(iter(versions)), chosen_as_of, tuple(missing), synthetic


def build_training_examples(
    impressions: Sequence[InteractionEvent],
    features: Sequence[FeatureRecord],
    events: Iterable[InteractionEvent] = (),
    candidate_pools: Sequence[CandidatePool] = (),
    *,
    splits: TimeSplitBoundaries,
    dataset_version: str = "v1",
    cohort: str = "default",
    observation_end: datetime | None = None,
) -> TrainingDataset:
    return TrainingExampleBuilder(dataset_version=dataset_version, cohort=cohort).build(impressions, features, events, candidate_pools, splits=splits, observation_end=observation_end)


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _split(value: datetime, boundaries: TimeSplitBoundaries) -> TimeSplit:
    if value < boundaries.validation_at:
        return TimeSplit.TRAIN
    if value < boundaries.test_at:
        return TimeSplit.VALIDATION
    return TimeSplit.TEST


def _checksum(examples: Sequence[TrainingExample]) -> str:
    return hashlib.sha256("\n".join(item.serialize() for item in examples).encode("utf-8")).hexdigest()
