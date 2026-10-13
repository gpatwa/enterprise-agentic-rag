"""ADS-063: identity and group propagation, delegated-purpose policy, and a negative token suite."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from idp_negative_suite import NEGATIVE_CASES, LocalIssuer
from jose import jwt
from pydantic import ValidationError
from reference_stack.stack import build_stack
from test_ads040_execution_gateways import _contract

from app.agent_tools import AgentToolSurface
from app.api_v2 import V2Runtime, build_v2_router
from app.security import (
    AuthenticationError,
    IdentityResolver,
    InMemoryGroupDirectory,
    OIDCVerifier,
    authorize,
    caller_kind,
)
from packages.platform_contracts.delegation import AgentGrant, DelegationPolicy
from packages.platform_contracts.semantic import SemanticPolicy

SERVICE = Path(__file__).resolve().parent.parent
PROPOSED = SERVICE / "delegation/delegation-policy.proposed.json"
URL = "/api/v2/analytics"


def _policy(*grants: AgentGrant, approved: bool = True) -> DelegationPolicy:
    approval = (
        {"status": "approved", "approved_by": "test-harness", "approved_at": "2026-10-13"}
        if approved
        else {"status": "proposed"}
    )
    return DelegationPolicy(policy_version="test", grants=grants, approval=approval)


PLANNER = AgentGrant(agent_id="agent-planner", purposes=("analytics",), groups=())


def _directory(**users) -> InMemoryGroupDirectory:
    directory = InMemoryGroupDirectory()
    for user, groups in (users or {"alice": ("analyst", "confidential-data")}).items():
        directory.set_user("tenant-a", user, groups)
    return directory


# ---- the negative suite: none of these may ever yield an identity ----


@pytest.mark.parametrize(("name", "build"), NEGATIVE_CASES, ids=[name for name, _ in NEGATIVE_CASES])
def test_malformed_or_untrusted_tokens_never_yield_an_identity(name, build):
    issuer = LocalIssuer()
    resolver = IdentityResolver(issuer.verifier(), directory=_directory())
    with pytest.raises(AuthenticationError):
        resolver.resolve(build(issuer))


def test_the_suite_has_a_positive_control_and_covers_every_failure_family():
    issuer = LocalIssuer()
    identity = IdentityResolver(issuer.verifier(), directory=_directory()).resolve(issuer.mint())
    assert (identity.tenant_id, identity.user_id) == ("tenant-a", "alice")
    assert identity.purposes == ["analytics"] and set(identity.groups) == {"analyst", "confidential-data"}
    names = {name for name, _ in NEGATIVE_CASES}
    for family in (
        "expired",
        "wrong_issuer",
        "wrong_audience",
        "unsigned_alg_none",
        "wrong_signature",
        "unknown_key_id",
        "tenant_claims_disagree",
        "purposes_is_a_string",
        "actor_chain",
        "tampered_payload",
    ):
        assert family in names
    assert len(NEGATIVE_CASES) >= 30


def _rsa_pair():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return private, public


def _hmac_token(claims: dict, secret: str) -> str:
    """Forge an HS256 token by hand; the JWT library itself refuses to HMAC with a PEM key."""
    import base64
    import hashlib
    import hmac
    import json

    def part(value: dict) -> str:
        return (
            base64.urlsafe_b64encode(json.dumps(value, default=lambda v: int(v.timestamp())).encode())
            .rstrip(b"=")
            .decode()
        )

    signing_input = f"{part({'alg': 'HS256', 'typ': 'JWT', 'kid': 'key-1'})}.{part(claims)}"
    signature = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


def test_an_rs256_verifier_rejects_algorithm_confusion_and_wrong_keys():
    private, public = _rsa_pair()
    claims = LocalIssuer().claims()
    verifier = OIDCVerifier("https://issuer.example", "analytics", {"key-1": public}, algorithms=("RS256",))
    good = jwt.encode(claims, private, algorithm="RS256", headers={"kid": "key-1"})
    assert verifier.verify(good).user_id == "alice"
    confused = _hmac_token(claims, public)  # the classic attack: the public key bytes used as an HMAC secret
    with pytest.raises(AuthenticationError):
        verifier.verify(confused)
    other_private, _ = _rsa_pair()
    with pytest.raises(AuthenticationError):
        verifier.verify(jwt.encode(claims, other_private, algorithm="RS256", headers={"kid": "key-1"}))


def test_a_rotated_key_invalidates_tokens_signed_with_the_retired_key():
    old = LocalIssuer(kid="key-old", secret="old-secret")
    token = old.mint()
    rotated = IdentityResolver(
        OIDCVerifier("https://issuer.example", "analytics", {"key-new": "new-secret"}, algorithms=("HS256",)),
        directory=_directory(),
    )
    with pytest.raises(AuthenticationError, match="unknown signing key"):
        rotated.resolve(token)


# ---- group propagation and group changes ----


def test_a_removed_group_takes_effect_on_the_next_request_not_at_token_expiry():
    issuer, directory = LocalIssuer(), _directory()
    resolver = IdentityResolver(issuer.verifier(), directory=directory)
    token = issuer.mint()
    assert "confidential-data" in resolver.resolve(token).groups
    directory.remove_group("tenant-a", "alice", "confidential-data")
    assert resolver.resolve(token).groups == ["analyst"]  # same token, next request
    directory.remove_group("tenant-a", "alice", "analyst")
    assert resolver.resolve(token).groups == []


def test_a_group_added_after_the_token_was_issued_is_never_granted_by_that_token():
    issuer, directory = LocalIssuer(), _directory(alice=("analyst",))
    resolver = IdentityResolver(issuer.verifier(), directory=directory)
    token = issuer.mint(groups=["analyst"])
    directory.add_group("tenant-a", "alice", "restricted-data")
    assert resolver.resolve(token).groups == ["analyst"]  # a new token is needed to carry a new group
    assert resolver.resolve(issuer.mint(groups=["analyst", "restricted-data"])).groups == ["analyst", "restricted-data"]


def test_a_token_cannot_claim_a_group_the_directory_does_not_grant():
    issuer = LocalIssuer()
    resolver = IdentityResolver(issuer.verifier(), directory=_directory(alice=("analyst",)))
    assert resolver.resolve(issuer.mint(groups=["analyst", "restricted-data", "admin"])).groups == ["analyst"]


def test_a_disabled_or_unknown_user_is_refused_even_with_a_valid_token():
    issuer, directory = LocalIssuer(), _directory()
    resolver = IdentityResolver(issuer.verifier(), directory=directory)
    token = issuer.mint()
    assert resolver.resolve(token).user_id == "alice"
    directory.disable("tenant-a", "alice")
    with pytest.raises(AuthenticationError, match="not active"):
        resolver.resolve(token)
    with pytest.raises(AuthenticationError, match="unknown user"):
        resolver.resolve(issuer.mint(sub="mallory"))
    with pytest.raises(AuthenticationError, match="unknown user"):
        resolver.resolve(issuer.mint(tid="tenant-b"))  # the same name in another tenant is another (unknown) person


def test_losing_a_group_changes_the_authorization_decision_for_protected_data():
    contract = _contract().model_copy(
        update={
            "policies": [
                SemanticPolicy(
                    id="conf",
                    target_ids=["revenue"],
                    classification="confidential",
                    allowed_purposes=["analytics"],
                    owner_ids=["team.data"],
                )
            ]
        }
    )
    issuer, directory = LocalIssuer(), _directory(alice=("confidential-data",))
    resolver = IdentityResolver(issuer.verifier(), directory=directory)
    token = issuer.mint(groups=["confidential-data"])
    assert authorize(resolver.resolve(token), contract, {"revenue"}, "analytics").effect == "allow"
    directory.remove_group("tenant-a", "alice", "confidential-data")
    assert authorize(resolver.resolve(token), contract, {"revenue"}, "analytics").effect == "review"


# ---- delegated purposes ----


def _delegated(issuer, **overrides):
    return issuer.mint(act={"sub": "agent-planner"}, purposes=["analytics", "billing"], **overrides)


def test_a_delegated_call_gets_only_the_intersection_of_the_person_and_the_agent():
    issuer = LocalIssuer()
    resolver = IdentityResolver(issuer.verifier(), directory=_directory(), delegation=_policy(PLANNER))
    identity = resolver.resolve(_delegated(issuer))
    assert identity.purposes == ["analytics"]  # the person's "billing" is not the agent's to use
    assert identity.groups == []  # the grant lists no groups, so none carry over
    assert identity.claims["act_sub"] == "agent-planner" and caller_kind(identity) == "agent"
    wider = AgentGrant(agent_id="agent-planner", purposes=("analytics", "reporting"), groups=("analyst",))
    resolver = IdentityResolver(issuer.verifier(), directory=_directory(), delegation=_policy(wider))
    narrow_person = resolver.resolve(issuer.mint(act={"sub": "agent-planner"}, purposes=["analytics"]))
    assert narrow_person.purposes == ["analytics"]  # the agent's grant never widens the person
    assert narrow_person.groups == ["analyst"]


def test_delegation_is_refused_unless_the_policy_is_approved_and_grants_that_agent():
    issuer = LocalIssuer()
    token = _delegated(issuer)
    directory = _directory()
    with pytest.raises(AuthenticationError, match="not enabled"):
        IdentityResolver(issuer.verifier(), directory=directory).resolve(token)
    with pytest.raises(AuthenticationError, match="not enabled"):
        IdentityResolver(issuer.verifier(), directory=directory, delegation=_policy(PLANNER, approved=False)).resolve(
            token
        )
    with pytest.raises(AuthenticationError, match="not granted"):
        IdentityResolver(issuer.verifier(), directory=directory, delegation=_policy()).resolve(token)
    other = AgentGrant(agent_id="agent-other", purposes=("analytics",))
    with pytest.raises(AuthenticationError, match="not granted"):
        IdentityResolver(issuer.verifier(), directory=directory, delegation=_policy(other)).resolve(token)
    scoped = AgentGrant(agent_id="agent-planner", purposes=("analytics",), tenants=("tenant-z",))
    with pytest.raises(AuthenticationError, match="not granted"):
        IdentityResolver(issuer.verifier(), directory=directory, delegation=_policy(scoped)).resolve(token)


def test_the_repository_delegation_policy_is_valid_and_not_approved():
    policy = DelegationPolicy.model_validate_json(PROPOSED.read_text())
    assert not policy.approved and policy.approval.approved_by is None and policy.grants
    issuer = LocalIssuer()
    resolver = IdentityResolver(issuer.verifier(), directory=_directory(), delegation=policy)
    with pytest.raises(AuthenticationError, match="not enabled"):
        resolver.resolve(_delegated(issuer))  # the shipped policy honours nothing until the user approves it


def test_a_delegation_policy_must_be_coherent():
    with pytest.raises(ValidationError, match="at most one grant"):
        _policy(PLANNER, PLANNER)
    with pytest.raises(ValidationError, match="who approved"):
        DelegationPolicy(policy_version="v", approval={"status": "approved"})
    with pytest.raises(ValidationError):
        AgentGrant(agent_id="x", purposes=())


# ---- end to end through the REST and tool surfaces ----


def _app(stack, resolver):
    application = FastAPI()

    async def no_api_key() -> None:
        return None

    runtime = V2Runtime(service=stack.service(), verifier=stack.verifier(), resolver=resolver)
    application.include_router(build_v2_router(runtime, no_api_key))
    return application


def _post(client, token, key="id-key-0001", purpose="analytics"):
    return client.post(
        f"{URL}/analyze",
        json={"request_text": "Show monthly revenue", "purpose": purpose},
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key},
    )


def test_rest_applies_group_changes_delegation_and_failures_per_request(tmp_path):
    stack = build_stack("duckdb", tmp_path / "a")
    directory = InMemoryGroupDirectory()
    directory.set_user("tenant-a", "requester", ("analyst",))
    directory.set_user("tenant-a", "reviewer", ("analyst",))
    resolver = IdentityResolver(stack.verifier(), directory=directory, delegation=_policy(PLANNER))
    client = TestClient(_app(stack, resolver))
    token = stack.token("requester")
    assert _post(client, token).status_code == 200
    assert _post(client, "not-a-token").status_code == 401
    expired = stack.token("requester", ttl_minutes=-5)
    assert _post(client, expired, key="id-key-0002").status_code == 401
    directory.disable("tenant-a", "requester")
    refused = _post(client, token, key="id-key-0003")
    assert (
        refused.status_code == 401 and refused.json()["detail"] == "invalid_identity_token"
    )  # same token, next request


def test_rest_and_tools_treat_a_delegated_token_as_an_agent_that_can_never_review(tmp_path):
    stack = build_stack("duckdb", tmp_path / "paused", review_threshold=1e-9)
    directory = _directory(requester=("analyst",), reviewer=("analyst",))
    resolver = IdentityResolver(stack.verifier(), directory=directory, delegation=_policy(PLANNER))
    client = TestClient(_app(stack, resolver))
    paused = _post(client, stack.token("requester"))
    assert paused.json()["state"] == "waiting_review"
    run_id = paused.json()["run_id"]
    review = stack.control.get_review(paused.json()["outcome"]["review_id"], tenant_id="tenant-a", purpose="analytics")
    body = {"purpose": "analytics", "decision": "approved", "plan_fingerprint": review.plan_fingerprint}
    claims = {
        "iss": stack.verifier().issuer,
        "aud": stack.verifier().audience,
        "sub": "reviewer",
        "tid": "tenant-a",
        "groups": ["analyst"],
        "purposes": ["analytics"],
        "act": {"sub": "agent-planner"},
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    delegated = jwt.encode(claims, stack.secret, algorithm="HS256", headers={"kid": next(iter(stack.verifier().jwks))})
    refused = client.post(f"{URL}/runs/{run_id}/review", json=body, headers={"Authorization": f"Bearer {delegated}"})
    assert refused.status_code == 403 and refused.json()["detail"] == "human_required"
    surface = AgentToolSurface(stack.service(), stack.evidence)
    identity = resolver.resolve(delegated)
    via_tool = surface.call(identity, {"tool": "analytics.review", "arguments": {"run_id": run_id, **body}})
    assert via_tool.error.code == "human_required"
    still = client.get(
        f"{URL}/runs/{run_id}",
        params={"purpose": "analytics"},
        headers={"Authorization": f"Bearer {stack.token('requester')}"},
    )
    assert still.json()["state"] == "waiting_review"
    approved = client.post(
        f"{URL}/runs/{run_id}/review", json=body, headers={"Authorization": f"Bearer {stack.token('reviewer')}"}
    )
    assert approved.status_code == 200 and approved.json()["outcome"]["outcome"] == "answer"


def test_the_default_runtime_is_unchanged_and_the_verifier_still_serves_without_a_resolver(tmp_path):
    stack = build_stack("duckdb", tmp_path / "plain")
    client = TestClient(stack.app())  # the ADS-045 reference app has no resolver
    assert _post(client, stack.token("requester")).status_code == 200
