from __future__ import annotations

import pytest

from app.resolution.evaluation import (
    abstention_accuracy,
    action_validity,
    citation_precision,
    compare_ranking_stages,
    evaluate_resolution,
    supported_claim_rate,
)


def test_metrics_match_hand_computed_values():
    report = evaluate_resolution(
        cited_labels=["[E1]", "[E9]", "[E1]"],
        authorized_labels=["[E1]", "[E2]"],
        supported=[True, False, True],
        predicted_abstentions=[False, True, False],
        expected_abstentions=[False, False, False],
        action_types=["draft_agent_response", "delete_events"],
        allowed_action_types=[["draft_agent_response"], ["route_to_human"]],
        latency_ms=125.5,
        input_tokens=100,
        output_tokens=40,
        estimated_cost=0.002,
    )
    assert report.metrics.citation_precision == pytest.approx(2 / 3)
    assert report.metrics.supported_claim_rate == pytest.approx(2 / 3)
    assert report.metrics.abstention_accuracy == pytest.approx(2 / 3)
    assert report.metrics.action_validity == pytest.approx(0.5)
    assert (report.latency_ms, report.input_tokens, report.output_tokens) == (125.5, 100, 40)


def test_empty_denominators_are_zero():
    assert citation_precision([], ["[E1]"]) == 0.0
    assert supported_claim_rate([]) == 0.0
    assert abstention_accuracy([], []) == 0.0
    assert action_validity([], []) == 0.0


@pytest.mark.parametrize("field", ["latency_ms", "input_tokens", "output_tokens", "estimated_cost"])
def test_negative_telemetry_is_rejected(field):
    values = dict(
        cited_labels=[], authorized_labels=[], supported=[], predicted_abstentions=[],
        expected_abstentions=[], action_types=[], allowed_action_types=[], latency_ms=0,
        input_tokens=0, output_tokens=0, estimated_cost=0,
    )
    values[field] = -1
    with pytest.raises(ValueError, match="non-negative"):
        evaluate_resolution(**values)


def test_ranking_comparison_matches_hand_computed_values():
    report = compare_ranking_stages(
        baseline_ids=["doc-c", "doc-b", "doc-a"],
        reranked_ids=["doc-a", "doc-b", "doc-c"],
        relevance={"doc-a": 2, "doc-b": 1},
        baseline_supported_document_ids=["doc-b"],
        reranked_supported_document_ids=["doc-a", "doc-b"],
        baseline_cost=0.001,
        reranked_cost=0.003,
        baseline_latency_ms=10,
        reranked_latency_ms=25,
        k=2,
    )
    assert report.baseline.recall_at_k == pytest.approx(0.5)
    assert report.reranked.recall_at_k == pytest.approx(1.0)
    assert report.baseline.mean_reciprocal_rank == pytest.approx(0.5)
    assert report.reranked.mean_reciprocal_rank == pytest.approx(1.0)
    assert report.baseline.supported_evidence_rate == pytest.approx(0.5)
    assert report.reranked.supported_evidence_rate == pytest.approx(1.0)
    assert report.deltas.estimated_cost == pytest.approx(0.002)
    assert report.deltas.latency_ms == pytest.approx(15)


def test_ranking_comparison_rejects_mismatched_or_duplicate_ids():
    args = dict(
        baseline_ids=["doc-a"], reranked_ids=["doc-b"], relevance={},
        baseline_supported_document_ids=[], reranked_supported_document_ids=[],
    )
    with pytest.raises(ValueError, match="same document IDs"):
        compare_ranking_stages(**args)
    args["reranked_ids"] = ["doc-a", "doc-a"]
    with pytest.raises(ValueError, match="unique"):
        compare_ranking_stages(**args)


@pytest.mark.parametrize("field", ["baseline_cost", "reranked_cost", "baseline_latency_ms", "reranked_latency_ms"])
def test_ranking_comparison_rejects_negative_cost_or_latency(field):
    args = dict(
        baseline_ids=[], reranked_ids=[], relevance={},
        baseline_supported_document_ids=[], reranked_supported_document_ids=[],
    )
    args[field] = -1
    with pytest.raises(ValueError, match="non-negative"):
        compare_ranking_stages(**args)
