import json
import math

import pytest

from app.evaluation.metrics import (
    MetricResult,
    build_evaluation_report,
    calibration_error,
    catalog_coverage,
    evaluate_query,
    intra_list_diversity,
    mean_reciprocal_rank,
    ndcg_at_k,
    negative_feedback_rate,
    policy_violation_rate,
    recall_at_k,
    unique_creator_coverage,
)


def test_retrieval_metrics_are_stable_and_deduplicate_candidates() -> None:
    relevance = {"a": 3, "b": 2, "c": 1}
    retrieved = ["a", "a", "noise", "b", "c"]

    assert recall_at_k(retrieved, relevance, k=3) == pytest.approx(2 / 3)
    assert mean_reciprocal_rank(retrieved, relevance, k=3) == pytest.approx(1.0)
    assert ndcg_at_k(retrieved, relevance, k=3) == pytest.approx(
        8.5 / (7.0 + 3.0 / math.log2(3) + 0.5)
    )
    assert evaluate_query("q1", retrieved, relevance, k=3).retrieved_count == 3


def test_coverage_uses_explicit_catalog_denominators() -> None:
    catalog = ["a", "b", "c", "d"]
    creators = {"a": "one", "b": "one", "c": "two", "d": "three"}
    assert catalog_coverage(["a", "a", "unknown"], catalog) == pytest.approx(0.25)
    assert unique_creator_coverage(["a", "b", "c"], catalog, creators) == pytest.approx(2 / 3)
    assert catalog_coverage([], []) == 0.0
    with pytest.raises(ValueError, match="incomplete"):
        unique_creator_coverage(["a"], catalog, {"a": "one"})


def test_diversity_handles_metadata_and_zero_vectors() -> None:
    assert intra_list_diversity(
        ["a", "b"], {"a": ["puzzle"], "b": ["racing"]}, {"a": [], "b": []}
    ) == 1.0
    assert intra_list_diversity(
        ["a", "b"], {"a": [], "b": []}, {"a": [], "b": []},
        embeddings_by_item={"a": [0.0, 0.0], "b": [1.0, 0.0]},
    ) == 0.0
    assert intra_list_diversity([], {}, {}) == 0.0


def test_calibration_feedback_and_policy_metrics() -> None:
    assert calibration_error([0.1, 0.9], [0, 1], bin_count=2) == pytest.approx(0.1)
    assert negative_feedback_rate([False, True, False, True]) == 0.5
    assert policy_violation_rate([False, True, False]) == pytest.approx(1 / 3)
    assert negative_feedback_rate([]) == 0.0
    assert policy_violation_rate([]) == 0.0


def test_report_is_stable_and_explicit_for_empty_input() -> None:
    report = build_evaluation_report(
        [], {"catalog_coverage": 0.0, "recall_at_k": 0.0}, cohort_labels=["cold-start"],
    )
    assert report.query_count == 0
    assert report.metric_versions == {"catalog_coverage": "v1", "recall_at_k": "v1"}
    assert json.loads(report.serialize()) == {
        "cohort_labels": ["cold-start"],
        "metric_versions": {"catalog_coverage": "v1", "recall_at_k": "v1"},
        "metrics": {"catalog_coverage": 0.0, "recall_at_k": 0.0},
        "query_count": 0,
    }
    with pytest.raises(ValueError, match="unique"):
        build_evaluation_report([], {}, cohort_labels=["x", "x"])
    with pytest.raises(ValueError, match="unique"):
        build_evaluation_report(
            [], [MetricResult("recall_at_k", "v1", 0.5), MetricResult("recall_at_k", "v1", 0.5)]
        )
    with pytest.raises(ValueError, match="finite"):
        build_evaluation_report([], {"recall_at_k": float("nan")})


def test_invalid_inputs_fail_clearly() -> None:
    with pytest.raises(ValueError, match="k"):
        recall_at_k([], {}, k=0)
    with pytest.raises(ValueError, match="equal lengths"):
        calibration_error([0.5], [])
    with pytest.raises(ValueError, match="probabilities"):
        calibration_error([float("inf")], [1])
    with pytest.raises(ValueError, match="binary"):
        calibration_error([0.5], [2])
