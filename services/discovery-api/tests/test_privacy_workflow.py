from datetime import datetime, timedelta, timezone

import pytest

from app.domain.models import ConsentState
from app.privacy.workflow import PrivacyOperation, PrivacyRecord, PrivacyRequest, PrivacySource, PrivacyWorkflow

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)


def _record(source: PrivacySource, record_id: str, *, user_id: str = "user-1", created_at: datetime = NOW, payload: dict[str, object] | None = None) -> PrivacyRecord:
    return PrivacyRecord(tenant_id="tenant-a", subject_id=user_id, record_id=record_id, source=source, created_at=created_at, payload=payload or {"genre": "adventure", "email": "hidden@example.com"})


def _request(operation: PrivacyOperation, *, consent_state: ConsentState = ConsentState.PERSONALIZATION_ALLOWED, **changes: object) -> PrivacyRequest:
    values: dict[str, object] = dict(tenant_id="tenant-a", user_id="user-1", operation=operation, consent_state=consent_state, requested_at=NOW, retention_days=30, confirmation_token="confirm-token-123456")
    values.update(changes)
    return PrivacyRequest(**values)


def test_withdrawal_removes_personal_records_and_tombstones_derived_data() -> None:
    records = tuple(_record(source, source.value) for source in PrivacySource)
    result = PrivacyWorkflow().execute(records, _request(PrivacyOperation.WITHDRAW_CONSENT, consent_state=ConsentState.PERSONALIZATION_DENIED))

    assert {item.source for item in result.remaining} == {PrivacySource.CATALOG}
    assert result.evidence.deleted_count == 4
    assert result.evidence.tombstoned_count == 2
    assert len(result.tombstones) == 2
    assert len(PrivacyWorkflow().evidence_log) == 0


def test_retention_deletes_old_canonical_records_without_recreating_derived_content() -> None:
    old = _record(PrivacySource.EVENT, "old", created_at=NOW - timedelta(days=31))
    old_feature = _record(PrivacySource.FEATURE, "old-feature", created_at=NOW - timedelta(days=31))
    fresh = _record(PrivacySource.PROFILE, "fresh")
    result = PrivacyWorkflow().execute((old, old_feature, fresh), _request(PrivacyOperation.RETAIN))

    assert result.remaining == (fresh,)
    assert result.evidence.deleted_count == 1
    assert result.evidence.tombstoned_count == 1


def test_export_is_bounded_approved_and_redacted() -> None:
    record = _record(PrivacySource.PROFILE, "profile", payload={"genre": "puzzle", "email": "secret@example.com", "score": 4})
    request = _request(PrivacyOperation.EXPORT, approved_export_fields=("genre", "email", "score"), max_export_records=1)
    result = PrivacyWorkflow().execute((record,), request)

    assert result.exported[0].fields == {"genre": "puzzle", "score": 4}
    assert result.exported[0].record_ref != record.record_id
    assert result.evidence.exported_count == 1
    assert "email" not in result.exported[0].model_dump_json()


def test_scope_and_confirmation_contracts_fail_closed() -> None:
    with pytest.raises(ValueError, match="approved fields"):
        _request(PrivacyOperation.EXPORT, approved_export_fields=())
    with pytest.raises(ValueError, match="denied consent"):
        _request(PrivacyOperation.WITHDRAW_CONSENT)
    other_user = _record(PrivacySource.EVENT, "event", user_id="other")
    result = PrivacyWorkflow().execute((other_user,), _request(PrivacyOperation.DELETE))
    assert result.remaining == (other_user,)
