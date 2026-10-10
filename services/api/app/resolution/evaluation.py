"""Pure, provider-neutral metrics for offline resolution evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from app.search.evaluation import mean_reciprocal_rank, ndcg_at_k, recall_at_k


@dataclass(frozen=True)
class ResolutionMetrics:
    citation_precision: float
    supported_claim_rate: float
    abstention_accuracy: float
    action_validity: float


@dataclass(frozen=True)
class ResolutionEvaluationReport:
    metrics: ResolutionMetrics
    latency_ms: float
    input_tokens: int
    output_tokens: int
    estimated_cost: float


@dataclass(frozen=True)
class RankingStageMetrics:
    """Quality and operational measurements for one ranking stage."""

    recall_at_k: float
    mean_reciprocal_rank: float
    ndcg_at_k: float
    supported_evidence_rate: float
    estimated_cost: float
    latency_ms: float


@dataclass(frozen=True)
class RankingComparisonReport:
    """Deterministic comparison of the baseline and reranked result lists."""

    k: int
    baseline: RankingStageMetrics
    reranked: RankingStageMetrics
    deltas: RankingStageMetrics


def supported_evidence_rate(
    retrieved_ids: Sequence[str],
    supported_document_ids: Sequence[str],
    *,
    k: int = 10,
) -> float:
    """Return the fraction of unique top-K results with supported evidence."""
    if k < 1:
        raise ValueError("k must be at least 1")
    retrieved = list(dict.fromkeys(retrieved_ids))[:k]
    if not retrieved:
        return 0.0
    supported = set(supported_document_ids)
    return sum(document_id in supported for document_id in retrieved) / len(retrieved)


def compare_ranking_stages(
    *,
    baseline_ids: Sequence[str],
    reranked_ids: Sequence[str],
    relevance: Mapping[str, int],
    baseline_supported_document_ids: Sequence[str],
    reranked_supported_document_ids: Sequence[str],
    baseline_cost: float = 0.0,
    reranked_cost: float = 0.0,
    baseline_latency_ms: float = 0.0,
    reranked_latency_ms: float = 0.0,
    k: int = 10,
    minimum_grade: int = 1,
) -> RankingComparisonReport:
    """Compare two result lists without invoking ranking or model providers."""
    if k < 1:
        raise ValueError("k must be at least 1")
    if set(baseline_ids) != set(reranked_ids):
        raise ValueError("baseline and reranked results must contain the same document IDs")
    if len(set(baseline_ids)) != len(baseline_ids) or len(set(reranked_ids)) != len(reranked_ids):
        raise ValueError("ranking results must contain unique document IDs")
    for name, value in (
        ("baseline_cost", baseline_cost),
        ("reranked_cost", reranked_cost),
        ("baseline_latency_ms", baseline_latency_ms),
        ("reranked_latency_ms", reranked_latency_ms),
    ):
        _validate_non_negative(name, value)

    def metrics(ids: Sequence[str], supported: Sequence[str], cost: float, latency: float) -> RankingStageMetrics:
        return RankingStageMetrics(
            recall_at_k(ids, relevance, k=k, minimum_grade=minimum_grade),
            mean_reciprocal_rank(ids, relevance, k=k, minimum_grade=minimum_grade),
            ndcg_at_k(ids, relevance, k=k),
            supported_evidence_rate(ids, supported, k=k),
            cost,
            latency,
        )

    baseline = metrics(baseline_ids, baseline_supported_document_ids, baseline_cost, baseline_latency_ms)
    reranked = metrics(reranked_ids, reranked_supported_document_ids, reranked_cost, reranked_latency_ms)
    return RankingComparisonReport(
        k=k,
        baseline=baseline,
        reranked=reranked,
        deltas=RankingStageMetrics(
            reranked.recall_at_k - baseline.recall_at_k,
            reranked.mean_reciprocal_rank - baseline.mean_reciprocal_rank,
            reranked.ndcg_at_k - baseline.ndcg_at_k,
            reranked.supported_evidence_rate - baseline.supported_evidence_rate,
            reranked.estimated_cost - baseline.estimated_cost,
            reranked.latency_ms - baseline.latency_ms,
        ),
    )


def citation_precision(cited_labels: Sequence[str], authorized_labels: Sequence[str]) -> float:
    """Return the fraction of cited labels that are authorized."""
    cited = list(cited_labels)
    if not cited:
        return 0.0
    authorized = set(authorized_labels)
    return sum(label in authorized for label in cited) / len(cited)


def supported_claim_rate(supported: Sequence[bool]) -> float:
    """Return the fraction of claims supported by authorized evidence."""
    if not supported:
        return 0.0
    return sum(supported) / len(supported)


def abstention_accuracy(predicted: Sequence[bool], expected: Sequence[bool]) -> float:
    """Return exact-match accuracy for abstention decisions."""
    if len(predicted) != len(expected):
        raise ValueError("predicted and expected abstentions must have the same length")
    if not expected:
        return 0.0
    return sum(actual == target for actual, target in zip(predicted, expected)) / len(expected)


def action_validity(action_types: Sequence[str | None], allowed_types: Sequence[Sequence[str]]) -> float:
    """Return the fraction of proposed actions allowed by their case policy."""
    if len(action_types) != len(allowed_types):
        raise ValueError("action_types and allowed_types must have the same length")
    if not action_types:
        return 0.0
    return sum(action is not None and action in allowed for action, allowed in zip(action_types, allowed_types)) / len(action_types)


def evaluate_resolution(
    *,
    cited_labels: Sequence[str],
    authorized_labels: Sequence[str],
    supported: Sequence[bool],
    predicted_abstentions: Sequence[bool],
    expected_abstentions: Sequence[bool],
    action_types: Sequence[str | None],
    allowed_action_types: Sequence[Sequence[str]],
    latency_ms: float,
    input_tokens: int,
    output_tokens: int,
    estimated_cost: float,
) -> ResolutionEvaluationReport:
    """Build a deterministic resolution report from already-collected values."""
    _validate_non_negative("latency_ms", latency_ms)
    _validate_non_negative("input_tokens", input_tokens)
    _validate_non_negative("output_tokens", output_tokens)
    _validate_non_negative("estimated_cost", estimated_cost)
    if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
        raise ValueError("token counts must be integers")
    return ResolutionEvaluationReport(
        metrics=ResolutionMetrics(
            citation_precision(cited_labels, authorized_labels),
            supported_claim_rate(supported),
            abstention_accuracy(predicted_abstentions, expected_abstentions),
            action_validity(action_types, allowed_action_types),
        ),
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost=estimated_cost,
    )


def _validate_non_negative(name: str, value: float | int) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"{name} must be non-negative")
