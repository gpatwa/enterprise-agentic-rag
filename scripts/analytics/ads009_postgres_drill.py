"""Run the ADS-009 control-store drill against a disposable PostgreSQL database."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import psycopg2
from psycopg2 import errors


def main() -> None:
    database_url = os.environ.get("ADS009_DATABASE_URL")
    if not database_url:
        raise SystemExit("ADS009_DATABASE_URL is required")

    prefix = f"ads009-{uuid.uuid4().hex[:12]}"
    run_id = f"{prefix}-run"
    connection = psycopg2.connect(database_url)
    connection.autocommit = False
    cursor = connection.cursor()
    now = datetime.now(timezone.utc)
    purpose = "m0-drill"
    try:
        cursor.execute(
            """INSERT INTO analytics_agent_runs
            (run_id, tenant_id, purpose, graph_version, state_version, current_node, state_payload)
            VALUES (%s, 'tenant-live', %s, 'fake-v1', 'v1', 'create', '{"node":"create"}'::jsonb)""",
            (run_id, purpose),
        )
        cursor.execute(
            """INSERT INTO analytics_run_leases
            (run_id, tenant_id, purpose, owner_id, lease_token, fencing_seq, expires_at)
            VALUES (%s, 'tenant-live', %s, 'worker-a', %s, 1, %s)""",
            (run_id, purpose, f"{prefix}-lease-a", now - timedelta(seconds=1)),
        )
        cursor.execute(
            """INSERT INTO analytics_run_checkpoints
            (run_id, checkpoint_seq, tenant_id, purpose, graph_version, state_version, current_node,
             transition_seq, lease_fencing_seq, state_payload)
            VALUES (%s, 1, 'tenant-live', %s, 'fake-v1', 'v1', 'bootstrap', 1, 1,
                    '{"step":"bootstrap"}'::jsonb)""",
            (run_id, purpose),
        )
        cursor.execute(
            """INSERT INTO analytics_run_transitions
            (run_id, transition_seq, tenant_id, purpose, graph_version, from_node, to_node, from_status, to_status,
             fencing_seq, idempotency_key, evidence_payload)
            VALUES (%s, 1, 'tenant-live', %s, 'fake-v1', 'create', 'bootstrap', 'active', 'active', 1, %s, '{}'::jsonb)""",
            (run_id, purpose, f"{prefix}-transition-1"),
        )
        connection.commit()

        cursor.execute(
            """UPDATE analytics_run_leases
            SET owner_id='worker-b', lease_token=%s, fencing_seq=2, expires_at=%s, renewed_at=CURRENT_TIMESTAMP
            WHERE run_id=%s AND tenant_id='tenant-live' AND purpose=%s AND fencing_seq=1 AND expires_at <= %s""",
            (f"{prefix}-lease-b", now + timedelta(minutes=5), run_id, purpose, now),
        )
        assert cursor.rowcount == 1
        cursor.execute(
            """UPDATE analytics_agent_runs SET lease_fencing_seq=2
            WHERE run_id=%s AND lease_fencing_seq < 2""",
            (run_id,),
        )
        assert cursor.rowcount == 1
        connection.commit()

        cursor.execute(
            """UPDATE analytics_agent_runs SET current_node='retrieve', transition_seq=2
            WHERE run_id=%s AND tenant_id='tenant-live' AND purpose=%s AND current_node='bootstrap'
              AND transition_seq=1 AND lease_fencing_seq=1""",
            (run_id, purpose),
        )
        assert cursor.rowcount == 0, "stale worker unexpectedly committed"
        connection.rollback()

        cursor.execute(
            """UPDATE analytics_agent_runs SET current_node='retrieve', transition_seq=2,
            state_payload='{"node":"retrieve"}'::jsonb
            WHERE run_id=%s AND tenant_id='tenant-live' AND purpose=%s AND current_node='bootstrap'
              AND transition_seq=1 AND lease_fencing_seq=2""",
            (run_id, purpose),
        )
        assert cursor.rowcount == 1
        cursor.execute(
            """INSERT INTO analytics_run_transitions
            (run_id, transition_seq, tenant_id, purpose, graph_version, from_node, to_node, from_status, to_status,
             fencing_seq, idempotency_key, evidence_payload)
            VALUES (%s, 2, 'tenant-live', %s, 'fake-v1', 'bootstrap', 'retrieve', 'active', 'active', 2, %s, '{}'::jsonb)""",
            (run_id, purpose, f"{prefix}-transition-2"),
        )
        cursor.execute(
            """INSERT INTO analytics_run_checkpoints
            (run_id, checkpoint_seq, tenant_id, purpose, graph_version, state_version, current_node,
             transition_seq, lease_fencing_seq, state_payload)
            VALUES (%s, 2, 'tenant-live', %s, 'fake-v1', 'v1', 'retrieve', 2, 2,
                    '{"node":"retrieve"}'::jsonb)""",
            (run_id, purpose),
        )
        connection.commit()

        try:
            cursor.execute(
                "UPDATE analytics_run_checkpoints SET current_node='tampered' WHERE run_id=%s AND checkpoint_seq=2",
                (run_id,),
            )
            connection.commit()
            raise AssertionError("checkpoint append-only trigger did not reject mutation")
        except errors.RaiseException:
            connection.rollback()

        cursor.execute(
            """UPDATE analytics_agent_runs SET status='terminal', state_payload=%s::jsonb
            WHERE run_id=%s AND tenant_id='tenant-live' AND purpose=%s AND current_node='retrieve'
              AND transition_seq=2 AND lease_fencing_seq=2""",
            ('{"node":"retrieve","terminal_outcome":{"kind":"succeeded","summary_reference":"summary-1"}}', run_id, purpose),
        )
        assert cursor.rowcount == 1
        cursor.execute(
            """INSERT INTO analytics_run_transitions
            (run_id, transition_seq, tenant_id, purpose, graph_version, from_node, to_node, from_status, to_status,
             fencing_seq, idempotency_key, evidence_payload)
            VALUES (%s, 3, 'tenant-live', %s, 'fake-v1', 'retrieve', NULL, 'active', 'terminal', 2, %s, '{}'::jsonb)""",
            (run_id, purpose, f"{prefix}-transition-3"),
        )
        cursor.execute(
            """INSERT INTO analytics_run_checkpoints
            (run_id, checkpoint_seq, tenant_id, purpose, graph_version, state_version, current_node,
             transition_seq, lease_fencing_seq, state_payload)
            VALUES (%s, 3, 'tenant-live', %s, 'fake-v1', 'v1', 'retrieve', 3, 2, %s::jsonb)""",
            (run_id, purpose, '{"node":"retrieve","terminal":true}'),
        )
        connection.commit()

        cursor.execute(
            "SELECT transition_seq FROM analytics_run_transitions WHERE run_id=%s AND tenant_id='tenant-live' AND purpose=%s ORDER BY transition_seq",
            (run_id, purpose),
        )
        assert [row[0] for row in cursor.fetchall()] == [1, 2, 3]

        try:
            cursor.execute(
                "INSERT INTO analytics_run_checkpoints (run_id, checkpoint_seq, tenant_id, purpose, graph_version, state_version, current_node, transition_seq, lease_fencing_seq, state_payload) VALUES (%s, 4, 'other-tenant', %s, 'fake-v1', 'v1', 'x', 4, 2, '{}'::jsonb)",
                (run_id, purpose),
            )
            connection.commit()
            raise AssertionError("cross-tenant child row was accepted")
        except errors.ForeignKeyViolation:
            connection.rollback()

        try:
            cursor.execute(
                "UPDATE analytics_run_transitions SET to_node='tampered' WHERE run_id=%s AND transition_seq=1",
                (run_id,),
            )
            connection.commit()
            raise AssertionError("append-only trigger did not reject mutation")
        except errors.RaiseException:
            connection.rollback()

        dedupe_key = f"{prefix}-outbox-once"
        cursor.execute(
            """INSERT INTO analytics_run_outbox
            (tenant_id, run_id, purpose, event_type, dedupe_key, payload)
            VALUES ('tenant-live', %s, %s, 'checkpoint', %s, '{}'::jsonb)""",
            (run_id, purpose, dedupe_key),
        )
        connection.commit()
        try:
            cursor.execute(
                """INSERT INTO analytics_run_outbox
                (tenant_id, run_id, purpose, event_type, dedupe_key, payload)
                VALUES ('tenant-live', %s, %s, 'checkpoint', %s, '{}'::jsonb)""",
                (run_id, purpose, dedupe_key),
            )
            connection.commit()
            raise AssertionError("outbox dedupe did not reject duplicate")
        except errors.UniqueViolation:
            connection.rollback()

        first = psycopg2.connect(database_url)
        second = psycopg2.connect(database_url)
        try:
            first_cursor = first.cursor()
            second_cursor = second.cursor()
            first_cursor.execute(
                """SELECT id FROM analytics_run_outbox
                WHERE dedupe_key=%s AND delivery_status='queued'
                FOR UPDATE SKIP LOCKED LIMIT 1""",
                (dedupe_key,),
            )
            assert first_cursor.fetchone() is not None
            second_cursor.execute(
                """SELECT id FROM analytics_run_outbox
                WHERE dedupe_key=%s AND delivery_status='queued'
                FOR UPDATE SKIP LOCKED LIMIT 1""",
                (dedupe_key,),
            )
            assert second_cursor.fetchone() is None, "second claimant did not skip locked row"
            second.rollback()
            first.commit()
        finally:
            first.close()
            second.close()
    finally:
        connection.close()

    print("ADS-009 live PostgreSQL drill: PASS")
    print("fencing_cas=pass")
    print("append_only_transition=pass")
    print("outbox_dedupe=pass")
    print("skip_locked_contention=pass")
    print(f"run_id={run_id}")


if __name__ == "__main__":
    main()
