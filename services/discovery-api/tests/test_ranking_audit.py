from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.audit.ranking import (
    AuditOutcome,
    NoOpRankingAuditWriter,
    PolicyOutcome,
    RankingAuditRecord,
    RankingAuditWriter,
    checksum,
    digest,
)


def _record(event_id: str = "event-1", **overrides: object) -> RankingAuditRecord:
    values: dict[str, object] = {
        "event_id": event_id,
        "tenant_digest": digest("tenant-a"),
        "request_digest": digest("request-a"),
        "decision_digest": digest("decision-a"),
        "outcome": AuditOutcome.COMPLETED,
        "eligibility_outcome": PolicyOutcome.ALLOWED,
        "policy_outcome": PolicyOutcome.ALLOWED,
        "candidate_count": 5,
        "eligible_count": 4,
        "selected_count": 3,
        "reason_codes": ("hybrid", "policy_allowed"),
        "component_versions": ("retrieval-v1", "ranker-v1"),
        "evidence": ("rrf", "eligible",),
        "occurred_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "record_checksum": checksum({"decision": "digest-only", "count": 3}),
    }
    values.update(overrides)
    return RankingAuditRecord(**values)


def test_record_is_immutable_and_serialization_is_stable() -> None:
    record = _record()
    assert record.serialize() == _record().serialize()
    with pytest.raises((TypeError, ValidationError)):
        record.outcome = AuditOutcome.FAILED  # type: ignore[misc]


def test_writer_is_idempotent_and_rejects_conflicts() -> None:
    writer = RankingAuditWriter(max_records=2)
    record = _record()
    assert writer.append(record) is True
    assert writer.append(record) is False
    with pytest.raises(ValueError, match="different audit evidence"):
        writer.append(_record(outcome=AuditOutcome.DEGRADED))
    assert writer.readback() == (record,)


def test_writer_readback_is_sorted_and_bounded() -> None:
    writer = RankingAuditWriter(max_records=2)
    writer.append_many((_record("event-2"), _record("event-1")))
    assert tuple(item.event_id for item in writer.readback()) == ("event-1", "event-2")
    with pytest.raises(ValueError, match="capacity"):
        writer.append(_record("event-3"))


def test_sensitive_checksum_fields_and_unredacted_evidence_are_rejected() -> None:
    with pytest.raises(ValueError, match="sensitive"):
        checksum({"query": "secret player history"})
    with pytest.raises(ValidationError):
        _record(evidence=("raw_query",))


def test_noop_writer_validates_but_does_not_retain() -> None:
    writer = NoOpRankingAuditWriter()
    assert writer.append(_record()) is False
    assert writer.readback() == ()


def test_counts_and_failed_reasons_are_fail_closed() -> None:
    with pytest.raises(ValidationError):
        _record(eligible_count=6)
    with pytest.raises(ValidationError):
        _record(outcome=AuditOutcome.FAILED, reason_codes=())
