"""Issuer-agnostic negative suite for identity tokens (ADS-063).

Each case builds a token that must NEVER yield an identity. The cases talk only to an `Issuer` (mint a token, give the
verifier its keys), so the same list can be pointed at a different issuer by implementing that small interface. Only the
local test issuer is provided; running the suite against a live identity provider is a separate step that needs the
user's explicit authorization and is not wired here.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import jwt

from app.security import OIDCVerifier

ISSUER_URL = "https://issuer.example"
AUDIENCE = "analytics"
SECRET = "local-test-only-secret"


def _b64(value: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).rstrip(b"=").decode()


class LocalIssuer:
    """Signs HS256 tokens with a local secret. Never accepted by any other service."""

    def __init__(self, *, kid: str = "key-1", secret: str = SECRET) -> None:
        self.kid, self.secret = kid, secret

    def verifier(self) -> OIDCVerifier:
        return OIDCVerifier(ISSUER_URL, AUDIENCE, {self.kid: self.secret}, algorithms=("HS256",))

    def claims(self, **overrides: Any) -> dict[str, Any]:
        base: dict[str, Any] = {
            "iss": ISSUER_URL,
            "aud": AUDIENCE,
            "sub": "alice",
            "tid": "tenant-a",
            "groups": ["analyst", "confidential-data"],
            "purposes": ["analytics"],
            "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
        }
        base.update(overrides)
        return {key: value for key, value in base.items() if value is not _DROP}

    def mint(self, *, headers: dict[str, Any] | None = None, secret: str | None = None, **overrides: Any) -> str:
        return jwt.encode(
            self.claims(**overrides),
            secret or self.secret,
            algorithm="HS256",
            headers={"kid": self.kid, **(headers or {})},
        )


_DROP = object()
Case = tuple[str, Callable[[LocalIssuer], str]]


def _unsigned(issuer: LocalIssuer) -> str:
    claims = json.loads(
        json.dumps(issuer.claims(exp=int((datetime.now(timezone.utc) + timedelta(minutes=10)).timestamp())))
    )
    return f"{_b64({'alg': 'none', 'typ': 'JWT', 'kid': issuer.kid})}.{_b64(claims)}."


def _tampered(issuer: LocalIssuer) -> str:
    header, _, signature = issuer.mint().split(".")
    forged = issuer.claims(tid="tenant-b", exp=int((datetime.now(timezone.utc) + timedelta(minutes=10)).timestamp()))
    return f"{header}.{_b64(json.loads(json.dumps(forged, default=str)))}.{signature}"


def _past() -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=5)


NEGATIVE_CASES: list[Case] = [
    ("expired", lambda i: i.mint(exp=_past())),
    ("not_yet_valid", lambda i: i.mint(nbf=datetime.now(timezone.utc) + timedelta(hours=1))),
    ("wrong_issuer", lambda i: i.mint(iss="https://evil.example")),
    ("wrong_audience", lambda i: i.mint(aud="another-service")),
    ("audience_list_without_ours", lambda i: i.mint(aud=["a", "b"])),
    ("missing_audience", lambda i: i.mint(aud=_DROP)),
    ("missing_expiry", lambda i: i.mint(exp=_DROP)),
    ("missing_subject", lambda i: i.mint(sub=_DROP)),
    ("empty_subject", lambda i: i.mint(sub="  ")),
    ("numeric_subject", lambda i: i.mint(sub=12345)),
    ("missing_tenant", lambda i: i.mint(tid=_DROP)),
    ("empty_tenant", lambda i: i.mint(tid="")),
    ("numeric_tenant", lambda i: i.mint(tid=123)),
    ("tenant_claims_disagree", lambda i: i.mint(tid="tenant-a", tenant_id="tenant-b")),
    ("unsigned_alg_none", _unsigned),
    ("wrong_signature", lambda i: i.mint(secret="some-other-secret")),
    ("tampered_payload", _tampered),
    ("unknown_key_id", lambda i: i.mint(headers={"kid": "key-unknown"})),
    ("missing_key_id", lambda i: jwt.encode(i.claims(), i.secret, algorithm="HS256")),
    ("purposes_is_a_string", lambda i: i.mint(purposes="analytics")),
    ("purposes_has_a_non_string", lambda i: i.mint(purposes=["analytics", 7])),
    ("purposes_is_an_object", lambda i: i.mint(purposes={"analytics": True})),
    ("purposes_has_an_empty_entry", lambda i: i.mint(purposes=["analytics", ""])),
    ("groups_is_a_string", lambda i: i.mint(groups="analyst")),
    ("groups_has_a_non_string", lambda i: i.mint(groups=["analyst", None])),
    ("actor_is_a_string", lambda i: i.mint(act="agent-planner")),
    ("actor_without_subject", lambda i: i.mint(act={"client_id": "x"})),
    ("actor_with_empty_subject", lambda i: i.mint(act={"sub": " "})),
    ("actor_chain", lambda i: i.mint(act={"sub": "agent-planner", "act": {"sub": "agent-other"}})),
    ("actor_with_extra_fields", lambda i: i.mint(act={"sub": "agent-planner", "scope": "admin"})),
]
