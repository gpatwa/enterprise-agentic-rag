from datetime import datetime, timedelta, timezone

import pytest

from app.domain.models import ConsentState, ExplicitPreferences, Genre, Theme
from app.events.models import ClickPayload, DismissPayload, EventType, InteractionEvent
from app.profiles.builder import ProfileBuilder, ProfileKind
from packages.platform_contracts.discovery import DiscoveryComponentVersion, DiscoveryRequestContext, ImpressionToken

UTC = timezone.utc
AS_OF = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


def _event(event_id: str, event_type: EventType = EventType.CLICK, occurred_at: datetime = AS_OF - timedelta(days=1), payload: object | None = None, **changes: object) -> InteractionEvent:
    request_id = str(changes.get("request_id", "request-001"))
    context = DiscoveryRequestContext(tenant_id="tenant-orbit", principal_id="user-001", request_id=request_id, purpose="recommendation", locale="en-US", device="web")
    component = DiscoveryComponentVersion(component_type="schema", name="discovery", version="v1", digest="a" * 64)
    token = ImpressionToken.for_context(context, token_id=f"token-{event_id}", issued_at=occurred_at - timedelta(minutes=1), expires_at=occurred_at + timedelta(minutes=5), schema_version="v1", components=(component,))
    values: dict[str, object] = dict(event_id=event_id, event_type=event_type, tenant_id="tenant-orbit", user_id="user-001", experience_id="exp-001", request_id=request_id, occurred_at=occurred_at, synthetic=True, consent_state=ConsentState.PERSONALIZATION_ALLOWED, impression_token=token, payload=payload or ClickPayload())
    values.update(changes)
    return InteractionEvent(**values)


def test_profile_is_point_in_time_decay_aware_and_reproducible() -> None:
    events = (_event("click-old", occurred_at=AS_OF - timedelta(days=7)), _event("click-new", occurred_at=AS_OF - timedelta(hours=1)))
    builder = ProfileBuilder()
    first = builder.build(tenant_id="tenant-orbit", user_id="user-001", events=events, as_of=AS_OF, explicit_preferences=ExplicitPreferences(genres=(Genre.ADVENTURE,), themes=(Theme.FOREST,)))
    second = builder.build(tenant_id="tenant-orbit", user_id="user-001", events=events, as_of=AS_OF, explicit_preferences=ExplicitPreferences(genres=(Genre.ADVENTURE,), themes=(Theme.FOREST,)))
    assert first == second
    assert first.short_term.signals["clicks"] < first.long_term.signals["clicks"]
    assert first.explicit_preferences == ("genre:adventure", "theme:forest")
    assert "user-001" not in first.model_dump_json()


def test_consent_denied_returns_typed_zero_profile() -> None:
    profile = ProfileBuilder().build(tenant_id="tenant-orbit", user_id="user-001", events=(_event("click"),), as_of=AS_OF, consent_state=ConsentState.PERSONALIZATION_DENIED, explicit_preferences=ExplicitPreferences(genres=(Genre.ACTION,)))
    assert profile.profile_kind is ProfileKind.NO_PERSONALIZATION
    assert profile.short_term.event_count == 0
    assert not profile.short_term.signals
    assert not profile.explicit_preferences


def test_future_and_deleted_events_are_ignored_without_raw_history() -> None:
    future = _event("future", occurred_at=AS_OF + timedelta(days=1))
    deleted = _event("deleted", event_type=EventType.DISMISS, payload=DismissPayload(reason="not_interested"))
    profile = ProfileBuilder().build(tenant_id="tenant-orbit", user_id="user-001", events=(future, deleted), as_of=AS_OF, deleted_event_ids=("deleted",))
    assert profile.short_term.event_count == 0
    assert profile.deleted_event_count == 1
    assert profile.negative_feedback.dismissals == 0


def test_scope_and_timestamp_validation_fail_closed() -> None:
    with pytest.raises(ValueError, match="tenant/user scope"):
        ProfileBuilder().build(tenant_id="tenant-other", user_id="user-001", events=(_event("click"),), as_of=AS_OF)
    with pytest.raises(ValueError, match="timezone-aware"):
        ProfileBuilder().build(tenant_id="tenant-orbit", user_id="user-001", events=(), as_of=datetime(2026, 1, 1))
