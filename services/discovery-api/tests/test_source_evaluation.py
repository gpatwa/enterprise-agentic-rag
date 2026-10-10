import json

import pytest

from app.candidates.contracts import Candidate, CandidateSourceResult, CandidateTrace, Degradation
from app.evaluation.metrics import (
    SourceEvaluationCase,
    build_source_evaluation_report,
)


def _trace(*results: CandidateSourceResult) -> CandidateTrace:
    return CandidateTrace(
        tenant_digest="a" * 64,
        request_digest="b" * 64,
        source_results=results,
    )


def _result(source: str, ids: tuple[str, ...], *, degradation=Degradation.OK) -> CandidateSourceResult:
    version = f"{source}-v1"
    return CandidateSourceResult(
        source=source,
        source_version=version,
        tenant_id="tenant-1",
        request_id="request-1",
        candidates=tuple(
            Candidate(
                experience_id=item_id,
                tenant_id="tenant-1",
                source=source,
                source_version=version,
                score=1.0,
                reason_codes=("fixture",),
            )
            for item_id in ids
        ),
        degradation=degradation,
        error_code="source_failure" if degradation is Degradation.FAILURE else None,
    )


def _metric(report, metric_id, source, cohort):
    return next(
        metric for metric in report.metrics
        if (metric.metric_id, metric.source, metric.cohort) == (metric_id, source, cohort)
    )


def test_source_metrics_attribute_overlap_without_double_counting():
    report = build_source_evaluation_report([
        SourceEvaluationCase(
            query_id="q1",
            trace=_trace(_result("lexical", ("a", "b")), _result("trending", ("b", "c"))),
            relevance={"a": 1, "b": 1, "c": 0},
            cohort_labels=("new-user",),
        )
    ], k=2)

    assert _metric(report, "source_recall_at_k", "lexical", "all").value == pytest.approx(1.0)
    assert _metric(report, "source_catalog_coverage", "lexical", "all").value == pytest.approx(2 / 3)
    assert _metric(report, "source_overlap_rate", "lexical", "all").value == pytest.approx(0.5)
    assert _metric(report, "cold_start_quality", "lexical", "new-user").value == pytest.approx(1.0)
    assert report.source_labels == ("lexical", "trending")


def test_degraded_sources_are_explicit_and_empty_sources_are_not_degraded():
    report = build_source_evaluation_report([
        SourceEvaluationCase(
            query_id="q1",
            trace=_trace(
                _result("healthy", ("a",)),
                _result("empty", (), degradation=Degradation.EMPTY),
                _result("failed", (), degradation=Degradation.FAILURE),
            ),
            relevance={"a": 1},
            cohort_labels=("new-item",),
        )
    ])
    failed = _metric(report, "source_recall_at_k", "failed", "new-item")
    empty = _metric(report, "source_recall_at_k", "empty", "new-item")
    assert failed.value == 0.0 and failed.degraded_query_count == 1
    assert empty.value == 0.0 and empty.degraded_query_count == 0
    assert _metric(report, "cold_start_quality", "healthy", "new-item").version == "v1"


def test_report_is_stable_and_ambiguous_joins_fail_closed():
    case = SourceEvaluationCase(
        query_id="q1",
        trace=_trace(_result("lexical", ("a",))),
        relevance={"a": 1},
        cohort_labels=("cold-start",),
    )
    report = build_source_evaluation_report([case])
    assert json.loads(report.serialize()) == json.loads(report.serialize())
    with pytest.raises(ValueError, match="query IDs"):
        build_source_evaluation_report([case, case])
    with pytest.raises(ValueError, match="same source labels"):
        build_source_evaluation_report([
            case,
            SourceEvaluationCase(
                query_id="q2",
                trace=_trace(_result("trending", ("a",))),
                relevance={"a": 1},
            ),
        ])
    with pytest.raises(ValueError, match="cohort labels"):
        SourceEvaluationCase(
            query_id="q2",
            trace=case.trace,
            relevance={"a": 1},
            cohort_labels=("new-user", "new-user"),
        )


def test_empty_input_is_explicit_and_deterministic():
    report = build_source_evaluation_report([])
    assert report.query_count == 0
    assert report.metrics == ()
    assert report.to_dict()["cohort_labels"] == []
