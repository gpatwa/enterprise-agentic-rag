"""Field-level classification enforcement for certified query plans."""
from __future__ import annotations

from packages.platform_contracts.security import AnalyticsIdentity, AuthorizationDecision
from packages.platform_contracts.semantic import SemanticContract


def enforce_field_access(
    identity: AnalyticsIdentity,
    contract: SemanticContract,
    field_ids: set[str],
    purpose: str,
) -> AuthorizationDecision:
    """Reject restricted fields without an approved group before compilation."""
    fields = {field.id: field for field in contract.fields}
    restricted = [fields[field_id] for field_id in field_ids if field_id in fields and fields[field_id].classification == "restricted"]
    confidential = [fields[field_id] for field_id in field_ids if field_id in fields and fields[field_id].classification == "confidential"]
    if restricted and "restricted-data" not in identity.groups:
        return AuthorizationDecision(decision_id="field-deny", effect="deny", reasons=["restricted_field_access"], policy_version=contract.version)
    if confidential and "confidential-data" not in identity.groups:
        return AuthorizationDecision(decision_id="field-review", effect="review", reasons=["confidential_field_requires_review"], policy_version=contract.version)
    return AuthorizationDecision(decision_id="field-allow", effect="allow", reasons=[f"purpose:{purpose}"], policy_version=contract.version)
