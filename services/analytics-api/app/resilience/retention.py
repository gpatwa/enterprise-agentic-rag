"""Retention for the durable run material (M7 fix D13; persona reviews: data owner and SRE).

- Policy values (small filter literals and identity claims) are deleted as soon as their run is terminal: they are only needed
  to compile and resume a run.
- Compiled plans and result links are kept for `plan_retention_days` after they were written (default 30), so a review or an
  investigation can still see what ran, then deleted.
- A run that is paused (for review or clarification) keeps everything until it ends.

Run it on a schedule (for example an hourly job). It deletes only these three working tables; runs, transitions, evidence, and
feedback are append-only and are not touched. Retention for backups is a separate decision.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.engine import Engine

DEFAULT_PLAN_RETENTION_DAYS = 30


def purge_run_material(
    engine: Engine, *, now: datetime | None = None, plan_retention_days: int = DEFAULT_PLAN_RETENTION_DAYS
) -> dict[str, int]:
    if plan_retention_days < 1:
        raise ValueError("plan_retention_days must be at least 1")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = (current - timedelta(days=plan_retention_days)).strftime("%Y-%m-%d %H:%M:%S")
    with engine.begin() as connection:
        values = connection.execute(
            text("""DELETE FROM analytics_run_policy_values WHERE EXISTS (
                SELECT 1 FROM analytics_agent_runs r WHERE r.run_id = analytics_run_policy_values.run_id
                AND r.tenant_id = analytics_run_policy_values.tenant_id AND r.status = 'terminal')""")
        ).rowcount
        open_runs = """NOT EXISTS (SELECT 1 FROM analytics_agent_runs r WHERE r.run_id = {table}.run_id
            AND r.tenant_id = {table}.tenant_id AND r.status <> 'terminal')"""
        links = connection.execute(
            text(
                "DELETE FROM analytics_run_result_links WHERE created_at < :cutoff AND "
                + open_runs.format(table="analytics_run_result_links")
            ),
            {"cutoff": cutoff},
        ).rowcount
        plans = connection.execute(
            text(
                "DELETE FROM analytics_run_plans WHERE created_at < :cutoff AND "
                + open_runs.format(table="analytics_run_plans")
            ),
            {"cutoff": cutoff},
        ).rowcount
    return {"policy_values": values, "result_links": links, "plans": plans}
