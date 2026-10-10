from __future__ import annotations

import hashlib


def assign_variant(*, tenant_id: str, principal_pseudonym: str, experiment: str, enabled: bool, kill_switch: bool) -> str:
    if not enabled or kill_switch:
        return "control"
    digest = hashlib.sha256(f"{experiment}:{tenant_id}:{principal_pseudonym}".encode()).digest()
    return "treatment" if int.from_bytes(digest[:4], "big") % 2 == 0 else "control"
