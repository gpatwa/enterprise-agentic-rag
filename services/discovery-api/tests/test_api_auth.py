"""Entra bearer-token verification and identity binding, with locally generated keys and a mock JWKS endpoint."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jose import jwt

from app.config import DiscoverySettings, settings_from_env
from app.main import create_app
from app.security import AuthError, TokenVerifier

TID = "11111111-1111-1111-1111-111111111111"
AUD = "api-client-id"
ISS = f"https://login.microsoftonline.com/{TID}/v2.0"
OID = "22222222-2222-2222-2222-222222222222"
NOW = float(int(time.time()))  # python-jose checks exp/nbf against real time, so tokens are minted relative to it


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class Keys:
    def __init__(self, kid: str) -> None:
        self.kid = kid
        self.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.private_pem = self.private.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
        self.public_pem = self.private.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        numbers = self.private.public_key().public_numbers()
        self.jwk = {
            "kty": "RSA",
            "kid": kid,
            "use": "sig",
            "alg": "RS256",
            "n": _b64(numbers.n.to_bytes(256, "big")),
            "e": _b64(numbers.e.to_bytes(3, "big")),
        }

    def token(self, **over) -> str:
        claims = {"iss": ISS, "aud": AUD, "tid": TID, "oid": OID, "iat": NOW, "nbf": NOW, "exp": NOW + 3600}
        claims.update(over)
        return jwt.encode(
            {k: v for k, v in claims.items() if v is not None}, self.private_pem, "RS256", headers={"kid": self.kid}
        )


KEYS = Keys("key-1")
OTHER = Keys("key-1")  # same kid, different key: a forged signature


class Jwks:
    """A mock JWKS endpoint that counts fetches and can be switched to fail."""

    def __init__(self, *keys: Keys) -> None:
        self.keys = list(keys)
        self.fetches = 0
        self.fail = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.fetches += 1
        if self.fail:
            return httpx.Response(500)
        return httpx.Response(200, json={"keys": [k.jwk for k in self.keys]})


def _verifier(jwks: Jwks, clock=lambda: NOW, **kw) -> TokenVerifier:
    return TokenVerifier(
        entra_tenant_id=TID,
        audience=AUD,
        tenant_map={TID: "tenant-01"},
        principal_map={OID: "user-0001"},
        transport=httpx.MockTransport(jwks),
        clock=clock,
        **kw,
    )


def _refuses(verifier: TokenVerifier, token: str, status: int = 401) -> None:
    with pytest.raises(AuthError) as raised:
        verifier.verify(token)
    assert raised.value.status == status


# ---- the verifier -------------------------------------------------------------------------------------------


def test_a_valid_token_yields_the_mapped_identity() -> None:
    identity = _verifier(Jwks(KEYS)).verify(KEYS.token())
    assert (identity.tenant_id, identity.principal_id, identity.subject) == ("tenant-01", "user-0001", OID)


def test_an_unmapped_object_id_keeps_its_own_id_which_has_no_profile() -> None:
    other = "33333333-3333-3333-3333-333333333333"
    assert _verifier(Jwks(KEYS)).verify(KEYS.token(oid=other)).principal_id == other


@pytest.mark.parametrize(
    "over",
    [
        {"exp": NOW - 3600},  # expired
        {"exp": NOW - 61},  # just beyond the 60 s leeway
        {"aud": "someone-else"},
        {"iss": "https://login.microsoftonline.com/other/v2.0"},
        {"tid": "99999999-9999-9999-9999-999999999999"},
        {"oid": None},
        {"exp": None},
    ],
)
def test_bad_claims_are_refused(over: dict) -> None:
    _refuses(_verifier(Jwks(KEYS)), KEYS.token(**over))


def test_leeway_allows_small_clock_skew() -> None:
    assert _verifier(Jwks(KEYS)).verify(KEYS.token(exp=NOW - 30)).tenant_id == "tenant-01"


def test_a_forged_signature_with_a_known_kid_is_refused() -> None:
    _refuses(_verifier(Jwks(KEYS)), OTHER.token())


def test_a_tampered_payload_is_refused() -> None:
    header, payload, signature = KEYS.token().split(".")
    forged = json.loads(base64.urlsafe_b64decode(payload + "=="))
    forged["oid"] = "44444444-4444-4444-4444-444444444444"
    _refuses(_verifier(Jwks(KEYS)), ".".join([header, _b64(json.dumps(forged).encode()), signature]))


def test_alg_none_is_refused() -> None:
    header = _b64(json.dumps({"alg": "none", "kid": "key-1", "typ": "JWT"}).encode())
    payload = _b64(json.dumps({"iss": ISS, "aud": AUD, "tid": TID, "oid": OID, "exp": NOW + 3600}).encode())
    _refuses(_verifier(Jwks(KEYS)), f"{header}.{payload}.")


def test_hmac_signed_with_the_public_key_is_refused() -> None:
    """The classic algorithm-confusion attack: HS256 using the RSA public key bytes as the secret."""
    header = _b64(json.dumps({"alg": "HS256", "kid": "key-1", "typ": "JWT"}).encode())
    payload = _b64(json.dumps({"iss": ISS, "aud": AUD, "tid": TID, "oid": OID, "exp": NOW + 3600}).encode())
    signature = _b64(hmac.new(KEYS.public_pem, f"{header}.{payload}".encode(), hashlib.sha256).digest())
    _refuses(_verifier(Jwks(KEYS)), f"{header}.{payload}.{signature}")


@pytest.mark.parametrize("token", ["", "abc", "a.b.c", "not.a.jwt.at.all"])
def test_malformed_tokens_are_refused(token: str) -> None:
    _refuses(_verifier(Jwks(KEYS)), token)


def test_a_token_with_an_unknown_kid_is_refused() -> None:
    _refuses(_verifier(Jwks(KEYS)), Keys("other-kid").token())


# ---- key handling -------------------------------------------------------------------------------------------


def test_keys_are_cached_between_requests() -> None:
    jwks = Jwks(KEYS)
    verifier = _verifier(jwks)
    verifier.verify(KEYS.token())
    verifier.verify(KEYS.token())
    assert jwks.fetches == 1


def test_a_rotated_key_is_picked_up_but_unknown_kids_cannot_cause_a_refetch_storm() -> None:
    now = [NOW]
    jwks = Jwks(KEYS)
    verifier = _verifier(jwks, clock=lambda: now[0])
    verifier.verify(KEYS.token())
    rotated = Keys("key-2")
    jwks.keys = [rotated]
    now[0] += 120  # past the minimum refresh interval
    assert verifier.verify(rotated.token()).tenant_id == "tenant-01"
    fetches = jwks.fetches
    for _ in range(5):
        _refuses(verifier, Keys("attacker-kid").token())
    assert jwks.fetches - fetches <= 1


def test_no_keys_and_a_failing_endpoint_fails_closed_with_503() -> None:
    jwks = Jwks(KEYS)
    jwks.fail = True
    _refuses(_verifier(jwks), KEYS.token(), status=503)


def test_a_failing_endpoint_keeps_serving_with_cached_keys() -> None:
    jwks = Jwks(KEYS)
    now = [NOW]
    verifier = _verifier(jwks, clock=lambda: now[0], jwks_ttl_seconds=10.0)
    verifier.verify(KEYS.token())
    jwks.fail = True
    now[0] += 30
    assert verifier.verify(KEYS.token()).tenant_id == "tenant-01"


# ---- the API ------------------------------------------------------------------------------------------------

BODY = {
    "query": "workshop",
    "context": {
        "tenant_id": "tenant-01",
        "principal_id": "user-0001",
        "request_id": "r1",
        "locale": "en-US",
        "device": "web",
        "age": 16,
        "purpose": "search",
    },
    "page": 1,
    "page_size": 10,
}


@pytest.fixture
def secured() -> TestClient:
    application = create_app()
    application.state.auth_verifier = _verifier(Jwks(KEYS), clock=time.time)
    return TestClient(application)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _fresh(**over) -> str:
    now = time.time()
    return KEYS.token(iat=now, nbf=now, exp=now + 3600, **over)


def test_health_stays_open(secured: TestClient) -> None:
    assert secured.get("/health").status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Basic abc"},
        {"Authorization": "Bearer"},
        {"Authorization": "Bearer junk"},
        {"Authorization": "bearer "},
    ],
)
def test_every_route_requires_a_valid_bearer_token(secured: TestClient, headers: dict) -> None:
    routes = [
        ("post", "/api/discovery/v1/search", BODY),
        ("post", "/api/discovery/v1/home", {"context": BODY["context"], "page_size": 3}),
        ("post", "/api/discovery/interactions", {}),
        ("post", "/api/discovery/feedback", {}),
        ("get", "/api/discovery/explanations/anything", None),
    ]
    for method, path, body in routes:
        response = getattr(secured, method)(path, headers=headers, **({"json": body} if body is not None else {}))
        assert response.status_code == 401, (path, response.text)
        assert response.json()["detail"] == "authentication required"
        assert "Bearer" in response.headers.get("www-authenticate", "")


def test_a_valid_token_reaches_the_route(secured: TestClient) -> None:
    response = secured.post("/api/discovery/v1/search", json=BODY, headers=_bearer(_fresh()))
    assert response.status_code == 200 and response.json()["results"]


def test_the_body_cannot_choose_the_tenant_or_principal(secured: TestClient) -> None:
    """A token for tenant-01 / user-0001 gets exactly tenant-01 / user-0001's results, whatever the body claims."""
    honest = secured.post("/api/discovery/v1/search", json=BODY, headers=_bearer(_fresh())).json()
    lying_body = {**BODY, "context": {**BODY["context"], "tenant_id": "tenant-02", "principal_id": "user-0013"}}
    lied = secured.post("/api/discovery/v1/search", json=lying_body, headers=_bearer(_fresh())).json()
    assert [r["experience_id"] for r in lied["results"]] == [r["experience_id"] for r in honest["results"]]


def test_without_auth_the_body_still_decides_which_is_why_the_flag_exists() -> None:
    open_client = TestClient(create_app())
    other = {**BODY, "context": {**BODY["context"], "tenant_id": "tenant-02", "principal_id": "user-0013"}}
    a = open_client.post("/api/discovery/v1/search", json=BODY).json()
    b = open_client.post("/api/discovery/v1/search", json=other).json()
    assert [r["experience_id"] for r in a["results"]] != [r["experience_id"] for r in b["results"]]


def test_an_expired_token_is_refused_on_a_route(secured: TestClient) -> None:
    now = time.time()
    token = KEYS.token(iat=now - 7200, nbf=now - 7200, exp=now - 3600)
    assert secured.post("/api/discovery/v1/search", json=BODY, headers=_bearer(token)).status_code == 401


def test_error_responses_do_not_leak_why(secured: TestClient) -> None:
    for token in (_fresh(aud="nope"), _fresh(tid="9"), OTHER.token()):
        response = secured.post("/api/discovery/v1/search", json=BODY, headers=_bearer(token))
        assert response.status_code == 401 and response.json() == {"detail": "authentication required"}


# ---- configuration ------------------------------------------------------------------------------------------


def test_auth_enabled_requires_the_directory_audience_and_a_mapped_tenant() -> None:
    with pytest.raises(ValueError, match="entra_tenant_id and entra_audience"):
        DiscoverySettings(auth_enabled=True)
    with pytest.raises(ValueError, match="entra_tenant_map"):
        DiscoverySettings(auth_enabled=True, entra_tenant_id=TID, entra_audience=AUD)
    assert DiscoverySettings(
        auth_enabled=True, entra_tenant_id=TID, entra_audience=AUD, entra_tenant_map={TID: "tenant-01"}
    ).auth_enabled


def test_environment_variables_configure_auth_and_reject_bad_maps() -> None:
    env = {
        "DISCOVERY_AUTH_ENABLED": "true",
        "DISCOVERY_ENTRA_TENANT_ID": TID,
        "DISCOVERY_ENTRA_AUDIENCE": AUD,
        "DISCOVERY_ENTRA_TENANT_MAP": json.dumps({TID: "tenant-01"}),
        "DISCOVERY_ENTRA_PRINCIPAL_MAP": json.dumps({OID: "user-0001"}),
    }
    settings = settings_from_env(env)
    assert settings.entra_principal_map == {OID: "user-0001"}
    for bad in ("not json", "[1]", json.dumps({"a": 1})):
        with pytest.raises(ValueError, match="JSON object of strings"):
            settings_from_env({**env, "DISCOVERY_ENTRA_TENANT_MAP": bad})
