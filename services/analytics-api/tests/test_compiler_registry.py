"""EA-017 compiler adapter conformance and registration tests."""
from app.compiler import CompilerRegistry, PostgreSQLCompilerAdapter


class FakeCompiler:
    dialect = "fake"


def test_second_dialect_can_register_without_planner_changes():
    registry = CompilerRegistry([PostgreSQLCompilerAdapter(), FakeCompiler()])

    assert registry.get("postgres").dialect == "postgres"
    assert registry.get("fake").dialect == "fake"


def test_registry_rejects_duplicate_or_unknown_dialects():
    registry = CompilerRegistry([FakeCompiler()])

    try:
        registry.register(FakeCompiler())
    except ValueError as error:
        assert "already registered" in str(error)
    else:
        raise AssertionError("duplicate compiler registration should fail")

    try:
        registry.get("missing")
    except LookupError as error:
        assert "not registered" in str(error)
    else:
        raise AssertionError("unknown compiler lookup should fail")
