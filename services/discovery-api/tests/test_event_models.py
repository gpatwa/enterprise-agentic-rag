from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.domain.models import ConsentState
from app.events.models import (
    ClickPayload,
    EventType,
    ImpressionPayload,
    InteractionEvent,
    InteractionEventBatch,
    NavigationPath,
    OrganicNavigationPayload,
    PlaytimePayload,
    QualifiedPlayPayload,
)
from packages.platform_contracts.discovery import DiscoveryComponentVersion, DiscoveryRequestContext, ImpressionToken

UTC = timezone.utc
ISSUED = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


def token() -> ImpressionToken:
    context = DiscoveryRequestContext(
        tenant_id="tenant-orbit",
        principal_id="user-001",
        request_id="request-001",
        purpose="search",
        locale="en-US",
        device="web",
    )
    component = DiscoveryComponentVersion(
        component_type="schema",
        name="discovery",
        version="v1",
        digest="a" * 64,
    )
    return ImpressionToken.for_context(
        context,
        token_id="token-001",
        issued_at=ISSUED,
        expires_at=ISSUED + timedelta(minutes=5),
        schema_version="v1",
        components=(component,),
    )


def event(event_type: EventType, payload: object, *, event_id: str = "event-001", **kwargs: object) -> InteractionEvent:
    values = {
        "event_id": event_id,
        "event_type": event_type,
        "tenant_id": "tenant-orbit",
        "user_id": "user-001",
        "experience_id": "exp-001",
        "request_id": "request-001",
        "occurred_at": ISSUED,
        "synthetic": True,
        "consent_state": ConsentState.PERSONALIZATION_ALLOWED,
        "impression_token": token(),
        "payload": payload,
    }
    values.update(kwargs)
    return InteractionEvent(
        **values,
    )


def test_all_required_event_types_have_typed_payloads_and_stable_serialization() -> None:
    cases = [
        (EventType.IMPRESSION, ImpressionPayload(position=0, surface="search", source="bm25", result_set_id="set-001")),
        (EventType.CLICK, ClickPayload()),
        (EventType.PLAYTIME, PlaytimePayload(duration_seconds=12.5)),
        (EventType.QUALIFIED_PLAY, QualifiedPlayPayload(duration_seconds=30, qualification_threshold_seconds=10)),
    ]
    for event_type, payload in cases:
        current = event(event_type, payload)
        assert current.serialize() == current.serialize()
        assert isinstance(current.payload, type(payload))


def test_impression_and_actions_require_matching_lineage() -> None:
    current = event(EventType.CLICK, ClickPayload())
    assert current.impression_token is not None
    with pytest.raises(ValidationError, match="require an impression token"):
        event(EventType.CLICK, ClickPayload(), impression_token=None)
    with pytest.raises(ValidationError, match="tenant"):
        event(EventType.CLICK, ClickPayload(), impression_token=token().model_copy(update={"tenant_id": "tenant-other"}))
    with pytest.raises(ValidationError, match="request"):
        event(EventType.CLICK, ClickPayload(), impression_token=token().model_copy(update={"request_id": "request-other"}))


def test_organic_navigation_is_explicit_and_cannot_masquerade_as_recommendation() -> None:
    organic = InteractionEvent(
        event_id="event-organic",
        event_type=EventType.ORGANIC_NAVIGATION,
        tenant_id="tenant-orbit",
        user_id="user-001",
        experience_id="exp-001",
        request_id="request-direct",
        occurred_at=ISSUED,
        synthetic=True,
        consent_state=ConsentState.PERSONALIZATION_DENIED,
        payload=OrganicNavigationPayload(path=NavigationPath.DIRECT, source="bookmark"),
    )
    assert organic.impression_token is None
    with pytest.raises(ValidationError, match="cannot carry"):
        InteractionEvent(
            **organic.model_dump(exclude={"impression_token"}),
            impression_token=token(),
        )


def test_timestamps_durations_and_numeric_bounds_are_validated() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        event(EventType.CLICK, ClickPayload(), occurred_at=datetime(2026, 8, 24, 12, 0))
    with pytest.raises(ValidationError):
        PlaytimePayload(duration_seconds=0)
    with pytest.raises(ValidationError):
        QualifiedPlayPayload(duration_seconds=4, qualification_threshold_seconds=5)


def test_payload_type_and_extra_fields_are_rejected() -> None:
    with pytest.raises(ValidationError, match="does not match"):
        event(EventType.CLICK, ImpressionPayload(position=0, surface="search", source="bm25", result_set_id="set-001"))
    with pytest.raises(ValidationError):
        ClickPayload(unexpected="value")
    with pytest.raises(ValidationError):
        InteractionEvent(
            event_id="event-extra",
            event_type=EventType.CLICK,
            tenant_id="tenant-orbit",
            user_id="user-001",
            experience_id="exp-001",
            request_id="request-001",
            occurred_at=ISSUED,
            synthetic=True,
            consent_state=ConsentState.PERSONALIZATION_ALLOWED,
            impression_token=token(),
            payload=ClickPayload(),
            extra_field="rejected",
        )


def test_batches_are_bounded_unique_and_deterministically_ordered() -> None:
    first = event(EventType.CLICK, ClickPayload(), event_id="event-001")
    second = event(EventType.PLAYTIME, PlaytimePayload(duration_seconds=5), event_id="event-002", occurred_at=ISSUED + timedelta(seconds=1))
    batch = InteractionEventBatch(batch_id="batch-001", events=(first, second))
    assert batch.serialize() == batch.serialize()
    with pytest.raises(ValidationError, match="unique"):
        InteractionEventBatch(batch_id="batch-duplicate", events=(first, first))
    with pytest.raises(ValidationError, match="strict"):
        InteractionEventBatch(batch_id="batch-order", events=(second, first))
