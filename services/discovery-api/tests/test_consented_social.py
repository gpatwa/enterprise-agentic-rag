from datetime import datetime, timezone

from tests.test_coplay_graph import context, experience, user

from app.candidates.consented_social import ConsentedSocialCandidateSource, SocialMembership
from app.domain.models import ConsentState

AS_OF = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)


def membership(identifier: str, experience_ids: tuple[str, ...], *, consent=ConsentState.PERSONALIZATION_ALLOWED, observed_at=AS_OF, tenant="tenant-orbit", user_id="user-001") -> SocialMembership:
    return SocialMembership(
        membership_id=identifier,
        tenant_id=tenant,
        user_id=user_id,
        group_id=f"group-{identifier}",
        experience_ids=experience_ids,
        consent_state=consent,
        observed_at=observed_at,
    )


def test_consent_and_eligibility_are_required() -> None:
    denied = membership("denied", ("exp-denied",), consent=ConsentState.PERSONALIZATION_DENIED)
    other_tenant = membership("other", ("exp-other",), tenant="tenant-other")
    result = ConsentedSocialCandidateSource().retrieve(user(), (denied, other_tenant), (experience("exp-denied"), experience("exp-other")), context(), as_of=AS_OF)
    assert result.source_result.candidates == ()
    assert result.source_result.degradation.value == "empty"


def test_future_and_blocked_memberships_are_excluded() -> None:
    future = membership("future", ("exp-future",), observed_at=AS_OF.replace(hour=13))
    result = ConsentedSocialCandidateSource().retrieve(user(), (future,), (experience("exp-future"),), context(), as_of=AS_OF, blocked_ids=("exp-future",))
    assert result.source_result.candidates == ()


def test_output_is_redacted_deterministic_and_bounded() -> None:
    records = (membership("b", ("exp-b",)), membership("a", ("exp-a", "exp-b")))
    first = ConsentedSocialCandidateSource(max_candidates=1).retrieve(user(), records, (experience("exp-a"), experience("exp-b")), context(), as_of=AS_OF)
    second = ConsentedSocialCandidateSource(max_candidates=1).retrieve(user(), tuple(reversed(records)), (experience("exp-b"), experience("exp-a")), context(), as_of=AS_OF)
    assert first == second
    assert len(first.source_result.candidates) == 1
    rendered = first.model_dump_json()
    assert "group-a" not in rendered and "group-b" not in rendered
    assert '"membership_id"' not in rendered
    assert len(first.evidence[0].relationship_digest) == 64


def test_denied_user_is_a_no_social_data_fallback() -> None:
    denied_user = user().model_copy(update={"consent_state": ConsentState.PERSONALIZATION_DENIED})
    result = ConsentedSocialCandidateSource().retrieve(denied_user, (membership("allowed", ("exp-allowed",)),), (experience("exp-allowed"),), context(), as_of=AS_OF)
    assert result.source_result.candidates == ()
