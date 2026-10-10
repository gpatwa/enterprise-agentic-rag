import time

from app.candidates.contracts import Candidate, CandidateSourceResult, Degradation
from app.candidates.orchestrator import (
    CandidateOrchestrator,
    OrchestrationConfig,
    SourceSpec,
)


def _source(name, ids=(), *, version=None):
    source_version = version or f"{name}-v1"

    def retrieve(*, tenant_id, request_id, limit):
        return CandidateSourceResult(
            source=name,
            source_version=source_version,
            tenant_id=tenant_id,
            request_id=request_id,
            candidates=tuple(
                Candidate(
                    experience_id=experience_id,
                    tenant_id=tenant_id,
                    source=name,
                    source_version=source_version,
                    score=1.0 - (index * 0.1),
                    reason_codes=("source_match",),
                )
                for index, experience_id in enumerate(ids[:limit])
            ),
        )

    return retrieve


def _spec(name, *, quota=20, timeout=0.25):
    return SourceSpec(source=name, source_version=f"{name}-v1", quota=quota, timeout_seconds=timeout)


def test_sources_run_in_parallel_and_output_follows_declared_order():
    def slow(**kwargs):
        time.sleep(0.04)
        return _source("slow", ("exp-2",))(**kwargs)

    def fast(**kwargs):
        return _source("fast", ("exp-1",))(**kwargs)

    result = CandidateOrchestrator(
        {"slow": slow, "fast": fast},
        [_spec("slow"), _spec("fast")],
    ).run(tenant_id="tenant-1", request_id="request-1")
    assert [item.source for item in result.trace.source_results] == ["slow", "fast"]
    assert [item.experience_id for item in result.fusion.candidates] == ["exp-1", "exp-2"]


def test_failure_and_timeout_degrade_without_blocking_healthy_source():
    def fail(**kwargs):
        raise RuntimeError("provider payload must not escape")

    def timeout(**kwargs):
        time.sleep(0.05)
        return _source("timeout", ("exp-timeout",))(**kwargs)

    result = CandidateOrchestrator(
        {"fail": fail, "timeout": timeout, "healthy": _source("healthy", ("exp-1",))},
        [_spec("fail"), _spec("timeout", timeout=0.001), _spec("healthy")],
    ).run(tenant_id="tenant-1", request_id="request-1")
    statuses = {item.source: item for item in result.trace.source_results}
    assert statuses["fail"].degradation is Degradation.FAILURE
    assert statuses["timeout"].degradation is Degradation.TIMEOUT
    assert statuses["fail"].error_code == "source_failure"
    assert [item.experience_id for item in result.fusion.candidates] == ["exp-1"]


def test_quota_global_limit_and_boundary_eligibility_are_enforced():
    result = CandidateOrchestrator(
        {"one": _source("one", ("exp-1", "exp-2", "exp-3"))},
        [_spec("one", quota=2)],
        OrchestrationConfig(global_limit=1),
    ).run(
        tenant_id="tenant-1",
        request_id="request-1",
        is_eligible=lambda experience_id, tenant_id: experience_id != "exp-1",
    )
    assert len(result.trace.source_results[0].candidates) == 2
    assert [item.experience_id for item in result.fusion.candidates] == ["exp-2"]


def test_trace_is_redacted_and_deterministic():
    orchestrator = CandidateOrchestrator(
        {"one": _source("one", ("exp-1",))},
        [_spec("one")],
    )
    first = orchestrator.run(tenant_id="tenant-1", request_id="request-1")
    second = orchestrator.run(tenant_id="tenant-1", request_id="request-1")
    assert first.trace == second.trace
    assert first.trace.tenant_digest != "tenant-1"
    assert len(first.trace.tenant_digest) == 64
    assert len(first.trace.request_digest) == 64
