from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class QueryEvaluation:
    query_id: str
    recall_at_k: float
    mean_reciprocal_rank: float
    ndcg_at_k: float
    retrieved_count: int
    relevant_count: int


@dataclass(frozen=True)
class EvaluationReport:
    query_count: int
    mean_recall_at_k: float
    mean_reciprocal_rank: float
    mean_ndcg_at_k: float


def recall_at_k(
    retrieved_ids: Sequence[str],
    relevance: Mapping[str, int],
    *,
    k: int = 10,
    minimum_grade: int = 1,
) -> float:
    """Return the fraction of relevant documents found in the first k results."""
    _validate_k(k)
    relevant_ids = {document_id for document_id, grade in relevance.items() if grade >= minimum_grade}
    if not relevant_ids:
        return 0.0
    retrieved = set(_unique_prefix(retrieved_ids, k))
    return len(retrieved & relevant_ids) / len(relevant_ids)


def mean_reciprocal_rank(
    retrieved_ids: Sequence[str],
    relevance: Mapping[str, int],
    *,
    k: int = 10,
    minimum_grade: int = 1,
) -> float:
    """Return the reciprocal rank of the first relevant result, or zero."""
    _validate_k(k)
    relevant_ids = {document_id for document_id, grade in relevance.items() if grade >= minimum_grade}
    for rank, document_id in enumerate(_unique_prefix(retrieved_ids, k), start=1):
        if document_id in relevant_ids:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(
    retrieved_ids: Sequence[str],
    relevance: Mapping[str, int],
    *,
    k: int = 10,
) -> float:
    """Return graded normalized discounted cumulative gain for the first k results."""
    _validate_k(k)
    retrieved = _unique_prefix(retrieved_ids, k)
    actual = sum(_gain(relevance.get(document_id, 0)) / math.log2(rank + 1) for rank, document_id in enumerate(retrieved, start=1))
    ideal_grades = sorted(relevance.values(), reverse=True)[:k]
    ideal = sum(_gain(grade) / math.log2(rank + 1) for rank, grade in enumerate(ideal_grades, start=1))
    if ideal == 0.0:
        return 0.0
    return actual / ideal


def evaluate_query(
    query_id: str,
    retrieved_ids: Sequence[str],
    relevance: Mapping[str, int],
    *,
    k: int = 10,
    minimum_grade: int = 1,
) -> QueryEvaluation:
    """Calculate all standard retrieval metrics for one judged query."""
    _validate_k(k)
    return QueryEvaluation(
        query_id=query_id,
        recall_at_k=recall_at_k(retrieved_ids, relevance, k=k, minimum_grade=minimum_grade),
        mean_reciprocal_rank=mean_reciprocal_rank(
            retrieved_ids,
            relevance,
            k=k,
            minimum_grade=minimum_grade,
        ),
        ndcg_at_k=ndcg_at_k(retrieved_ids, relevance, k=k),
        retrieved_count=len(_unique_prefix(retrieved_ids, k)),
        relevant_count=sum(grade >= minimum_grade for grade in relevance.values()),
    )


def evaluate_run(
    retrieved_by_query: Mapping[str, Sequence[str]],
    relevance_by_query: Mapping[str, Mapping[str, int]],
    *,
    k: int = 10,
    minimum_grade: int = 1,
) -> EvaluationReport:
    """Average metrics across a deterministic set of judged queries."""
    _validate_k(k)
    query_ids = sorted(relevance_by_query)
    evaluations = [
        evaluate_query(
            query_id,
            retrieved_by_query.get(query_id, ()),
            relevance_by_query[query_id],
            k=k,
            minimum_grade=minimum_grade,
        )
        for query_id in query_ids
    ]
    if not evaluations:
        return EvaluationReport(0, 0.0, 0.0, 0.0)
    count = len(evaluations)
    return EvaluationReport(
        query_count=count,
        mean_recall_at_k=sum(item.recall_at_k for item in evaluations) / count,
        mean_reciprocal_rank=sum(item.mean_reciprocal_rank for item in evaluations) / count,
        mean_ndcg_at_k=sum(item.ndcg_at_k for item in evaluations) / count,
    )


def _unique_prefix(document_ids: Sequence[str], k: int) -> list[str]:
    return list(dict.fromkeys(document_ids))[:k]


def _gain(grade: int) -> float:
    return float((2**max(grade, 0)) - 1)


def _validate_k(k: int) -> None:
    if k < 1:
        raise ValueError("k must be at least 1")
