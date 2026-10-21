"""PostgreSQL-only behaviour of the control store (M7 fixes D1 and D3).

Skipped unless ANALYTICS_TEST_POSTGRES_URL points at a disposable PostgreSQL server (a superuser URL; each test creates and drops
its own database). SQLite hides both defects: it returns timestamps as ISO text and has no sequences.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from alembic.config import Config
from reference_stack.stack import SERVICE_ROOT, _upgrade, build_stack
from sqlalchemy import create_engine, text

from app.resilience import backup_control_store, restore_control_store
from app.runtime.control_store import ControlStore, LeaseUnavailable
from app.runtime.evidence_store import EvidenceStore

ADMIN_URL = os.environ.get("ANALYTICS_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(
    not ADMIN_URL, reason="needs ANALYTICS_TEST_POSTGRES_URL (a disposable PostgreSQL server)"
)
PURPOSE = "analytics"


@pytest.fixture
def pg_url():
    name = f"m7_{uuid.uuid4().hex[:10]}"
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    url = ADMIN_URL.rsplit("/", 1)[0] + f"/{name}"
    config = Config(str(SERVICE_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", url)
    _upgrade(config, url)
    yield url
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
    admin.dispose()


def _paused_run(tmp_path, url):
    stack = build_stack("duckdb", tmp_path, review_threshold=1e-9)
    engine = create_engine(url)
    stack.control, stack.evidence = ControlStore(engine), EvidenceStore(engine)
    who = stack.verifier().verify(stack.token("requester"))
    run = stack.service().analyze(
        who, purpose=PURPOSE, idempotency_key="pg-key-000000001", request_text="Show monthly revenue"
    )
    return stack, who, run


def test_a_live_lease_is_not_mistaken_for_an_expired_one(tmp_path, pg_url):
    stack, who, run = _paused_run(tmp_path, pg_url)
    store = ControlStore(create_engine(pg_url), lease_seconds=30)
    t0 = datetime.now(timezone.utc)
    lease = store.acquire_lease(
        run_id=run.run_id, tenant_id=who.tenant_id, purpose=PURPOSE, owner_id="a", lease_token="t-a", now=t0
    )
    with pytest.raises(
        LeaseUnavailable
    ):  # before the fix, PostgreSQL's datetime vs ISO text made this lease look expired
        store.acquire_lease(
            run_id=run.run_id,
            tenant_id=who.tenant_id,
            purpose=PURPOSE,
            owner_id="b",
            lease_token="t-b",
            now=t0 + timedelta(seconds=10),
        )
    renewed = store.renew_lease(lease, now=t0 + timedelta(seconds=25))
    with pytest.raises(LeaseUnavailable):  # the heartbeat extended it
        store.acquire_lease(
            run_id=run.run_id,
            tenant_id=who.tenant_id,
            purpose=PURPOSE,
            owner_id="b",
            lease_token="t-b",
            now=t0 + timedelta(seconds=40),
        )
    taken = store.acquire_lease(
        run_id=run.run_id,
        tenant_id=who.tenant_id,
        purpose=PURPOSE,
        owner_id="b",
        lease_token="t-b",
        now=renewed.expires_at + timedelta(seconds=1),
    )
    assert taken.fencing_seq > lease.fencing_seq


def test_a_restored_postgres_database_accepts_new_transitions(tmp_path, pg_url, request):
    stack, who, run = _paused_run(tmp_path / "a", pg_url)
    backup_control_store(stack.control.engine, tmp_path / "backup")
    # a second, empty, migrated database to restore into
    name = f"m7_r_{uuid.uuid4().hex[:8]}"
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    request.addfinalizer(lambda: admin.connect().execute(text(f'DROP DATABASE "{name}" WITH (FORCE)')))
    target = ADMIN_URL.rsplit("/", 1)[0] + f"/{name}"
    config = Config(str(SERVICE_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", target)
    _upgrade(config, target)
    restore_control_store(tmp_path / "backup", create_engine(target))
    revived = build_stack("duckdb", tmp_path / "b", review_threshold=1e-9)
    engine = create_engine(target)
    revived.control, revived.evidence = ControlStore(engine), EvidenceStore(engine)
    # before the fix the outbox sequence restarted at 1 and every new transition failed with a duplicate key
    fresh = revived.service().analyze(
        who, purpose=PURPOSE, idempotency_key="pg-key-000000002", request_text="Show monthly revenue"
    )
    assert fresh.state == "waiting_review"
    review = revived.control.get_review(run.outcome.review_id, tenant_id=who.tenant_id, purpose=PURPOSE)
    reviewer = revived.verifier().verify(revived.token("reviewer"))
    done = revived.service().decide_review(
        reviewer,
        purpose=PURPOSE,
        run_id=run.run_id,
        decision="approved",
        plan_fingerprint=review.plan_fingerprint,
        note=None,
    )
    assert done.state == "terminal"
