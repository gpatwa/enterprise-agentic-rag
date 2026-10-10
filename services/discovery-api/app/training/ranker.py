"""Repeatable, offline-only ranker training for synthetic discovery data."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ranking.contracts import FeatureValue
from app.training.examples import TimeSplit, TrainingDataset, TrainingExample

_MAX_ROWS = 50_000
_MAX_FEATURES = 512
_MAX_SEED = 2_147_483_647
_VERSION = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"


class _TrainingModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, protected_namespaces=())


class RankerTrainingConfig(_TrainingModel):
    """Bounded knobs for one reproducible local training run."""

    dataset_version: str | None = Field(default=None, max_length=128, pattern=_VERSION)
    feature_version: str | None = Field(default=None, max_length=128, pattern=_VERSION)
    seed: int = Field(default=7, ge=0, le=_MAX_SEED)
    max_rows: int = Field(default=_MAX_ROWS, ge=1, le=_MAX_ROWS)
    learning_rate: float = Field(default=0.05, gt=0, le=1, allow_inf_nan=False)
    epochs: int = Field(default=80, ge=1, le=500)
    use_lightgbm: bool = True


class RankerArtifactManifest(_TrainingModel):
    """Redacted receipt for an offline artifact; it contains no feature values."""

    schema_version: str = Field(default="imd-ranker-artifact-v1", pattern=_VERSION)
    dataset_version: str = Field(min_length=1, max_length=128, pattern=_VERSION)
    feature_version: str = Field(min_length=1, max_length=128, pattern=_VERSION)
    seed: int = Field(ge=0, le=_MAX_SEED)
    trainer: str = Field(min_length=1, max_length=32, pattern=r"^[a-z0-9_.:-]+$")
    fallback: bool
    fallback_reason: str | None = Field(default=None, max_length=128)
    row_count: int = Field(ge=1, le=_MAX_ROWS)
    split_counts: dict[str, int]
    feature_count: int = Field(ge=1, le=_MAX_FEATURES)
    feature_names_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    metrics: dict[str, float]

    @model_validator(mode="after")
    def validate_fallback(self) -> "RankerArtifactManifest":
        if self.fallback != (self.trainer == "deterministic-linear"):
            raise ValueError("fallback status must match trainer")
        if self.fallback and not self.fallback_reason:
            raise ValueError("fallback reason is required")
        if not self.fallback and self.fallback_reason is not None:
            raise ValueError("fallback reason is only valid for fallback artifacts")
        if any(value < 0 or not math.isfinite(value) for value in self.metrics.values()):
            raise ValueError("metrics must be finite and non-negative")
        return self


class RankerTrainingResult(_TrainingModel):
    """Model receipt and redacted manifest returned by local training."""

    manifest: RankerArtifactManifest
    feature_names: tuple[str, ...] = Field(min_length=1, max_length=_MAX_FEATURES)
    coefficients: tuple[float, ...] = Field(min_length=1, max_length=_MAX_FEATURES)
    intercept: float

    @model_validator(mode="after")
    def validate_shape(self) -> "RankerTrainingResult":
        if len(self.feature_names) != len(self.coefficients):
            raise ValueError("feature names and coefficients must have equal length")
        if not all(math.isfinite(value) for value in self.coefficients) or not math.isfinite(self.intercept):
            raise ValueError("model parameters must be finite")
        return self


@dataclass(frozen=True)
class _Row:
    example: TrainingExample
    values: tuple[float, ...]
    label: float


def train_offline_ranker(dataset: TrainingDataset, config: RankerTrainingConfig | None = None) -> RankerTrainingResult:
    """Train a ranker from an immutable, point-in-time dataset in local memory."""
    settings = config or RankerTrainingConfig()
    _validate_dataset(dataset, settings)
    rows, feature_names = _rows(dataset.examples)
    if not rows:
        raise ValueError("dataset contains no trainable rows")
    train_rows = [row for row in rows if row.example.split is TimeSplit.TRAIN]
    if not train_rows:
        raise ValueError("dataset must contain at least one train split row")
    coefficients: tuple[float, ...]
    intercept: float
    fallback = False
    fallback_reason: str | None = None
    trainer = "lightgbm"
    if settings.use_lightgbm:
        try:
            coefficients, intercept = _fit_lightgbm(train_rows, feature_names, settings)
        except ImportError:
            fallback = True
            fallback_reason = "lightgbm_unavailable"
            trainer = "deterministic-linear"
            coefficients, intercept = _fit_linear(train_rows, len(feature_names), settings)
        except Exception as exc:  # pragma: no cover - provider failures vary by install
            fallback = True
            fallback_reason = f"lightgbm_error:{type(exc).__name__}"[:128]
            trainer = "deterministic-linear"
            coefficients, intercept = _fit_linear(train_rows, len(feature_names), settings)
    else:
        fallback = True
        fallback_reason = "lightgbm_disabled"
        trainer = "deterministic-linear"
        coefficients, intercept = _fit_linear(train_rows, len(feature_names), settings)

    metrics = _metrics(rows, coefficients, intercept)
    feature_checksum = _checksum(feature_names)
    dataset_checksum = dataset.examples_checksum
    model_checksum = _checksum((trainer, settings.seed, feature_names, coefficients, intercept))
    receipt = {
        "dataset_version": dataset.dataset_version,
        "feature_version": settings.feature_version or _feature_version(rows),
        "seed": settings.seed,
        "trainer": trainer,
        "row_count": len(rows),
        "split_counts": {split.value: sum(row.example.split is split for row in rows) for split in TimeSplit},
        "feature_count": len(feature_names),
        "feature_names_checksum": feature_checksum,
        "dataset_checksum": dataset_checksum,
        "model_checksum": model_checksum,
        "metrics": metrics,
    }
    artifact_checksum = _checksum(receipt)
    manifest = RankerArtifactManifest(
        **receipt,
        fallback=fallback,
        fallback_reason=fallback_reason,
        artifact_checksum=artifact_checksum,
    )
    return RankerTrainingResult(manifest=manifest, feature_names=feature_names, coefficients=coefficients, intercept=intercept)


def train_ranker(dataset: TrainingDataset, config: RankerTrainingConfig | None = None) -> RankerTrainingResult:
    """Compatibility-friendly command entry point for offline training."""
    return train_offline_ranker(dataset, config)


def _validate_dataset(dataset: TrainingDataset, config: RankerTrainingConfig) -> None:
    if config.dataset_version is not None and dataset.dataset_version != config.dataset_version:
        raise ValueError("dataset version does not match training configuration")
    if len(dataset.examples) > config.max_rows:
        raise ValueError("dataset exceeds configured max_rows")
    versions = {item.feature_version for item in dataset.examples}
    if len(versions) != 1:
        raise ValueError("dataset must contain one feature version")
    actual = next(iter(versions))
    if config.feature_version is not None and actual != config.feature_version:
        raise ValueError("feature version does not match training configuration")
    for item in dataset.examples:
        if item.feature_as_of > item.impression_at:
            raise ValueError("training data contains a future feature snapshot")
        for feature_set in item.feature_sets:
            for feature in feature_set.features:
                if feature.numeric_value is not None and not math.isfinite(feature.numeric_value):
                    raise ValueError("training features must be finite")
    ordered = sorted(dataset.examples, key=lambda item: item.impression_at)
    seen = [item.split for item in ordered]
    rank = {TimeSplit.TRAIN: 0, TimeSplit.VALIDATION: 1, TimeSplit.TEST: 2}
    if any(rank[left] > rank[right] for left, right in zip(seen, seen[1:])):
        raise ValueError("time splits must be ordered train, validation, test")


def _rows(examples: Sequence[TrainingExample]) -> tuple[list[_Row], tuple[str, ...]]:
    names = sorted({f"{feature_set.feature_kind.value}:{feature.name}" for example in examples for feature_set in example.feature_sets for feature in feature_set.features})
    if not names or len(names) > _MAX_FEATURES:
        raise ValueError("feature count is outside the training bound")
    index = {name: position for position, name in enumerate(names)}
    rows: list[_Row] = []
    for example in examples:
        values = [0.0] * len(names)
        for feature_set in example.feature_sets:
            for feature in feature_set.features:
                if feature.missing_reason is not None:
                    continue
                value = _numeric_value(feature)
                values[index[f"{feature_set.feature_kind.value}:{feature.name}"]] = value
        rows.append(_Row(example=example, values=tuple(values), label=_label(example)))
    return rows, tuple(names)


def _numeric_value(feature: FeatureValue) -> float:
    if feature.numeric_value is not None:
        value = feature.numeric_value
    elif feature.boolean_value is not None:
        value = 1.0 if feature.boolean_value else 0.0
    elif feature.categorical_value is not None:
        digest = hashlib.sha256(feature.categorical_value.encode("utf-8")).hexdigest()
        value = int(digest[:12], 16) / float(16**12 - 1)
    else:
        return 0.0
    if not math.isfinite(value):
        raise ValueError("training features must be finite")
    return float(value)


def _label(example: TrainingExample) -> float:
    if example.label.value in {"click", "qualified_play", "save"}:
        return min(1.0, example.label_value)
    if example.label.value == "playtime":
        return min(1.0, example.label_value / 86_400.0)
    return 0.0


def _fit_linear(rows: Sequence[_Row], feature_count: int, config: RankerTrainingConfig) -> tuple[tuple[float, ...], float]:
    weights = [0.0] * feature_count
    intercept = 0.0
    rate = config.learning_rate
    for _ in range(config.epochs):
        for row in rows:
            prediction = max(0.0, min(1.0, intercept + sum(weight * value for weight, value in zip(weights, row.values))))
            error = prediction - row.label
            intercept -= rate * error / len(rows)
            for index, value in enumerate(row.values):
                weights[index] -= rate * error * value / len(rows)
    return tuple(weights), intercept


def _fit_lightgbm(rows: Sequence[_Row], feature_names: Sequence[str], config: RankerTrainingConfig) -> tuple[tuple[float, ...], float]:
    import lightgbm as lgb  # type: ignore[import-not-found]

    train = lgb.Dataset([row.values for row in rows], label=[row.label for row in rows], feature_name=list(feature_names), free_raw_data=False)
    booster = lgb.train(
        {"objective": "regression", "verbosity": -1, "seed": config.seed, "feature_fraction_seed": config.seed, "bagging_seed": config.seed, "data_random_seed": config.seed, "num_leaves": 7, "learning_rate": config.learning_rate, "feature_fraction": 1.0, "bagging_fraction": 1.0, "deterministic": True},
        train,
        num_boost_round=min(config.epochs, 100),
    )
    values = booster.feature_importance(importance_type="gain")
    total = float(sum(values)) or 1.0
    coefficients = tuple(float(value) / total for value in values)
    return coefficients, float(booster.predict([tuple(0.0 for _ in feature_names)])[0])


def _metrics(rows: Sequence[_Row], coefficients: Sequence[float], intercept: float) -> dict[str, float]:
    result: dict[str, float] = {}
    for split in TimeSplit:
        selected = [row for row in rows if row.example.split is split]
        errors = []
        for row in selected:
            predicted = max(0.0, min(1.0, intercept + sum(weight * value for weight, value in zip(coefficients, row.values))))
            errors.append((predicted - row.label) ** 2)
        result[f"{split.value}_rows"] = float(len(selected))
        result[f"{split.value}_mse"] = sum(errors) / len(errors) if errors else 0.0
    return result


def _feature_version(rows: Sequence[_Row]) -> str:
    return rows[0].example.feature_version


def _checksum(value: Any) -> str:
    encoded = json.dumps(value, default=lambda item: item.value if hasattr(item, "value") else str(item), ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def main() -> int:
    """Keep the command surface explicit without inventing a storage format."""
    parser = argparse.ArgumentParser(description="Train the local discovery ranker from an in-memory dataset supplied by an embedding application.")
    parser.parse_args()
    parser.error("dataset loading is application-owned; call train_offline_ranker(dataset, config) instead")
    return 2


__all__ = ["RankerArtifactManifest", "RankerTrainingConfig", "RankerTrainingResult", "main", "train_offline_ranker", "train_ranker"]
