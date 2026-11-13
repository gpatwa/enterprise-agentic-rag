"""The migration job adopts a schema the API already created instead of failing on ``CREATE TABLE``.

Seen on the first Azure production deploy: the API's startup ``create_all`` had built all 22 tables, ``alembic_version``
did not exist, and ``alembic upgrade head`` died on ``relation "mcp_connections" already exists``.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[4]
MODELS = {"chat_history", "mcp_connections", "support_tickets"}


def test_a_versioned_database_is_upgraded() -> None:
    from alembic_runner import decide

    assert decide(True, MODELS | {"alembic_version"}, MODELS) == "upgrade"


def test_a_complete_unversioned_schema_is_stamped_not_rebuilt() -> None:
    from alembic_runner import decide

    assert decide(False, set(MODELS), MODELS) == "stamp"
    assert decide(False, MODELS | {"something_else"}, MODELS) == "stamp"


def test_an_empty_or_partial_schema_runs_the_migrations() -> None:
    from alembic_runner import decide

    assert decide(False, set(), MODELS) == "upgrade"
    assert decide(False, {"chat_history"}, MODELS) == "upgrade", "a partial schema must fail loudly, not be adopted"


def test_with_no_known_models_nothing_is_stamped() -> None:
    from alembic_runner import decide

    assert decide(False, {"a"}, set()) == "upgrade"


def test_the_runner_sees_every_table_the_migrations_create() -> None:
    """Stamping is only sound when the model tables cover what 0002-0008 would have created."""
    from alembic_runner import _model_tables

    created = set()
    for path in (REPO / "services" / "api" / "alembic" / "versions").glob("0*.py"):
        created |= set(re.findall(r'create_table\(\s*"([^"]+)"', path.read_text()))
    assert created <= _model_tables(), f"migrations create tables the models do not: {created - _model_tables()}"


def test_the_chart_runs_the_runner_and_the_image_contains_it() -> None:
    values = yaml.safe_load((REPO / "deploy" / "helm" / "api" / "values.yaml").read_text())
    assert values["migrations"]["command"] == ["python", "alembic_runner.py"]
    assert (REPO / "services" / "api" / "alembic_runner.py").is_file()
    assert "COPY . ." in (REPO / "services" / "api" / "Dockerfile").read_text()
    ignore = REPO / "services" / "api" / ".dockerignore"
    assert not ignore.exists() or "alembic_runner" not in ignore.read_text()
