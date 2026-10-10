"""EA-044 and EA-045 field access and secret handling tests."""
from datetime import datetime, timedelta, timezone

import pytest

from app.security import InMemorySecretProvider, enforce_field_access, redact_secret
from packages.platform_contracts.security import AnalyticsIdentity


def test_restricted_fields_fail_closed_without_group():
    import json
    from pathlib import Path

    from packages.platform_contracts.semantic import SemanticContract

    contract = SemanticContract.model_validate(json.loads((Path(__file__).parent.parent / "semantic_registry/contracts/olist-commerce-v1.json").read_text())["contract"])
    field = contract.fields[0]
    restricted = contract.model_copy(update={"fields": [field.model_copy(update={"classification": "restricted"})]})
    decision = enforce_field_access(AnalyticsIdentity(tenant_id="demo", user_id="u"), restricted, {field.id}, "reporting")
    assert decision.effect == "deny"


def test_secret_provider_supports_versioned_lease_and_redaction():
    provider = InMemorySecretProvider({("demo", "warehouse"): ("super-secret", "v2")})
    lease = provider.lease("demo", "warehouse", "v2", datetime.now(timezone.utc) + timedelta(minutes=5))
    assert lease.version == "v2"
    assert provider.read("demo", "warehouse") == "super-secret"
    assert redact_secret("super-secret") == "[REDACTED]"
    with pytest.raises(KeyError):
        provider.lease("demo", "warehouse", "v1", lease.expires_at)
