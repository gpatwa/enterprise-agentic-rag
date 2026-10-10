from __future__ import annotations

import hashlib


def rollout_bucket(tenant_id: str, *, salt: str = "opensearch-canary-v1") -> int:
    digest = hashlib.sha256(f"{salt}:{tenant_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % 100


def use_opensearch(
    tenant_id: str,
    *,
    canary_percent: int,
    enabled: bool,
    rollback: bool = False,
) -> bool:
    if canary_percent < 0 or canary_percent > 100:
        raise ValueError("canary_percent must be between 0 and 100")
    if not enabled or rollback or canary_percent <= 0:
        return False
    if canary_percent >= 100:
        return True
    return rollout_bucket(tenant_id) < canary_percent
