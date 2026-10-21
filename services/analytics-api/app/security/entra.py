"""Microsoft Entra ID access tokens for the pilot (RS256 via the tenant's published keys).

Entra tokens carry the Entra tenant (`tid`), a stable user object ID (`oid`), and app roles (`roles`), not this product's
purposes or analytics tenant. The mapping is explicit configuration:

- `tenant_map`: Entra tenant ID -> analytics tenant ID. A token from an unmapped Entra tenant is refused.
- `role_map`: app role -> (purposes, groups). Example: `Analytics.Analyst` -> (["analytics"], ["analyst"]),
  `Analytics.Reviewer` -> ([], ["analytics-reviewer"]). Unknown roles grant nothing.

The signing keys are fetched from the tenant's JWKS URL and refetched once when a token names an unknown key (key rotation). Every
check the local verifier makes is kept: issuer, audience, expiry, subject, and a one-level actor claim.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from typing import Any

from jose import JWTError, jwt

from app.security.oidc import AuthenticationError
from packages.platform_contracts.security import AnalyticsIdentity


def fetch_jwks(url: str) -> dict[str, Any]:
    import httpx

    response = httpx.get(url, timeout=10.0)
    response.raise_for_status()
    return {key["kid"]: key for key in response.json().get("keys", []) if key.get("kid")}


class EntraVerifier:
    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        jwks_url: str,
        tenant_map: Mapping[str, str],
        role_map: Mapping[str, tuple[list[str], list[str]]],
        fetch: Callable[[str], dict[str, Any]] = fetch_jwks,
    ) -> None:
        if not tenant_map:
            raise ValueError("tenant_map must name at least one Entra tenant")
        self.issuer, self.audience, self._jwks_url = issuer, audience, jwks_url
        self._tenant_map, self._role_map, self._fetch = dict(tenant_map), dict(role_map), fetch
        self._lock = threading.Lock()
        self._keys: dict[str, Any] = {}

    def _key(self, kid: str) -> Any:
        with self._lock:
            if kid not in self._keys:
                self._keys = self._fetch(self._jwks_url)  # refetch once on an unknown key (rotation)
            if kid not in self._keys:
                raise AuthenticationError("unknown signing key")
            return self._keys[kid]

    def verify(self, token: str) -> AnalyticsIdentity:
        try:
            kid = jwt.get_unverified_header(token).get("kid")
            if not kid:
                raise AuthenticationError("unknown signing key")
            claims = jwt.decode(
                token,
                self._key(kid),
                algorithms=["RS256"],
                issuer=self.issuer,
                audience=self.audience,
                options={"require_iss": True, "require_aud": True, "require_exp": True, "require_sub": True},
            )
        except AuthenticationError:
            raise
        except (JWTError, TypeError, ValueError, KeyError) as exc:
            raise AuthenticationError("invalid identity token") from exc
        entra_tenant = claims.get("tid")
        if not isinstance(entra_tenant, str) or entra_tenant not in self._tenant_map:
            raise AuthenticationError("token tenant is not enabled for analytics")
        subject = claims.get("oid") or claims.get("sub")
        if not isinstance(subject, str) or not subject.strip():
            raise AuthenticationError("token subject is invalid")
        roles = claims.get("roles", [])
        if not isinstance(roles, list) or not all(isinstance(r, str) for r in roles):
            raise AuthenticationError("token roles claim is invalid")
        purposes: list[str] = []
        groups: list[str] = []
        for role in roles:
            role_purposes, role_groups = self._role_map.get(role, ([], []))
            purposes += [p for p in role_purposes if p not in purposes]
            groups += [g for g in role_groups if g not in groups]
        passthrough = {"iss": str(claims["iss"]), "aud": str(claims["aud"]), "sub": subject, "tid": entra_tenant}
        actor = claims.get("act")
        if actor is not None:
            if (
                not isinstance(actor, dict)
                or set(actor) - {"sub", "client_id"}
                or not isinstance(actor.get("sub"), str)
                or not actor["sub"].strip()
            ):
                raise AuthenticationError("token actor claim is invalid")
            passthrough["act_sub"] = actor["sub"]
        return AnalyticsIdentity(
            tenant_id=self._tenant_map[entra_tenant],
            user_id=subject,
            purposes=purposes,
            groups=groups,
            claims=passthrough,
        )
