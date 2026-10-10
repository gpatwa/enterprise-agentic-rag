import pytest
from pydantic import ValidationError

from app.candidates.contracts import (
    Candidate,
    CandidateBatch,
    CandidateSourceResult,
    Degradation,
    SourceQuota,
)


def _candidate(**overrides):
    values = dict(
        experience_id="exp-1", tenant_id="tenant-1", source="lexical",
        source_version="v1", score=0.8, reason_codes=("exact_title",),
    )
    values.update(overrides)
    return Candidate(**values)


def test_source_results_are_scoped_versioned_and_deterministic():
    result = CandidateSourceResult(
        source="lexical", source_version="v1", tenant_id="tenant-1", request_id="req-1",
        candidates=(_candidate(),),
    )
    batch = CandidateBatch(
        tenant_id="tenant-1", request_id="req-1", candidates=result.candidates,
        quotas=(SourceQuota(source="lexical", limit=20),),
    )
    assert batch.model_dump(mode="json")["candidates"][0]["experience_id"] == "exp-1"


def test_degraded_results_are_explicit_and_empty_has_no_candidates():
    failed = CandidateSourceResult(
        source="vector", source_version="v1", tenant_id="tenant-1", request_id="req-1",
        degradation=Degradation.TIMEOUT, error_code="provider_timeout",
    )
    empty = CandidateSourceResult(
        source="lexical", source_version="v1", tenant_id="tenant-1", request_id="req-1",
        degradation=Degradation.EMPTY,
    )
    assert failed.error_code == "provider_timeout"
    assert not empty.candidates


@pytest.mark.parametrize(
    "factory",
    [
        lambda: CandidateSourceResult(
            source="lexical", source_version="v1", tenant_id="tenant-1", request_id="req-1",
            candidates=(_candidate(source="vector"),),
        ),
        lambda: CandidateBatch(
            tenant_id="tenant-1", request_id="req-1",
            candidates=(_candidate(), _candidate()),
        ),
    ],
)
def test_scope_and_duplicates_are_rejected(factory):
    with pytest.raises(ValidationError):
        factory()
