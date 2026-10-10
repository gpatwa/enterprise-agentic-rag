from datetime import datetime, timedelta, timezone

from app.integrity.defenses import (
    EvidenceCode,
    IntegrityDefenses,
    IntegrityPolicy,
    IntegritySignal,
    IntegrityStatus,
    SignalType,
    assess_integrity,
)

UTC = timezone.utc
BASE = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


def digest(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode()).hexdigest()


def signal(number: int, kind: SignalType, *, actor: str = "actor", experience: str = "experience", offset: float = 0, source: str = "recommendation") -> IntegritySignal:
    return IntegritySignal(
        event_digest=digest(f"event-{number}"),
        tenant_digest=digest("tenant"),
        actor_digest=digest(actor),
        experience_digest=digest(experience),
        occurred_at=BASE + timedelta(seconds=offset),
        signal_type=kind,
        synthetic=True,
        source=source,
    )


def test_duplicate_and_impossible_sequence_are_quarantined() -> None:
    impression = signal(1, SignalType.IMPRESSION)
    duplicate = impression.model_copy()
    invalid_play = signal(2, SignalType.PLAY, actor="different-actor", offset=1)
    assessment = assess_integrity((impression, duplicate, invalid_play))
    assert assessment.status is IntegrityStatus.FLAGGED
    assert len(assessment.ranking_eligible_event_digests) == 0
    assert EvidenceCode.DUPLICATE_EVENT in {item.code for item in assessment.evidence}
    assert EvidenceCode.IMPOSSIBLE_SEQUENCE in {item.code for item in assessment.evidence}


def test_rate_limit_and_timing_defenses_are_deterministic() -> None:
    policy = IntegrityPolicy(max_actor_events_per_window=2, min_event_spacing_seconds=1)
    events = (
        signal(1, SignalType.IMPRESSION, offset=0),
        signal(2, SignalType.IMPRESSION, offset=0.1),
        signal(3, SignalType.IMPRESSION, offset=0.2),
    )
    assessment = assess_integrity(events, policy=policy)
    codes = {item.code for item in assessment.evidence}
    assert EvidenceCode.ACTOR_RATE_LIMIT in codes
    assert EvidenceCode.IMPOSSIBLE_TIMING in codes


def test_coordinated_burst_and_popularity_loop_are_flagged() -> None:
    policy = IntegrityPolicy(coordinated_actor_count=3, coordinated_burst_events=3, min_popularity_actions=3, max_actions_per_impression=0.5)
    impressions = [signal(i, SignalType.IMPRESSION, actor=f"actor-{i}", offset=i) for i in range(3)]
    actions = [signal(i + 10, SignalType.CLICK, actor=f"actor-{i}", offset=i + 0.5) for i in range(3)]
    assessment = assess_integrity(tuple(impressions + actions), policy=policy)
    codes = {item.code for item in assessment.evidence}
    assert EvidenceCode.COORDINATED_BURST in codes
    assert EvidenceCode.POPULARITY_LOOP in codes


def test_organic_navigation_is_allowed_and_unsafe_input_fails_closed() -> None:
    organic = signal(1, SignalType.ORGANIC_NAVIGATION, source="organic")
    clean = IntegrityDefenses().assess((organic,))
    assert clean.status is IntegrityStatus.CLEAN
    rejected = IntegrityDefenses().assess_raw(({"event_digest": "not-a-digest"},))
    assert rejected.status is IntegrityStatus.REJECTED
    assert rejected.ranking_eligible_event_digests == ()
    assert rejected.evidence[0].code is EvidenceCode.UNSAFE_SIGNAL


def test_serialization_contains_digests_but_not_raw_identity() -> None:
    event = signal(1, SignalType.IMPRESSION, actor="private-user")
    serialized = assess_integrity((event,)).serialize()
    assert "private-user" not in serialized
    assert event.event_digest in serialized
