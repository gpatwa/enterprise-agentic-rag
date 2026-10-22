"""A URL-encoded password ("%21") in the control DB URL must not break startup migrations (alembic uses configparser)."""

import sqlite3

from app.runtime.pilot_wiring import migrate


def test_migrate_accepts_percent_in_database_url(tmp_path):
    path = tmp_path / "control%21.db"
    migrate(f"sqlite:///{path}")
    with sqlite3.connect(path) as conn:
        tables = {row[0] for row in conn.execute("select name from sqlite_master where type='table'")}
    assert "alembic_version" in tables
