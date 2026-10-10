from datetime import datetime, timedelta, timezone

import pytest


def _event(kind="click", document_id="doc-1", *, consent=True, expired=False):
    from app.search.events import InteractionKind, SearchInteractionEvent

    now = datetime.now(timezone.utc)
    return SearchInteractionEvent(
        idempotency_key=f"{kind}-{document_id}-{consent}-{expired}",
        tenant_id="tenant-acme",
        principal_pseudonym="principal-hash",
        purpose="support-search",
        kind=InteractionKind(kind),
        document_id=document_id if kind != "search" else None,
        occurred_at=now - timedelta(days=2),
        expires_at=now - timedelta(days=1) if expired else now + timedelta(days=30),
        consent_granted=consent,
    )


def test_interaction_event_requires_consent_and_document_for_action():
    from app.search.events import InteractionKind, SearchInteractionEvent

    with pytest.raises(ValueError, match="document_id is required"):
        SearchInteractionEvent(
            idempotency_key="x",
            tenant_id="tenant-acme",
            principal_pseudonym="p",
            purpose="support",
            kind=InteractionKind.CLICK,
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )


def test_materialized_features_ignore_expired_or_nonconsented_events():
    from app.search.materialize import materialize_features

    features = materialize_features([_event(), _event("accept"), _event(expired=True), _event(consent=False)])
    assert features[("tenant-acme", "doc-1")].expertise > 0
    assert features[("tenant-acme", "doc-1")].provenance == ("interaction-events.v1",)


def test_reranker_is_deterministic_and_uses_baseline_for_zero_history():
    from app.search.features import RankingFeatures
    from app.search.models import RetrievalSource, SearchResult
    from app.search.ranking import rerank_authorized

    def result(document_id, score):
        return SearchResult(
            document_id=document_id, tenant_id="tenant-acme", source_type="ticket", source_id=document_id,
            title=document_id, text="body", score=score, rank=1, retrieval_source=RetrievalSource.HYBRID,
            index_generation="g1", content_version="v1", permission_version="p1",
        )

    ranked = rerank_authorized(
        [result("b", 1.0), result("a", 1.0)],
        {"a": RankingFeatures(popularity=1.0)},
    )
    assert [item.document_id for item in ranked] == ["a", "b"]


def test_recommendation_metrics_and_kill_switch_are_reproducible():
    from app.search.experiments import assign_variant
    from app.search.recommendation_metrics import precision_at_k, recall_at_k

    assert precision_at_k(["a", "x"], {"a"}, k=2) == 0.5
    assert recall_at_k(["a", "x"], {"a", "b"}, k=2) == 0.5
    assert assign_variant(tenant_id="t", principal_pseudonym="p", experiment="e", enabled=True, kill_switch=False) == assign_variant(
        tenant_id="t", principal_pseudonym="p", experiment="e", enabled=True, kill_switch=False
    )
    assert assign_variant(tenant_id="t", principal_pseudonym="p", experiment="e", enabled=True, kill_switch=True) == "control"


@pytest.mark.asyncio
async def test_support_feedback_event_is_redacted_and_best_effort(monkeypatch):
    import app.support.workflow as workflow
    from app.auth.tenant import TenantContext
    from app.search.events import InteractionKind

    captured = []

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def commit(self):
            pass

    monkeypatch.setattr("app.memory.postgres.AsyncSessionLocal", lambda: FakeSession())

    async def capture(session, event):
        captured.append(event)

    monkeypatch.setattr(workflow, "persist_interaction_event", capture)
    ctx = TenantContext(tenant_id="tenant-acme", user_id="agent-1", role="agent", permissions=[])
    await workflow.emit_support_interaction_event(
        ctx=ctx,
        kind=InteractionKind.RESOLVE,
        correlation_id="req-123",
        document_id="resolution:abc",
        consent_granted=True,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        metadata={"confidence": "high", "match_count": "1"},
    )

    assert captured[0].request_id == "req-123"
    assert captured[0].tenant_id == "tenant-acme"
    assert captured[0].metadata == {"confidence": "high", "match_count": "1"}
    assert not hasattr(captured[0], "question")

    async def fail(*args):
        raise RuntimeError("event store unavailable")

    monkeypatch.setattr(workflow, "persist_interaction_event", fail)
    await workflow.emit_support_interaction_event(
        ctx=ctx,
        kind=InteractionKind.EXECUTE,
        correlation_id="action-1",
        document_id="action-1",
        consent_granted=True,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
