"""OIDC JWT verification with explicit issuer, audience, and key rotation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jose import JWTError, jwt

from packages.platform_contracts.security import AnalyticsIdentity


class AuthenticationError(ValueError):
    """Raised when an identity token cannot be trusted."""


@dataclass(frozen=True)
class OIDCVerifier:
    issuer: str
    audience: str
    jwks: dict[str, Any]
    algorithms: tuple[str, ...] = ("RS256",)

    def verify(self, token: str) -> AnalyticsIdentity:
        try:
            header = jwt.get_unverified_header(token)
            key_id = header.get("kid")
            if not key_id or key_id not in self.jwks:
                raise AuthenticationError("unknown signing key")
            claims = jwt.decode(
                token,
                self.jwks[key_id],
                algorithms=list(self.algorithms),
                issuer=self.issuer,
                audience=self.audience,
                options={"require_iss": True, "require_aud": True, "require_exp": True, "require_sub": True},
            )
        except AuthenticationError:
            raise
        except (JWTError, TypeError, ValueError) as exc:
            raise AuthenticationError("invalid identity token") from exc
        tenant_claims = {value for value in (claims.get("tenant_id"), claims.get("tid")) if value is not None}
        if not tenant_claims:
            raise AuthenticationError("token has no tenant claim")
        if len(tenant_claims) > 1:
            raise AuthenticationError("token tenant claims disagree")
        tenant_id = next(iter(tenant_claims))
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise AuthenticationError("token tenant claim is invalid")
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject.strip():
            raise AuthenticationError("token subject is invalid")
        groups = _string_list(claims.get("groups", []), "groups")
        purposes = _string_list(claims.get("purposes", []), "purposes")
        passthrough = {key: str(value) for key, value in claims.items() if key in _PASSTHROUGH}
        actor = claims.get("act")
        if actor is not None:
            # RFC 8693 actor claim: one level only, naming the acting party. A chain of delegations is refused.
            if (
                not isinstance(actor, dict)
                or set(actor) - {"sub", "client_id"}
                or not isinstance(actor.get("sub"), str)
            ):
                raise AuthenticationError("token actor claim is invalid")
            if not actor["sub"].strip():
                raise AuthenticationError("token actor claim is invalid")
            passthrough["act_sub"] = actor["sub"]
        return AnalyticsIdentity(
            tenant_id=tenant_id, user_id=subject, purposes=purposes, groups=groups, claims=passthrough
        )


_PASSTHROUGH = {"iss", "aud", "sub", "tid", "tenant_id"}


def _string_list(value: object, name: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise AuthenticationError(f"token {name} claim is invalid")
    return list(value)
