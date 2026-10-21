"""`python -m app.jobs.purge`: delete expired run working material (scheduled as a Container Apps job).

Reads ANALYTICS_CONTROL_DB_URL; prints the counts it deleted as one JSON line; exits non-zero on failure so the job shows as failed.
"""

from __future__ import annotations

import json
import sys

from sqlalchemy import create_engine

from app.config import settings
from app.resilience.retention import DEFAULT_PLAN_RETENTION_DAYS, purge_run_material


def main(argv: list[str] | None = None) -> int:
    if not settings.ANALYTICS_CONTROL_DB_URL:
        print(json.dumps({"error": "ANALYTICS_CONTROL_DB_URL is not set"}))
        return 2
    days = int((argv or sys.argv[1:] or [DEFAULT_PLAN_RETENTION_DAYS])[0])
    engine = create_engine(settings.ANALYTICS_CONTROL_DB_URL, pool_pre_ping=True)
    try:
        print(json.dumps({"deleted": purge_run_material(engine, plan_retention_days=days)}))
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
