"""EA-014 certified compiler adapter and golden intent checks."""
import json
from pathlib import Path

from app.compiler import CertifiedIntentCompiler, PostgreSQLCompilerAdapter
from packages.platform_contracts.analytics_intent import AnalyticalIntent

SERVICE_ROOT = Path(__file__).parent.parent


def test_certified_compiler_loads_registry_contract_and_compiles_golden_intent():
    intent_payload = json.loads(
        (SERVICE_ROOT / "tests" / "fixtures" / "semantic" / "sales-monthly-intent.json").read_text()
    )
    compiler = CertifiedIntentCompiler(SERVICE_ROOT / "semantic_registry")

    compiled = compiler.compile(AnalyticalIntent.model_validate(intent_payload))

    assert "DATE_TRUNC('month'" in compiled.sql
    assert 'FROM "sales_orders" AS d0' in compiled.sql
    assert compiled.parameters["p0"] == "paid"


def test_production_selection_point_exposes_postgres_dialect():
    assert PostgreSQLCompilerAdapter.dialect == "postgres"
