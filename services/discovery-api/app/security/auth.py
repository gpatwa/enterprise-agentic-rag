"""Verify Entra ID bearer tokens and make the verified identity authoritative for every request.

When ``auth_enabled`` is true each route requires ``Authorization: Bearer <jwt>``. The token is checked for an
RS256 signature against the tenant's published keys, issuer, audience and expiry. The tenant and principal then
come from the token (through configured maps), never from the request body: any ``tenant_id`` / ``principal_id`` /
``user_id`` the client sent is overwritten. Everything fails closed: a missing, malformed, expired or unmapped
token is refused with a generic message and the reason goes only to the server log, never the token itself.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping

import httpx
from fastapi import Request
from jose import JWTError, jwt

logger = logging.getLogger(__name__)

ALGORITHMS = ["RS256"]
JWKS_MIN_REFRESH_SECONDS = 60.0


class AuthError(Exception):
    """Authentication failed. ``status`` is 401 (credentials) or 403 (valid token, no access) or 503."""

    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


@dataclass(frozen=True)
class Identity:
    tenant_id: str
    principal_id: str
    subject: str  # the token's object id, kept for audit


class TokenVerifier:
    def __init__(
        self,
        *,
        entra_tenant_id: str,
        audience: str,
        tenant_map: Mapping[str, str],
        principal_map: Mapping[str, str] | None = None,
        jwks_url: str | None = None,
        issuer: str | None = None,
        required_scope: str | None = None,
        leeway_seconds: int = 60,
        jwks_ttl_seconds: float = 3600.0,
        timeout: float = 5.0,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not entra_tenant_id or not audience or not tenant_map:
            raise ValueError("entra_tenant_id, audience and a tenant map are required")
        self._entra_tenant = entra_tenant_id
        self._audience = audience
        self._tenant_map = dict(tenant_map)
        self._principal_map = dict(principal_map or {})
        self._required_scope = required_scope
        self._issuer = issuer or f"https://login.microsoftonline.com/{entra_tenant_id}/v2.0"
        self._jwks_url = jwks_url or f"https://login.microsoftonline.com/{entra_tenant_id}/discovery/v2.0/keys"
        self._leeway = leeway_seconds
        self._ttl = jwks_ttl_seconds
        self._clock = clock
        self._http = httpx.Client(timeout=timeout, transport=transport)
        self._lock = threading.Lock()
        self._keys: dict[str, dict[str, Any]] = {}
        self._fetched_at = -1e18

    def _refresh(self, *, force: bool) -> None:
        now = self._clock()
        with self._lock:
            age = now - self._fetched_at
            if not force and age < self._ttl and self._keys:
                return
            if force and age < JWKS_MIN_REFRESH_SECONDS:
                return  # an unknown kid must not let a caller make us refetch on every request
            try:
                response = self._http.get(self._jwks_url)
                response.raise_for_status()
                keys = {k["kid"]: k for k in response.json()["keys"] if k.get("kty") == "RSA" and "kid" in k}
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                logger.warning("jwks fetch failed: %s", type(exc).__name__)
                if not self._keys:
                    raise AuthError(503, "signing keys unavailable") from exc
                return  # keep serving with the cached keys
            self._keys, self._fetched_at = keys, now

    def _key_for(self, kid: str) -> dict[str, Any]:
        self._refresh(force=False)
        if kid not in self._keys:
            self._refresh(force=True)
        key = self._keys.get(kid)
        if key is None:
            raise AuthError(401, "unknown signing key")
        return key

    def verify(self, token: str) -> Identity:
        try:
            header = jwt.get_unverified_header(token)
        except JWTError as exc:
            raise AuthError(401, "malformed token") from exc
        if header.get("alg") not in ALGORITHMS:
            raise AuthError(401, "unsupported algorithm")
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise AuthError(401, "no key id")
        key = self._key_for(kid)
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=ALGORITHMS,
                audience=self._audience,
                issuer=self._issuer,
                options={"leeway": self._leeway, "require_exp": True, "require_iat": False},
            )
        except JWTError as exc:
            raise AuthError(401, f"invalid token ({type(exc).__name__})") from exc
        if claims.get("tid") != self._entra_tenant:
            raise AuthError(401, "wrong directory")
        if self._required_scope and self._required_scope not in str(claims.get("scp", "")).split():
            # An ID token for this same app carries the same audience; only an access token for the exposed scope passes.
            raise AuthError(401, "token lacks the required scope")
        subject = claims.get("oid")
        if not isinstance(subject, str) or not subject:
            raise AuthError(401, "no object id")
        tenant = self._tenant_map.get(self._entra_tenant)
        if tenant is None:
            raise AuthError(403, "directory not mapped to a tenant")
        return Identity(tenant_id=tenant, principal_id=self._principal_map.get(subject, subject), subject=subject)


_PUBLIC_401 = "authentication required"
_PUBLIC_403 = "access denied"


def require_identity(request: Request) -> Identity | None:
    """FastAPI dependency: ``None`` when auth is off, otherwise the verified identity or an HTTP error."""
    from fastapi import HTTPException

    verifier: TokenVerifier | None = getattr(request.app.state, "auth_verifier", None)
    if verifier is None:
        return None
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail=_PUBLIC_401, headers={"WWW-Authenticate": "Bearer"})
    try:
        return verifier.verify(token.strip())
    except AuthError as exc:
        logger.info("auth refused: %s", exc.reason)
        if exc.status == 503:
            raise HTTPException(status_code=503, detail="authentication unavailable") from exc
        detail = _PUBLIC_403 if exc.status == 403 else _PUBLIC_401
        raise HTTPException(status_code=exc.status, detail=detail, headers={"WWW-Authenticate": "Bearer"}) from exc


def bind_identity(model: Any, identity: Identity | None) -> Any:
    """Return the request with tenant and principal overwritten from the identity (unchanged when auth is off)."""
    if identity is None:
        return model
    if hasattr(model, "context"):
        context = model.context.model_copy(
            update={"tenant_id": identity.tenant_id, "principal_id": identity.principal_id}
        )
        return model.model_copy(update={"context": context})
    return model.model_copy(update={"tenant_id": identity.tenant_id, "user_id": identity.principal_id})
