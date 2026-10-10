from __future__ import annotations

import pytest


def test_recall_at_k_is_fraction_of_relevant_documents_found():
    from app.search.evaluation import recall_at_k

    relevance = {"a": 3, "b": 2, "c": 0, "d": 1}
    assert recall_at_k(["x", "b", "a", "d"], relevance, k=2) == pytest.approx(1 / 3)
    assert recall_at_k(["x", "c"], relevance, k=2) == 0.0


def test_mean_reciprocal_rank_uses_first_relevant_result():
    from app.search.evaluation import mean_reciprocal_rank

    relevance = {"a": 3, "b": 2}
    assert mean_reciprocal_rank(["x", "b", "a"], relevance, k=3) == pytest.approx(0.5)
    assert mean_reciprocal_rank(["x", "c"], relevance, k=2) == 0.0


def test_ndcg_at_k_rewards_graded_relevance_and_normalizes_by_ideal_order():
    from app.search.evaluation import ndcg_at_k

    relevance = {"a": 3, "b": 2, "c": 1}
    assert ndcg_at_k(["a", "b", "c"], relevance, k=3) == pytest.approx(1.0)
    assert ndcg_at_k(["c", "b", "a"], relevance, k=3) < 1.0
    assert ndcg_at_k(["x", "y"], {"a": 0}, k=2) == 0.0


def test_evaluate_run_is_deterministic_and_handles_missing_results():
    from app.search.evaluation import evaluate_run

    report = evaluate_run(
        {"q-1": ["a", "b"], "q-2": []},
        {"q-1": {"a": 3, "b": 0}, "q-2": {"c": 2}},
        k=2,
    )

    assert report.query_count == 2
    assert report.mean_recall_at_k == pytest.approx(0.5)
    assert report.mean_reciprocal_rank == pytest.approx(0.5)
    assert report.mean_ndcg_at_k == pytest.approx(0.5)


def test_metrics_reject_non_positive_k():
    from app.search.evaluation import ndcg_at_k

    with pytest.raises(ValueError, match="k must be at least 1"):
        ndcg_at_k(["a"], {"a": 1}, k=0)
