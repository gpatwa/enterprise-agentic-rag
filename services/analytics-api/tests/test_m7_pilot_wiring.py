"""The production wiring of the governed v2 runtime: end to end with local stand-ins, and the Entra ID verifier."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jose import jwt
from reference_stack.fakes import ScriptedIntentClient, seed_lake
from reference_stack.stack import SERVICE_ROOT, build_stack

from app.api_v2 import V2Runtime, build_v2_router
from app.compiler import DuckDBCompilerAdapter
from app.compiler.service import CertifiedIntentCompiler
from app.context.registry_context import CertifiedContracts, SnapshotSearch, context_from_contract
from app.execution import DuckDBGateway
from app.runtime.evidence_store import EvidenceStore
from app.runtime.pilot_wiring import DEFAULT_ROLE_MAP, GovernedRuntime, build_pilot_runtime
from app.security.entra import EntraVerifier
from app.security.oidc import AuthenticationError
from app.semantic_registry import SemanticRegistry

REGISTRY = SERVICE_ROOT / "semantic_registry"
DOCUMENT = SemanticRegistry(REGISTRY).get_certified("sales-core", "v1")
URL = "/api/v2/analytics"


async def _no_key() -> None:
    return None


def _client(runtime: GovernedRuntime, verifier) -> TestClient:
    app = FastAPI()
    app.include_router(
        build_v2_router(
            V2Runtime(service=runtime.service(), verifier=verifier, feedback=runtime.feedback_service()), _no_key
        )
    )
    return TestClient(app)


def _local_runtime(tmp_path, **overrides) -> tuple[GovernedRuntime, object]:
    stack = build_stack("duckdb", tmp_path / "control")  # only for a migrated control database and a local token issuer
    parquet = seed_lake(tmp_path / "lake")
    runtime = GovernedRuntime(
        control=stack.control,
        evidence=EvidenceStore(stack.control.engine),
        gateway=DuckDBGateway({"sales_orders": parquet}, allowed_root=tmp_path / "lake"),
        compiler=CertifiedIntentCompiler(REGISTRY, DuckDBCompilerAdapter()),
        contracts=CertifiedContracts([DOCUMENT]),
        contexts={"tenant-a": context_from_contract(DOCUMENT)},
        model_factory=lambda request_id: ScriptedIntentClient(request_id),
        **overrides,
    )
    return runtime, stack


def test_the_wired_runtime_answers_end_to_end_and_only_the_requester_sees_the_rows(tmp_path):
    runtime, stack = _local_runtime(tmp_path)
    client = _client(runtime, stack.verifier())
    auth = {"Authorization": f"Bearer {stack.token('requester')}", "Idempotency-Key": "pilot-key-000001"}
    reply = client.post(
        f"{URL}/analyze", json={"request_text": "Show monthly revenue", "purpose": "analytics"}, headers=auth
    )
    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert body["state"] == "terminal" and body["outcome"]["outcome"] == "answer"
    assert len(body["outcome"]["result"]["rows"]) == 3 and body["outcome"]["explanation_status"] in {
        "grounded",
        "evidence_only",
    }
    colleague = client.get(
        f"{URL}/runs/{body['run_id']}",
        params={"purpose": "analytics"},
        headers={"Authorization": f"Bearer {stack.token('colleague')}"},
    )
    assert colleague.status_code == 403


def test_a_tenant_without_a_contract_cannot_start_a_run(tmp_path):
    runtime, stack = _local_runtime(tmp_path)
    client = _client(runtime, stack.verifier())
    headers = {
        "Authorization": f"Bearer {stack.token('requester', tenant='tenant-z')}",
        "Idempotency-Key": "pilot-key-000002",
    }
    reply = client.post(
        f"{URL}/analyze", json={"request_text": "Show monthly revenue", "purpose": "analytics"}, headers=headers
    )
    assert reply.status_code == 403 and reply.json()["detail"] == "snapshot_tenant_mismatch"


def test_outside_dev_the_runtime_refuses_to_start_without_a_strong_run_id_key(tmp_path):
    runtime, _ = _local_runtime(tmp_path, require_run_id_key=True)
    with pytest.raises(ValueError, match="run_id_key"):
        runtime.service()
    keyed, _ = _local_runtime(tmp_path / "k", require_run_id_key=True, run_id_key=b"k" * 32)
    keyed.service()


def test_the_registry_context_holds_only_certified_assets_and_search_never_returns_an_empty_pack():
    context, ontology = context_from_contract(DOCUMENT)
    assert context.tenant_id == "tenant-a" and all(asset.certified for asset in context.metadata_assets)
    assert {n.node_id for n in ontology.nodes} >= {"orders", "revenue"}
    hits = SnapshotSearch(context).search(
        "nothing matches this", tenant_id="tenant-a", snapshot_id=context.snapshot_id, limit=3
    )
    assert hits and hits[0].citation.startswith(f"context:{context.snapshot_id}")
    assert SnapshotSearch(context).search("revenue", tenant_id="tenant-b", snapshot_id=context.snapshot_id) == ()


# ---- Entra ID ----


def _keypair():
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


ENTRA_TENANT = "11111111-2222-3333-4444-555555555555"
ISSUER = f"https://login.microsoftonline.com/{ENTRA_TENANT}/v2.0"


def _entra(fetch_calls: list, keys: dict) -> EntraVerifier:
    def fetch(url):
        fetch_calls.append(url)
        return dict(keys)

    return EntraVerifier(
        issuer=ISSUER,
        audience="api://analytics",
        jwks_url="https://example.invalid/keys",
        tenant_map={ENTRA_TENANT: "tenant-a"},
        role_map=DEFAULT_ROLE_MAP,
        fetch=fetch,
    )


def _token(private, kid="k1", **claims):
    body = {
        "iss": ISSUER,
        "aud": "api://analytics",
        "sub": "pairwise-sub",
        "oid": "object-id-1",
        "tid": ENTRA_TENANT,
        "roles": ["Analytics.Analyst"],
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        **claims,
    }
    return jwt.encode(body, private, algorithm="RS256", headers={"kid": kid})


def test_an_entra_token_maps_roles_to_purposes_and_groups_and_its_tenant_to_the_analytics_tenant():
    private, public = _keypair()
    calls: list = []
    verifier = _entra(calls, {"k1": public})
    who = verifier.verify(_token(private))
    assert (who.tenant_id, who.user_id, who.purposes, who.groups) == (
        "tenant-a",
        "object-id-1",
        ["analytics"],
        ["analyst"],
    )
    reviewer = verifier.verify(_token(private, roles=["Analytics.Analyst", "Analytics.Reviewer"]))
    assert reviewer.groups == ["analyst", "analytics-reviewer"]
    nobody = verifier.verify(_token(private, roles=["Something.Else"]))
    assert nobody.purposes == [] and nobody.groups == []
    assert calls == ["https://example.invalid/keys"]  # keys fetched once and cached


@pytest.mark.parametrize(
    "claims",
    [
        {"tid": "99999999-0000-0000-0000-000000000000"},
        {"aud": "api://someone-else"},
        {"iss": "https://evil.example/v2.0"},
        {"exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
        {"roles": "Analytics.Analyst"},
        {"act": {"sub": "agent", "act": {"sub": "deeper"}}},
    ],
)
def test_hostile_or_foreign_entra_tokens_are_refused(claims):
    private, public = _keypair()
    with pytest.raises(AuthenticationError):
        _entra([], {"k1": public}).verify(_token(private, **claims))


def test_a_forged_signature_or_an_unknown_key_is_refused_and_a_rotated_key_is_refetched_once():
    private, public = _keypair()
    other_private, _ = _keypair()
    calls: list = []
    keys = {"k1": public}
    verifier = _entra(calls, keys)
    with pytest.raises(AuthenticationError):
        verifier.verify(_token(other_private))
    with pytest.raises(AuthenticationError, match="unknown signing key"):
        verifier.verify(_token(private, kid="k2"))
    new_private, new_public = _keypair()
    keys["k2"] = new_public  # the tenant rotated its keys
    assert verifier.verify(_token(new_private, kid="k2")).user_id == "object-id-1"


# ---- the full builder against PostgreSQL ----

PG = os.environ.get("ANALYTICS_TEST_POSTGRES_URL")


@pytest.mark.skipif(not PG, reason="needs ANALYTICS_TEST_POSTGRES_URL (a disposable PostgreSQL server)")
def test_build_pilot_runtime_migrates_and_answers_against_postgresql(tmp_path):
    from sqlalchemy import create_engine, text

    admin = create_engine(PG, isolation_level="AUTOCOMMIT")
    control_db, warehouse_db = f"ctl_{uuid.uuid4().hex[:8]}", f"wh_{uuid.uuid4().hex[:8]}"
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{control_db}"'))
        connection.execute(text(f'CREATE DATABASE "{warehouse_db}"'))
    base = PG.rsplit("/", 1)[0]
    try:
        warehouse = create_engine(f"{base}/{warehouse_db}")
        with warehouse.begin() as connection:
            connection.execute(
                text("""CREATE TABLE sales_orders AS SELECT 'o' || i AS id, CAST(i AS NUMERIC(12,2)) AS amount,
                CASE WHEN i % 5 = 0 THEN 'refunded' ELSE 'paid' END AS status,
                TIMESTAMPTZ '2024-01-01 00:00:00+00' + make_interval(hours => i * 20) AS created_at FROM generate_series(1, 100) AS i""")
            )
        warehouse.dispose()
        stack = build_stack("duckdb", tmp_path)  # a local token issuer only
        settings = SimpleNamespace(
            ENV="prod",
            ANALYTICS_CONTROL_DB_URL=f"{base}/{control_db}",
            ANALYTICS_DB_URL=f"{base}/{warehouse_db}",
            ANALYTICS_MIGRATE_ON_START=True,
            ANALYTICS_SEMANTIC_REGISTRY_PATH=str(REGISTRY),
            ANALYTICS_V2_CONTRACTS="sales-core@v1",
            ANALYTICS_LEASE_SECONDS=120,
            ANALYTICS_MIN_COHORT=None,
            ANALYTICS_REVIEW_COST_THRESHOLD=1e9,
            ANALYTICS_RUN_MAX_COST_UNITS=1e9,
            ANALYTICS_RUN_ID_KEY="k" * 32,
        )
        runtime = build_pilot_runtime(
            settings, model_factory=lambda request_id: ScriptedIntentClient(request_id), verifier=stack.verifier()
        )
        app = FastAPI()
        app.include_router(build_v2_router(runtime, _no_key))
        client = TestClient(app)
        headers = {"Authorization": f"Bearer {stack.token('requester')}", "Idempotency-Key": "pilot-pg-000001"}
        reply = client.post(
            f"{URL}/analyze", json={"request_text": "Show monthly revenue", "purpose": "analytics"}, headers=headers
        )
        assert reply.status_code == 200, reply.text
        body = reply.json()
        assert body["outcome"]["outcome"] == "answer", json.dumps(body)[:400]
        assert [r[1] for r in body["outcome"]["result"]["rows"]] == ["1969", "1468", "563"]
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{control_db}" WITH (FORCE)'))
            connection.execute(text(f'DROP DATABASE "{warehouse_db}" WITH (FORCE)'))
