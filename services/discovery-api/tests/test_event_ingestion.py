from datetime import datetime, timedelta, timezone

import pytest

from app.domain.models import ConsentState
from app.events.ingestion import InteractionIngestion, ReceiptStatus, RejectionReason
from app.events.models import (
    ClickPayload,
    EventType,
    InteractionEvent,
    InteractionEventBatch,
    NavigationPath,
    OrganicNavigationPayload,
)
from packages.platform_contracts.discovery import DiscoveryComponentVersion, DiscoveryRequestContext, ImpressionToken

UTC = timezone.utc
RECEIVED = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


def token(*, issued_at: datetime = RECEIVED, request_id: str = "request-001") -> ImpressionToken:
    context = DiscoveryRequestContext(
        tenant_id="tenant-orbit",
        principal_id="user-001",
        request_id=request_id,
        purpose="recommendation",
        locale="en-US",
        device="web",
    )
    component = DiscoveryComponentVersion(
        component_type="schema", name="discovery", version="v1", digest="a" * 64
    )
    return ImpressionToken.for_context(
        context,
        token_id="token-001",
        issued_at=issued_at,
        expires_at=issued_at + timedelta(minutes=5),
        schema_version="v1",
        components=(component,),
    )


def event(*, event_id: str = "event-001", occurred_at: datetime = RECEIVED, **changes: object) -> InteractionEvent:
    tenant_id = str(changes.get("tenant_id", "tenant-orbit"))
    user_id = str(changes.get("user_id", "user-001"))
    request_id = str(changes.get("request_id", "request-001"))
    values: dict[str, object] = {
        "event_id": event_id,
        "event_type": EventType.CLICK,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "experience_id": "exp-001",
        "request_id": request_id,
        "occurred_at": occurred_at,
        "synthetic": True,
        "consent_state": ConsentState.PERSONALIZATION_ALLOWED,
        "impression_token": token(request_id=request_id).model_copy(update={"tenant_id": tenant_id, "principal_id": user_id}),
        "payload": ClickPayload(target="card"),
    }
    values.update(changes)
    return InteractionEvent(**values)


def batch(*events: InteractionEvent) -> InteractionEventBatch:
    return InteractionEventBatch(batch_id="batch-001", events=events)


def test_accepts_typed_consented_event_and_redacts_receipt() -> None:
    result = InteractionIngestion().ingest(
        batch(event()), tenant_id="tenant-orbit", user_id="user-001", request_id="request-001", received_at=RECEIVED
    )
    assert result.accepted == 1
    assert result.receipts[0].status is ReceiptStatus.ACCEPTED
    assert result.receipts[0].event_ref != "event-001"
    assert len(result.receipts[0].event_ref) == 64
    assert "user-001" not in result.model_dump_json()


def test_replay_is_idempotent_but_conflicting_event_id_is_rejected() -> None:
    ingestion = InteractionIngestion()
    current = batch(event())
    first = ingestion.ingest(current, tenant_id="tenant-orbit", user_id="user-001", request_id="request-001", received_at=RECEIVED)
    replay = ingestion.ingest(current, tenant_id="tenant-orbit", user_id="user-001", request_id="request-001", received_at=RECEIVED)
    conflict = ingestion.ingest(
        batch(event(payload=ClickPayload(target="title"))),
        tenant_id="tenant-orbit", user_id="user-001", request_id="request-001", received_at=RECEIVED,
    )
    assert first.accepted == 1
    assert replay.already_present == 1
    assert conflict.rejected == 1
    assert conflict.receipts[0].reason is RejectionReason.EVENT_ID_CONFLICT


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"tenant_id": "tenant-other"}, RejectionReason.BATCH_TENANT_MISMATCH),
        ({"user_id": "user-other"}, RejectionReason.USER_SCOPE_MISMATCH),
        ({"request_id": "request-other", "impression_token": token(request_id="request-other")}, RejectionReason.REQUEST_SCOPE_MISMATCH),
        ({"consent_state": ConsentState.PERSONALIZATION_DENIED}, RejectionReason.CONSENT_REQUIRED),
        ({"occurred_at": RECEIVED - timedelta(minutes=6), "impression_token": token(issued_at=RECEIVED - timedelta(minutes=10))}, RejectionReason.TIMESTAMP_SKEW),
        ({"impression_token": token(issued_at=RECEIVED + timedelta(minutes=1))}, RejectionReason.IMPRESSION_LINEAGE_INVALID),
    ],
)
def test_scope_consent_time_and_lineage_fail_closed(changes: dict[str, object], reason: RejectionReason) -> None:
    result = InteractionIngestion().ingest(
        batch(event(**changes)), tenant_id="tenant-orbit", user_id="user-001", request_id="request-001", received_at=RECEIVED
    )
    assert result.rejected == 1
    assert result.receipts[0].reason is reason


def test_organic_navigation_is_admitted_without_recommendation_lineage() -> None:
    organic = InteractionEvent(
        event_id="organic-001",
        event_type=EventType.ORGANIC_NAVIGATION,
        tenant_id="tenant-orbit",
        user_id="user-001",
        experience_id="exp-001",
        request_id="request-direct",
        occurred_at=RECEIVED,
        synthetic=True,
        consent_state=ConsentState.PERSONALIZATION_DENIED,
        impression_token=None,
        payload=OrganicNavigationPayload(path=NavigationPath.ORGANIC, source="search_bookmark"),
    )
    result = InteractionIngestion().ingest(
        batch(organic), tenant_id="tenant-orbit", user_id="user-001", request_id="request-direct", received_at=RECEIVED
    )
    assert result.accepted == 1


def test_synthetic_only_mode_and_batch_bound_are_explicit() -> None:
    live = event(synthetic=False)
    result = InteractionIngestion(require_synthetic=True).ingest(
        batch(live), tenant_id="tenant-orbit", user_id="user-001", request_id="request-001", received_at=RECEIVED
    )
    assert result.receipts[0].reason is RejectionReason.SYNTHETIC_MARKER_INVALID
    with pytest.raises(ValueError, match="max_timestamp_skew"):
        InteractionIngestion(max_timestamp_skew=timedelta(days=2))
