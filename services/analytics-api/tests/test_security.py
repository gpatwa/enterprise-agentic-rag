"""EA-040 to EA-047 identity, policy, and audit tests."""
import json
from pathlib import Path

from app.security import AuditChain, authorize
from packages.platform_contracts.security import AnalyticsIdentity
from packages.platform_contracts.semantic import SemanticContract

CONTRACT = Path(__file__).parent.parent / "semantic_registry/contracts/olist-commerce-v1.json"


def contract():
    return SemanticContract.model_validate(json.loads(CONTRACT.read_text())["contract"])


def test_authorization_fails_closed_for_cross_tenant_identity():
    decision = authorize(AnalyticsIdentity(tenant_id="other", user_id="u"), contract(), {"delivered_revenue"}, "reporting")
    assert decision.effect == "deny"


def test_audit_chain_detects_tampering():
    chain = AuditChain()
    chain.append("1", "query.received", "demo", "u", {"query_id": "q1"})
    chain.append("2", "query.completed", "demo", "u", {"outcome": "answer"})
    assert chain.verify() is True
    chain.events[0].payload["query_id"] = "tampered"
    assert chain.verify() is False
