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
        tenant_id = claims.get("tenant_id") or claims.get("tid")
        if not tenant_id:
            raise AuthenticationError("token has no tenant claim")
        groups = claims.get("groups", [])
        if not isinstance(groups, list) or not all(isinstance(group, str) for group in groups):
            raise AuthenticationError("token groups claim is invalid")
        return AnalyticsIdentity(
            tenant_id=str(tenant_id),
            user_id=str(claims["sub"]),
            purposes=[str(purpose) for purpose in claims.get("purposes", [])],
            groups=groups,
            claims={key: str(value) for key, value in claims.items() if key in {"iss", "aud", "sub", "tid", "tenant_id"}},
        )
