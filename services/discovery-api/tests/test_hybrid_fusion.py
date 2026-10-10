import pytest

from app.candidates.contracts import Candidate, CandidateSourceResult, Degradation
from app.search.fusion import FusionConfig, FusionMethod, fuse_candidates


def _result(source, candidates=(), *, degradation=Degradation.OK, error_code=None):
    return CandidateSourceResult(
        source=source,
        source_version=f"{source}-v1",
        tenant_id="tenant-1",
        request_id="request-1",
        candidates=tuple(candidates),
        degradation=degradation,
        error_code=error_code,
    )


def _candidate(source, experience_id, score, reasons=("match",)):
    return Candidate(
        experience_id=experience_id,
        tenant_id="tenant-1",
        source=source,
        source_version=f"{source}-v1",
        score=score,
        reason_codes=reasons,
    )


def test_rrf_deduplicates_preserves_evidence_and_breaks_ties_by_id():
    result = fuse_candidates(
        [
            _result("lexical", [_candidate("lexical", "exp-b", 1.0), _candidate("lexical", "exp-a", 0.8)]),
            _result("vector", [_candidate("vector", "exp-a", 0.9), _candidate("vector", "exp-b", 0.7)]),
        ],
        tenant_id="tenant-1",
        request_id="request-1",
        config=FusionConfig(rrf_k=1),
    )
    assert [item.experience_id for item in result.candidates] == ["exp-a", "exp-b"]
    assert len(result.candidates[0].source_evidence) == 2
    assert "lexical:match" in result.candidates[0].reason_codes


def test_weighted_fusion_is_explicit_and_bounded():
    result = fuse_candidates(
        [_result("lexical", [_candidate("lexical", "exp-1", 0.5)])],
        tenant_id="tenant-1",
        request_id="request-1",
        config=FusionConfig(method=FusionMethod.WEIGHTED, source_weights={"lexical": 2.0}, limit=1),
    )
    assert result.candidates[0].score == 1.0


def test_degraded_source_does_not_discard_healthy_candidates():
    result = fuse_candidates(
        [
            _result("lexical", [_candidate("lexical", "exp-1", 0.8)]),
            _result("vector", degradation=Degradation.TIMEOUT, error_code="timeout"),
        ],
        tenant_id="tenant-1",
        request_id="request-1",
    )
    assert [item.experience_id for item in result.candidates] == ["exp-1"]
    assert result.degraded_sources == ("vector",)


def test_scope_version_and_boundary_eligibility_are_enforced():
    with pytest.raises(ValueError, match="version"):
        fuse_candidates(
            [_result("lexical", [_candidate("lexical", "exp-1", 0.8)])],
            tenant_id="tenant-1",
            request_id="request-1",
            expected_source_versions={"lexical": "lexical-v2"},
        )

    result = fuse_candidates(
        [_result("lexical", [_candidate("lexical", "exp-1", 0.8), _candidate("lexical", "exp-2", 0.7)])],
        tenant_id="tenant-1",
        request_id="request-1",
        is_eligible=lambda experience_id, _: experience_id == "exp-2",
    )
    assert [item.experience_id for item in result.candidates] == ["exp-2"]
