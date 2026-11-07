"""The verifier against the claim set a real Entra *v2* access token for this app carries.

The shapes below follow Microsoft's documented v2.0 access-token payload (``ver`` 2.0, ``aud`` the API's client id GUID,
``iss`` ``https://login.microsoftonline.com/<tid>/v2.0``, delegated scopes in ``scp``) and the v1 shape an app gets when
``requested_access_token_version`` is left unset (``aud`` ``api://<client id>``, ``iss`` ``https://sts.windows.net/<tid>/``).
Signing keys are generated locally; nothing here talks to Entra, and no real tenant data is used.
"""

from __future__ import annotations

import base64
import time

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt

from app.config import settings_from_env
from app.security import AuthError, TokenVerifier

TENANT = "9e0cfba8-0000-4000-8000-000000000001"  # the directory
CLIENT_ID = "5d2f7c1e-0000-4000-8000-0000000000aa"  # the app registration: web sign-in and API in one
OID = "22222222-2222-4222-8222-222222222222"
SCOPE = "access_as_user"
NOW = int(time.time())


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


_PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PEM = _PRIVATE.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
)
_NUMBERS = _PRIVATE.public_key().public_numbers()
_JWKS = {
    "keys": [
        {
            "kty": "RSA",
            "kid": "v2-key",
            "use": "sig",
            "alg": "RS256",
            "n": _b64(_NUMBERS.n.to_bytes(256, "big")),
            "e": _b64(_NUMBERS.e.to_bytes(3, "big")),
        }
    ]
}


def v2_access_token_claims(**over: object) -> dict[str, object]:
    """A v2.0 delegated access token for the app, as issued to the single-page app for ``access_as_user``."""
    claims: dict[str, object] = {
        "aud": CLIENT_ID,
        "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0",
        "iat": NOW,
        "nbf": NOW,
        "exp": NOW + 3600,
        "aio": "opaque-activity-id",
        "azp": CLIENT_ID,  # the SPA is the same registration
        "azpacr": "0",
        "name": "Demo Operator",
        "oid": OID,
        "preferred_username": "operator@example.invalid",
        "rh": "opaque",
        "scp": SCOPE,
        "sub": "pairwise-subject",
        "tid": TENANT,
        "uti": "opaque",
        "ver": "2.0",
    }
    claims.update(over)
    return {k: v for k, v in claims.items() if v is not None}


def _sign(claims: dict[str, object]) -> str:
    return jwt.encode(claims, _PEM, "RS256", headers={"kid": "v2-key"})


def _verifier(**kw: object) -> TokenVerifier:
    return TokenVerifier(
        entra_tenant_id=TENANT,
        audience=CLIENT_ID,
        tenant_map={TENANT: "tenant-01"},
        principal_map={OID: "user-0001"},
        required_scope=SCOPE,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=_JWKS)),
        **kw,  # type: ignore[arg-type]
    )


def _refused(token: str, reason: str) -> None:
    with pytest.raises(AuthError) as raised:
        _verifier().verify(token)
    assert raised.value.status == 401 and reason in raised.value.reason


def test_a_realistic_v2_access_token_is_accepted_and_mapped() -> None:
    identity = _verifier().verify(_sign(v2_access_token_claims()))
    assert (identity.tenant_id, identity.principal_id, identity.subject) == ("tenant-01", "user-0001", OID)


def test_extra_scopes_alongside_the_required_one_are_accepted() -> None:
    assert _verifier().verify(_sign(v2_access_token_claims(scp=f"User.Read {SCOPE}"))).principal_id == "user-0001"


def test_the_default_issuer_is_the_v2_form_not_the_v1_form() -> None:
    _refused(_sign(v2_access_token_claims(iss=f"https://sts.windows.net/{TENANT}/")), "invalid token")


def test_a_v1_access_token_is_refused_so_a_missing_version_setting_fails_closed() -> None:
    """With requested_access_token_version unset the app gets v1 tokens: aud api://<id>, iss sts.windows.net."""
    v1 = v2_access_token_claims(
        aud=f"api://{CLIENT_ID}", iss=f"https://sts.windows.net/{TENANT}/", ver="1.0", appid=CLIENT_ID
    )
    _refused(_sign(v1), "invalid token")


def test_an_id_token_for_the_same_app_is_not_an_api_token() -> None:
    """The ID token has the same audience, issuer and tenant but no delegated scope: the scope check refuses it."""
    id_token = v2_access_token_claims(scp=None, nonce="n", azp=None)
    _refused(_sign(id_token), "scope")


def test_a_token_for_a_different_scope_is_refused() -> None:
    _refused(_sign(v2_access_token_claims(scp="User.Read")), "scope")


def test_a_token_from_another_directory_is_refused() -> None:
    other = "aaaaaaaa-0000-4000-8000-00000000000b"
    _refused(_sign(v2_access_token_claims(tid=other, iss=f"https://login.microsoftonline.com/{other}/v2.0")), "invalid")


def test_the_scope_check_is_off_unless_configured() -> None:
    verifier = TokenVerifier(
        entra_tenant_id=TENANT,
        audience=CLIENT_ID,
        tenant_map={TENANT: "tenant-01"},
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=_JWKS)),
    )
    assert verifier.verify(_sign(v2_access_token_claims(scp=None))).tenant_id == "tenant-01"


def test_settings_carry_the_audience_as_the_bare_client_id_and_the_scope_name() -> None:
    settings = settings_from_env(
        {
            "DISCOVERY_AUTH_ENABLED": "true",
            "DISCOVERY_ENTRA_TENANT_ID": TENANT,
            "DISCOVERY_ENTRA_AUDIENCE": CLIENT_ID,
            "DISCOVERY_ENTRA_REQUIRED_SCOPE": SCOPE,
            "DISCOVERY_ENTRA_TENANT_MAP": f'{{"{TENANT}": "tenant-01"}}',
        }
    )
    assert settings.entra_audience == CLIENT_ID and settings.entra_required_scope == SCOPE
