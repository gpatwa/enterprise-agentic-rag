from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.audit.ranking import AuditOutcome, PolicyOutcome, RankingAuditRecord, RankingAuditWriter, checksum, digest
from app.domain.models import ConsentState
from app.events.models import ClickPayload, EventType, InteractionEvent
from app.routes.interactions import (
    FeedbackReason,
    FeedbackSubmission,
    FeedbackType,
    InteractionSubmission,
    LocalInteractionService,
)
from packages.platform_contracts.discovery import DiscoveryComponentVersion, ImpressionToken

NOW = datetime.now(timezone.utc).replace(microsecond=0)


def _component() -> DiscoveryComponentVersion:
    return DiscoveryComponentVersion(component_type="model", name="ranker", version="v1", digest="a" * 64)


def _token() -> ImpressionToken:
    return ImpressionToken(
        token_id="token-1",
        tenant_id="tenant-1",
        principal_id="user-1",
        request_id="request-1",
        context_digest="b" * 64,
        issued_at=NOW - timedelta(seconds=1),
        expires_at=NOW + timedelta(minutes=5),
        schema_version="imd-search-v1",
        components=(_component(),),
    )


def _event(*, consent: ConsentState = ConsentState.PERSONALIZATION_ALLOWED) -> InteractionEvent:
    return InteractionEvent(
        event_id="event-1",
        event_type=EventType.CLICK,
        tenant_id="tenant-1",
        user_id="user-1",
        experience_id="experience-1",
        request_id="request-1",
        occurred_at=NOW,
        synthetic=True,
        consent_state=consent,
        impression_token=_token(),
        payload=ClickPayload(position=1),
    )


def test_submit_interactions_accepts_and_replays_idempotently() -> None:
    service = LocalInteractionService()
    request = InteractionSubmission(
        tenant_id="tenant-1", user_id="user-1", request_id="request-1", events=(_event(),)
    )

    first = service.submit(request)
    second = service.submit(request)

    assert first.accepted == 1
    assert second.already_present == 1
    assert first.receipts[0].event_ref != "event-1"


def test_submit_rejects_mismatched_scope_and_consent() -> None:
    service = LocalInteractionService()
    mismatched = service.submit(
        InteractionSubmission(
            tenant_id="other-tenant", user_id="user-1", request_id="request-1", events=(_event(),)
        )
    )
    denied = service.submit(
        InteractionSubmission(
            tenant_id="tenant-1",
            user_id="user-1",
            request_id="request-1",
            events=(_event(consent=ConsentState.PERSONALIZATION_DENIED).model_copy(update={"event_id": "event-2"}),),
        )
    )

    assert mismatched.receipts[0].reason.value == "batch_tenant_mismatch"
    assert denied.receipts[0].reason.value == "consent_required"


def test_feedback_is_typed_and_uses_canonical_ingestion() -> None:
    service = LocalInteractionService()
    request = FeedbackSubmission(
        event_id="feedback-1",
        tenant_id="tenant-1",
        user_id="user-1",
        request_id="request-1",
        experience_id="experience-1",
        occurred_at=NOW,
        synthetic=True,
        consent_state=ConsentState.PERSONALIZATION_ALLOWED,
        impression_token=_token(),
        feedback_type=FeedbackType.DISMISS,
        reason=FeedbackReason.NOT_INTERESTED,
    )

    response = service.submit_feedback(request)

    assert response.receipt.status.value == "accepted"
    with pytest.raises(ValueError, match="report feedback"):
        FeedbackSubmission(**{**request.model_dump(), "feedback_type": FeedbackType.REPORT})


def test_feedback_rejects_invalid_lineage_and_extra_fields() -> None:
    service = LocalInteractionService()
    request = FeedbackSubmission(
        event_id="feedback-2",
        tenant_id="tenant-1",
        user_id="user-1",
        request_id="request-1",
        experience_id="experience-1",
        occurred_at=NOW,
        synthetic=True,
        consent_state=ConsentState.PERSONALIZATION_ALLOWED,
        impression_token=_token().model_copy(update={"request_id": "other-request"}),
        feedback_type=FeedbackType.DISMISS,
        reason=FeedbackReason.NOT_INTERESTED,
    )

    with pytest.raises(ValueError, match="impression token request"):
        service.submit_feedback(request)
    with pytest.raises(ValidationError):
        FeedbackSubmission(**request.model_dump(), comment="private text")


def test_explanation_returns_only_redacted_audit_evidence() -> None:
    event_id = "decision-1"
    record = RankingAuditRecord(
        event_id=event_id,
        tenant_digest=digest("tenant-1"),
        request_digest=digest("request-1"),
        decision_digest=digest("decision"),
        outcome=AuditOutcome.COMPLETED,
        eligibility_outcome=PolicyOutcome.ALLOWED,
        policy_outcome=PolicyOutcome.ALLOWED,
        candidate_count=3,
        eligible_count=2,
        selected_count=1,
        reason_codes=("relevant",),
        component_versions=("ranker-v1",),
        evidence=("lexical_match",),
        occurred_at=NOW,
        record_checksum=checksum({"decision": "redacted"}),
    )
    service = LocalInteractionService(audit=RankingAuditWriter())
    service._audit.append(record)

    explanation = service.explain(event_id)

    assert explanation.decision_ref == event_id
    assert explanation.explanation_id == digest(event_id)
    assert explanation.evidence == ("lexical_match",)
    assert "tenant" not in explanation.model_dump_json()
    with pytest.raises(KeyError, match="unknown decision"):
        service.explain("missing-decision")


def test_explanation_route_models_are_bounded() -> None:
    with pytest.raises(ValidationError):
        InteractionSubmission(
            tenant_id="tenant-1",
            user_id="user-1",
            request_id="request-1",
            events=(_event(),),
            history="private",
        )
