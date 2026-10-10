"""Pure, backend-neutral metrics for immersive discovery evaluation."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Mapping, Sequence

from app.candidates.contracts import CandidateTrace, Degradation

METRIC_VERSIONS: Mapping[str, str] = {
    "recall_at_k": "v1",
    "mrr": "v1",
    "ndcg_at_k": "v1",
    "catalog_coverage": "v1",
    "unique_creator_coverage": "v1",
    "intra_list_diversity": "v1",
    "calibration_error": "v1",
    "negative_feedback_rate": "v1",
    "policy_violation_rate": "v1",
}

SOURCE_METRIC_VERSIONS: Mapping[str, str] = {
    "source_recall_at_k": "v1",
    "source_catalog_coverage": "v1",
    "source_overlap_rate": "v1",
    "cold_start_quality": "v1",
}


@dataclass(frozen=True)
class QueryMetrics:
    query_id: str
    recall_at_k: float
    mrr: float
    ndcg_at_k: float
    retrieved_count: int
    relevant_count: int


@dataclass(frozen=True)
class MetricResult:
    metric_id: str
    version: str
    value: float


@dataclass(frozen=True)
class EvaluationReport:
    query_count: int
    cohort_labels: tuple[str, ...]
    metrics: tuple[MetricResult, ...]

    @property
    def metric_versions(self) -> dict[str, str]:
        return {metric.metric_id: metric.version for metric in self.metrics}

    def to_dict(self) -> dict[str, object]:
        return {
            "query_count": self.query_count,
            "cohort_labels": list(self.cohort_labels),
            "metric_versions": self.metric_versions,
            "metrics": {
                metric.metric_id: metric.value
                for metric in self.metrics
            },
        }

    def serialize(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class SourceEvaluationCase:
    """One query join between a candidate trace, judgments, and cohorts."""

    query_id: str
    trace: CandidateTrace
    relevance: Mapping[str, int]
    cohort_labels: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.query_id.strip():
            raise ValueError("query_id must be non-empty")
        labels = tuple(self.cohort_labels)
        if len(labels) != len(set(labels)):
            raise ValueError("cohort labels must be unique per query")
        if any(not label.strip() for label in labels):
            raise ValueError("cohort labels must be non-empty")
        if any(not item_id.strip() for item_id in self.relevance):
            raise ValueError("relevance IDs must be non-empty")
        if any(isinstance(grade, bool) or not isinstance(grade, int) for grade in self.relevance.values()):
            raise ValueError("relevance grades must be integers")


@dataclass(frozen=True)
class SourceMetricResult:
    """A deterministic metric attributed to one source and cohort."""

    metric_id: str
    version: str
    source: str
    cohort: str
    query_count: int
    degraded_query_count: int
    value: float


@dataclass(frozen=True)
class SourceEvaluationReport:
    """Versioned source/cohort evaluation without provider-specific state."""

    query_count: int
    source_labels: tuple[str, ...]
    cohort_labels: tuple[str, ...]
    metrics: tuple[SourceMetricResult, ...]

    @property
    def metric_versions(self) -> dict[str, str]:
        return {
            f"{metric.source}:{metric.cohort}:{metric.metric_id}": metric.version
            for metric in self.metrics
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "query_count": self.query_count,
            "source_labels": list(self.source_labels),
            "cohort_labels": list(self.cohort_labels),
            "metric_versions": self.metric_versions,
            "metrics": [
                {
                    "metric_id": metric.metric_id,
                    "version": metric.version,
                    "source": metric.source,
                    "cohort": metric.cohort,
                    "query_count": metric.query_count,
                    "degraded_query_count": metric.degraded_query_count,
                    "value": metric.value,
                }
                for metric in self.metrics
            ],
        }

    def serialize(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


def evaluate_source_metrics(
    cases: Sequence[SourceEvaluationCase],
    *,
    k: int = 10,
    minimum_grade: int = 1,
) -> SourceEvaluationReport:
    """Attribute retrieval quality to sources and explicit query cohorts.

    Each query contributes once to each applicable cohort. Candidate IDs are
    deduplicated per source before every numerator is calculated. A source's
    overlap is its fraction of unique candidates also returned by another
    healthy source for that query; degraded sources have explicit zero output.
    """
    _validate_k(k)
    entries = tuple(cases)
    query_ids = [case.query_id for case in entries]
    if len(query_ids) != len(set(query_ids)):
        raise ValueError("source evaluation query IDs must be unique")
    source_names = sorted({result.source for case in entries for result in case.trace.source_results})
    if not source_names:
        return SourceEvaluationReport(0, (), (), ())
    expected_sources = set(source_names)
    all_cohorts = sorted({label for case in entries for label in case.cohort_labels} | {"all"})
    buckets: dict[tuple[str, str], list[tuple[float, float, float, bool]]] = {}
    for case in entries:
        labels = ("all", *case.cohort_labels)
        results = {result.source: result for result in case.trace.source_results}
        if set(results) != expected_sources:
            raise ValueError("source joins must contain the same source labels for every query")
        healthy_ids = {
            result.source: {candidate.experience_id for candidate in result.candidates}
            for result in case.trace.source_results
            if result.degradation in {Degradation.OK, Degradation.EMPTY}
        }
        for source in source_names:
            result = results[source]
            ids = [candidate.experience_id for candidate in result.candidates]
            judged_ids = set(case.relevance)
            degraded = result.degradation in {Degradation.FAILURE, Degradation.TIMEOUT}
            recall = 0.0 if degraded else recall_at_k(ids, case.relevance, k=k, minimum_grade=minimum_grade)
            coverage = 0.0 if degraded or not judged_ids else len(set(ids) & judged_ids) / len(judged_ids)
            others = set().union(*(healthy_ids.get(name, set()) for name in source_names if name != source))
            overlap = 0.0 if degraded or not ids else len(set(ids) & others) / len(set(ids))
            for cohort in labels:
                buckets.setdefault((source, cohort), []).append((recall, coverage, overlap, degraded))
    metrics: list[SourceMetricResult] = []
    for source in source_names:
        for cohort in all_cohorts:
            rows = buckets.get((source, cohort), [])
            if not rows:
                continue
            count = len(rows)
            degraded_count = sum(row[3] for row in rows)
            values = {
                "source_recall_at_k": sum(row[0] for row in rows) / count,
                "source_catalog_coverage": sum(row[1] for row in rows) / count,
                "source_overlap_rate": sum(row[2] for row in rows) / count,
            }
            if cohort != "all" and _is_cold_start_cohort(cohort):
                values["cold_start_quality"] = values["source_recall_at_k"]
            for metric_id in sorted(values):
                metrics.append(
                    SourceMetricResult(
                        metric_id=metric_id,
                        version=SOURCE_METRIC_VERSIONS[metric_id],
                        source=source,
                        cohort=cohort,
                        query_count=count,
                        degraded_query_count=degraded_count,
                        value=values[metric_id],
                    )
                )
    return SourceEvaluationReport(len(entries), tuple(source_names), tuple(all_cohorts), tuple(metrics))


def build_source_evaluation_report(
    cases: Sequence[SourceEvaluationCase],
    *,
    k: int = 10,
    minimum_grade: int = 1,
) -> SourceEvaluationReport:
    """Named builder alias matching :func:`build_evaluation_report`."""
    return evaluate_source_metrics(cases, k=k, minimum_grade=minimum_grade)


def recall_at_k(
    retrieved_ids: Sequence[str],
    relevance: Mapping[str, int],
    *,
    k: int = 10,
    minimum_grade: int = 1,
) -> float:
    """Return relevant catalog items found in the stable unique top-k."""
    _validate_k(k)
    relevant = {item_id for item_id, grade in relevance.items() if grade >= minimum_grade}
    if not relevant:
        return 0.0
    return len(set(_unique_prefix(retrieved_ids, k)) & relevant) / len(relevant)


def mean_reciprocal_rank(
    retrieved_ids: Sequence[str],
    relevance: Mapping[str, int],
    *,
    k: int = 10,
    minimum_grade: int = 1,
) -> float:
    """Return the reciprocal rank of the first relevant unique result."""
    _validate_k(k)
    relevant = {item_id for item_id, grade in relevance.items() if grade >= minimum_grade}
    for rank, item_id in enumerate(_unique_prefix(retrieved_ids, k), start=1):
        if item_id in relevant:
            return 1.0 / rank
    return 0.0


def mrr(*args: object, **kwargs: object) -> float:
    """Short alias for :func:`mean_reciprocal_rank`."""
    return mean_reciprocal_rank(*args, **kwargs)  # type: ignore[arg-type]


def ndcg_at_k(
    retrieved_ids: Sequence[str],
    relevance: Mapping[str, int],
    *,
    k: int = 10,
) -> float:
    """Return graded nDCG using gains of ``2**grade - 1``."""
    _validate_k(k)
    retrieved = _unique_prefix(retrieved_ids, k)
    actual = sum(
        _gain(relevance.get(item_id, 0)) / math.log2(rank + 1)
        for rank, item_id in enumerate(retrieved, start=1)
    )
    ideal_grades = sorted(relevance.values(), reverse=True)[:k]
    ideal = sum(
        _gain(grade) / math.log2(rank + 1)
        for rank, grade in enumerate(ideal_grades, start=1)
    )
    return 0.0 if ideal == 0.0 else actual / ideal


def evaluate_query(
    query_id: str,
    retrieved_ids: Sequence[str],
    relevance: Mapping[str, int],
    *,
    k: int = 10,
    minimum_grade: int = 1,
) -> QueryMetrics:
    _validate_k(k)
    unique_retrieved = _unique_prefix(retrieved_ids, k)
    return QueryMetrics(
        query_id=query_id,
        recall_at_k=recall_at_k(retrieved_ids, relevance, k=k, minimum_grade=minimum_grade),
        mrr=mean_reciprocal_rank(retrieved_ids, relevance, k=k, minimum_grade=minimum_grade),
        ndcg_at_k=ndcg_at_k(retrieved_ids, relevance, k=k),
        retrieved_count=len(unique_retrieved),
        relevant_count=sum(grade >= minimum_grade for grade in relevance.values()),
    )


def catalog_coverage(retrieved_ids: Sequence[str], catalog_ids: Sequence[str]) -> float:
    """Return unique retrieved items divided by the unique catalog size."""
    catalog = set(catalog_ids)
    if not catalog:
        return 0.0
    return len(set(retrieved_ids) & catalog) / len(catalog)


def unique_creator_coverage(
    retrieved_ids: Sequence[str],
    catalog_ids: Sequence[str],
    creator_by_item: Mapping[str, str],
) -> float:
    """Return unique retrieved creators divided by creators in the catalog."""
    catalog = set(catalog_ids)
    if any(item_id not in creator_by_item for item_id in catalog):
        raise ValueError("creator denominator is incomplete")
    creators = {creator_by_item[item_id] for item_id in catalog}
    if not creators:
        return 0.0
    retrieved_creators = {
        creator_by_item[item_id]
        for item_id in set(retrieved_ids) & catalog
    }
    return len(retrieved_creators) / len(creators)


def intra_list_diversity(
    item_ids: Sequence[str],
    genres_by_item: Mapping[str, Sequence[str]],
    themes_by_item: Mapping[str, Sequence[str]],
    *,
    embeddings_by_item: Mapping[str, Sequence[float]] | None = None,
) -> float:
    """Return mean pairwise distance, with metadata then vector fallback.

    Metadata distance is Jaccard distance over genres and themes. If both
    metadata sets are empty for a pair, cosine distance is used when both
    vectors exist. Missing or zero vectors contribute deterministic distance
    zero rather than producing NaN.
    """
    items = _unique_all(item_ids)
    if len(items) < 2:
        return 0.0
    distances = [
        _item_distance(first, second, genres_by_item, themes_by_item, embeddings_by_item)
        for index, first in enumerate(items)
        for second in items[index + 1 :]
    ]
    return sum(distances) / len(distances)


def calibration_error(
    predicted_probabilities: Sequence[float],
    observed_outcomes: Sequence[int | bool],
    *,
    bin_count: int = 10,
) -> float:
    """Return equal-width expected calibration error."""
    if bin_count < 1:
        raise ValueError("bin_count must be at least 1")
    if len(predicted_probabilities) != len(observed_outcomes):
        raise ValueError("probabilities and outcomes must have equal lengths")
    if not predicted_probabilities:
        return 0.0
    for probability in predicted_probabilities:
        if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
            raise ValueError("probabilities must be finite values in [0, 1]")
    if any(outcome not in (0, 1, False, True) for outcome in observed_outcomes):
        raise ValueError("outcomes must be binary")
    total = len(predicted_probabilities)
    error = 0.0
    bins: list[list[int]] = [[] for _ in range(bin_count)]
    for index, probability in enumerate(predicted_probabilities):
        bin_index = min(int(probability * bin_count), bin_count - 1)
        bins[bin_index].append(index)
    for indices in bins:
        if indices:
            mean_probability = sum(predicted_probabilities[index] for index in indices) / len(indices)
            mean_outcome = sum(int(observed_outcomes[index]) for index in indices) / len(indices)
            error += len(indices) / total * abs(mean_probability - mean_outcome)
    return error


def negative_feedback_rate(negative_feedback: Sequence[bool]) -> float:
    """Return negative actions divided by observed feedback opportunities."""
    if not negative_feedback:
        return 0.0
    return sum(negative_feedback) / len(negative_feedback)


def policy_violation_rate(violations: Sequence[bool]) -> float:
    """Return policy violations divided by evaluated candidates."""
    if not violations:
        return 0.0
    return sum(violations) / len(violations)


def build_evaluation_report(
    query_metrics: Sequence[QueryMetrics],
    metric_values: Mapping[str, float] | Sequence[MetricResult],
    *,
    cohort_labels: Sequence[str] = (),
    metric_versions: Mapping[str, str] | None = None,
) -> EvaluationReport:
    """Build a stable report and reject duplicate or ambiguous metric IDs."""
    labels = tuple(sorted(set(cohort_labels)))
    if len(labels) != len(tuple(cohort_labels)):
        raise ValueError("cohort labels must be unique")
    versions = dict(metric_versions or {})
    if isinstance(metric_values, Mapping):
        values = dict(metric_values)
    else:
        values = {}
        for metric in metric_values:
            if metric.metric_id in values:
                raise ValueError("metric IDs must be unique")
            values[metric.metric_id] = metric.value
            if metric.metric_id in versions and versions[metric.metric_id] != metric.version:
                raise ValueError("metric versions conflict")
            versions[metric.metric_id] = metric.version
    unknown_versions = set(versions) - set(values)
    if unknown_versions:
        raise ValueError("metric versions contain unknown metric IDs")
    results: list[MetricResult] = []
    for metric_id in sorted(values):
        if not metric_id:
            raise ValueError("metric IDs must be non-empty")
        value = values[metric_id]
        if not math.isfinite(value):
            raise ValueError(f"metric {metric_id} must be finite")
        version = versions.get(metric_id, METRIC_VERSIONS.get(metric_id, "v1"))
        if not version:
            raise ValueError(f"metric {metric_id} must have a version")
        results.append(MetricResult(metric_id, version, value))
    return EvaluationReport(len(query_metrics), labels, tuple(results))


def _item_distance(
    first: str,
    second: str,
    genres_by_item: Mapping[str, Sequence[str]],
    themes_by_item: Mapping[str, Sequence[str]],
    embeddings_by_item: Mapping[str, Sequence[float]] | None,
) -> float:
    first_tags = set(genres_by_item.get(first, ())) | set(themes_by_item.get(first, ()))
    second_tags = set(genres_by_item.get(second, ())) | set(themes_by_item.get(second, ()))
    union = first_tags | second_tags
    if union:
        return 1.0 - len(first_tags & second_tags) / len(union)
    if embeddings_by_item is None:
        return 0.0
    return _cosine_distance(embeddings_by_item.get(first), embeddings_by_item.get(second))


def _cosine_distance(first: Sequence[float] | None, second: Sequence[float] | None) -> float:
    if first is None or second is None or len(first) != len(second) or not first:
        return 0.0
    if any(not math.isfinite(value) for value in (*first, *second)):
        raise ValueError("embeddings must contain finite values")
    first_norm = math.sqrt(sum(value * value for value in first))
    second_norm = math.sqrt(sum(value * value for value in second))
    if first_norm == 0.0 or second_norm == 0.0:
        return 0.0
    similarity = sum(left * right for left, right in zip(first, second)) / (first_norm * second_norm)
    return 1.0 - max(-1.0, min(1.0, similarity))


def _unique_prefix(values: Sequence[str], k: int) -> list[str]:
    return _unique_all(values)[:k]


def _unique_all(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _gain(grade: int) -> float:
    return float((2 ** max(grade, 0)) - 1)


def _validate_k(k: int) -> None:
    if isinstance(k, bool) or k < 1:
        raise ValueError("k must be at least 1")


def _is_cold_start_cohort(label: str) -> bool:
    normalized = label.strip().lower().replace("_", "-")
    return normalized in {"new-user", "new-item", "cold-start"}
