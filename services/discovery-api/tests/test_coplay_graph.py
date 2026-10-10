from datetime import datetime, timedelta, timezone

from app.candidates.social_graph import CoPlayGraphCandidateSource, CoPlayGraphConfig
from app.domain.models import (
    AgeRating,
    Availability,
    CatalogDevice,
    ConsentState,
    ExperienceRecord,
    ExperienceSignals,
    FreshnessBand,
    Genre,
    HistoryLength,
    ImmersiveDiscoveryContext,
    Locale,
    Mechanic,
    Persona,
    PopularityBand,
    QualityBand,
    SafetyState,
    Theme,
    UserProfile,
)
from app.events.models import CoPlayPayload, EventType, InteractionEvent, QualifiedPlayPayload
from packages.platform_contracts.discovery import DiscoveryComponentVersion, DiscoveryRequestContext, ImpressionToken

UTC = timezone.utc
AS_OF = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


def user(user_id: str = "user-001") -> UserProfile:
    return UserProfile(
        user_id=user_id,
        tenant_id="tenant-orbit",
        persona=Persona.SOCIAL,
        locale=Locale.EN_US,
        age_rating_limit=AgeRating.T,
        devices=(CatalogDevice.DESKTOP,),
        history_length=HistoryLength.SHORT,
        preferences={"genres": (Genre.ADVENTURE,), "themes": (Theme.FANTASY,)},
        consent_state=ConsentState.PERSONALIZATION_ALLOWED,
        synthetic=True,
    )


def experience(experience_id: str) -> ExperienceRecord:
    return ExperienceRecord(
        experience_id=experience_id,
        creator_id="creator-001",
        tenant_id="tenant-orbit",
        title=experience_id,
        description="synthetic experience",
        genres=(Genre.ADVENTURE,),
        themes=(Theme.FANTASY,),
        mechanics=(Mechanic.EXPLORATION,),
        devices=(CatalogDevice.DESKTOP,),
        locales=(Locale.EN_US,),
        age_rating=AgeRating.E,
        safety_state=SafetyState.APPROVED,
        availability=Availability.AVAILABLE,
        synthetic=True,
        signals=ExperienceSignals(
            freshness_band=FreshnessBand.FRESH,
            quality_band=QualityBand.HIGH,
            popularity_band=PopularityBand.RISING,
        ),
    )


def context() -> ImmersiveDiscoveryContext:
    return ImmersiveDiscoveryContext(
        request_context=DiscoveryRequestContext(
            tenant_id="tenant-orbit", principal_id="user-001", request_id="request-001", purpose="recommendation", locale="en-US", device="web"
        ),
        surface="recommendation",
    )


def token(user_id: str, request_id: str) -> ImpressionToken:
    request = DiscoveryRequestContext(
        tenant_id="tenant-orbit", principal_id=user_id, request_id=request_id, purpose="recommendation", locale="en-US", device="web"
    )
    return ImpressionToken.for_context(
        request,
        token_id=f"token-{user_id}-{request_id}",
        issued_at=AS_OF - timedelta(minutes=1),
        expires_at=AS_OF + timedelta(minutes=5),
        schema_version="v1",
        components=(DiscoveryComponentVersion(component_type="schema", name="discovery", version="v1", digest="a" * 64),),
    )


def event(event_id: str, user_id: str, experience_id: str, event_type: EventType, payload: object, *, occurred_at: datetime = AS_OF, consent_state: ConsentState = ConsentState.PERSONALIZATION_ALLOWED) -> InteractionEvent:
    request_id = f"request-{user_id}"
    return InteractionEvent(
        event_id=event_id,
        event_type=event_type,
        tenant_id="tenant-orbit",
        user_id=user_id,
        experience_id=experience_id,
        request_id=request_id,
        occurred_at=occurred_at,
        synthetic=True,
        consent_state=consent_state,
        impression_token=token(user_id, request_id),
        payload=payload,
    )


def qualified(event_id: str, user_id: str, experience_id: str, *, occurred_at: datetime = AS_OF, consent_state: ConsentState = ConsentState.PERSONALIZATION_ALLOWED) -> InteractionEvent:
    return event(event_id, user_id, experience_id, EventType.QUALIFIED_PLAY, QualifiedPlayPayload(duration_seconds=30, qualification_threshold_seconds=10), occurred_at=occurred_at, consent_state=consent_state)


def test_shared_qualified_engagement_is_ranked_without_peer_identity() -> None:
    events = (
        qualified("q-target", "user-001", "exp-anchor"),
        qualified("q-peer-anchor", "user-002", "exp-anchor"),
        qualified("q-peer-candidate", "user-002", "exp-candidate"),
        event("coplay", "user-002", "exp-anchor", EventType.CO_PLAY, CoPlayPayload(participant_count=2, session_id="session-1")),
    )
    result = CoPlayGraphCandidateSource().retrieve(user(), events, (experience("exp-anchor"), experience("exp-candidate")), context(), as_of=AS_OF)
    assert [item.experience_id for item in result.source_result.candidates] == ["exp-candidate"]
    assert result.evidence[0].support_count == 1
    assert result.evidence[0].co_play_signal is True
    assert "user-002" not in result.model_dump_json()


def test_future_denied_and_cross_tenant_events_do_not_enter_graph() -> None:
    future = qualified("future", "user-002", "exp-candidate", occurred_at=AS_OF + timedelta(seconds=1))
    denied = qualified("denied", "user-002", "exp-candidate", consent_state=ConsentState.PERSONALIZATION_DENIED)
    other = qualified("other", "user-003", "exp-candidate") .model_copy(update={"tenant_id": "tenant-other"})
    result = CoPlayGraphCandidateSource().retrieve(user(), (qualified("anchor", "user-001", "exp-anchor"), future, denied, other), (experience("exp-anchor"), experience("exp-candidate")), context(), as_of=AS_OF)
    assert result.source_result.candidates == ()


def test_support_threshold_tenant_and_eligibility_are_enforced() -> None:
    events = (
        qualified("target", "user-001", "exp-anchor"),
        qualified("peer-one-anchor", "user-002", "exp-anchor"),
        qualified("peer-one-candidate", "user-002", "exp-candidate"),
    )
    source = CoPlayGraphCandidateSource(CoPlayGraphConfig(minimum_support=2))
    result = source.retrieve(user(), events, (experience("exp-anchor"), experience("exp-candidate")), context(), as_of=AS_OF)
    assert result.source_result.candidates == ()


def test_graph_is_deterministic_and_bounded() -> None:
    events = (
        qualified("target", "user-001", "exp-anchor"),
        qualified("peer-b-anchor", "user-003", "exp-anchor"),
        qualified("peer-b-candidate", "user-003", "exp-candidate", occurred_at=AS_OF - timedelta(days=2)),
        qualified("peer-a-anchor", "user-002", "exp-anchor"),
        qualified("peer-a-candidate", "user-002", "exp-candidate", occurred_at=AS_OF - timedelta(days=1)),
    )
    source = CoPlayGraphCandidateSource(CoPlayGraphConfig(max_candidates=1))
    first = source.retrieve(user(), events, (experience("exp-anchor"), experience("exp-candidate")), context(), as_of=AS_OF)
    second = source.retrieve(user(), tuple(reversed(events)), (experience("exp-candidate"), experience("exp-anchor")), context(), as_of=AS_OF)
    assert first == second
    assert len(first.source_result.candidates) == 1
