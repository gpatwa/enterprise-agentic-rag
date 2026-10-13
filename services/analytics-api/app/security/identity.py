"""Group propagation and delegated-purpose resolution on top of OIDC verification (ADS-063).

`IdentityResolver.resolve` turns a bearer token into the `AnalyticsIdentity` a request runs as:

* the token is verified (issuer, audience, signature, expiry, tenant, and well-formed claims);
* if a directory is configured, the person must be active there, and the effective groups are the token's groups
  *intersected with the directory's current groups*, so removing a group (or disabling the person) takes effect on the very
  next request instead of at token expiry, and a group added after the token was issued is never granted by the token;
* if the token names an acting party, the delegation policy must be approved and grant that agent; the effective purposes
  and groups are then the intersection of the person's and the agent's grant, and the identity keeps the actor claim so the
  call is treated as an agent call (it can never decide a review).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Protocol

from app.security.oidc import AuthenticationError, OIDCVerifier
from packages.platform_contracts.delegation import DelegationPolicy
from packages.platform_contracts.security import AnalyticsIdentity


@dataclass(frozen=True)
class DirectoryEntry:
    active: bool
    groups: frozenset[str]


class GroupDirectory(Protocol):
    def current(self, tenant_id: str, user_id: str) -> DirectoryEntry | None: ...


class InMemoryGroupDirectory:
    """A local stand-in for a live directory; thread-safe so tests can change membership mid-session."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[tuple[str, str], DirectoryEntry] = {}

    def set_user(self, tenant_id: str, user_id: str, groups=(), *, active: bool = True) -> None:
        with self._lock:
            self._entries[(tenant_id, user_id)] = DirectoryEntry(active, frozenset(groups))

    def remove_group(self, tenant_id: str, user_id: str, group: str) -> None:
        with self._lock:
            entry = self._entries[(tenant_id, user_id)]
            self._entries[(tenant_id, user_id)] = DirectoryEntry(entry.active, entry.groups - {group})

    def add_group(self, tenant_id: str, user_id: str, group: str) -> None:
        with self._lock:
            entry = self._entries[(tenant_id, user_id)]
            self._entries[(tenant_id, user_id)] = DirectoryEntry(entry.active, entry.groups | {group})

    def disable(self, tenant_id: str, user_id: str) -> None:
        with self._lock:
            entry = self._entries[(tenant_id, user_id)]
            self._entries[(tenant_id, user_id)] = DirectoryEntry(False, entry.groups)

    def current(self, tenant_id: str, user_id: str) -> DirectoryEntry | None:
        with self._lock:
            return self._entries.get((tenant_id, user_id))


# A token that names an acting party on behalf of the subject carries one of these claims.
DELEGATION_CLAIMS = ("act_sub", "azp_agent", "delegated_by")


def caller_kind(identity: AnalyticsIdentity) -> str:
    """`agent` for automated or delegated callers; `human` only for a direct, non-automated identity."""
    from app.review.rules import is_automated  # imported lazily: the review package sits above this layer

    if is_automated(identity.user_id) or any(identity.claims.get(claim) for claim in DELEGATION_CLAIMS):
        return "agent"
    return "human"


class IdentityResolver:
    def __init__(
        self,
        verifier: OIDCVerifier,
        *,
        directory: GroupDirectory | None = None,
        delegation: DelegationPolicy | None = None,
    ) -> None:
        self.verifier, self.directory, self.delegation = verifier, directory, delegation

    def resolve(self, token: str) -> AnalyticsIdentity:
        identity = self.verifier.verify(token)
        groups = list(identity.groups)
        purposes = list(identity.purposes)
        claims = dict(identity.claims)
        if self.directory is not None:
            entry = self.directory.current(identity.tenant_id, identity.user_id)
            if entry is None:
                raise AuthenticationError("unknown user")
            if not entry.active:
                raise AuthenticationError("user is not active")
            groups = [group for group in groups if group in entry.groups]
        agent_id = claims.get("act_sub")
        if agent_id:
            if self.delegation is None or not self.delegation.approved:
                raise AuthenticationError("delegation is not enabled")
            grant = self.delegation.grant_for(agent_id, identity.tenant_id)
            if grant is None:
                raise AuthenticationError("agent is not granted")
            purposes = [purpose for purpose in purposes if purpose in grant.purposes]
            groups = [group for group in groups if group in grant.groups]
        return AnalyticsIdentity(
            tenant_id=identity.tenant_id, user_id=identity.user_id, purposes=purposes, groups=groups, claims=claims
        )
