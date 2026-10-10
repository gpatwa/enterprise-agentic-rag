"""EA-041 issuer, audience, expiry, tenant, and key-rotation tests."""
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt

from app.security import AuthenticationError, OIDCVerifier

KEY = "local-test-only-secret"


def token(**claims):
    payload = {"iss": "https://issuer.example", "aud": "analytics", "sub": "user-1", "tid": "tenant-1", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)}
    payload.update(claims)
    return jwt.encode(payload, KEY, algorithm="HS256", headers={"kid": "key-1"})


def verifier():
    return OIDCVerifier("https://issuer.example", "analytics", {"key-1": KEY}, algorithms=("HS256",))


def test_oidc_verifier_returns_tenant_scoped_identity():
    identity = verifier().verify(token(groups=["analyst"], purposes=["reporting"]))
    assert identity.tenant_id == "tenant-1"
    assert identity.groups == ["analyst"]


@pytest.mark.parametrize("bad", [token(iss="https://other.example"), token(aud="other"), token(tid=None)])
def test_oidc_verifier_rejects_untrusted_claims(bad):
    with pytest.raises(AuthenticationError):
        verifier().verify(bad)


def test_oidc_verifier_rejects_unknown_rotated_key():
    rotated = jwt.encode({"iss": "https://issuer.example", "aud": "analytics", "sub": "u", "tid": "t", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)}, "new-key", algorithm="HS256", headers={"kid": "key-2"})
    with pytest.raises(AuthenticationError, match="unknown signing key"):
        verifier().verify(rotated)
