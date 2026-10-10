"""EA-050 to EA-058 runtime boundary tests."""
import pytest

from app.runtime import BudgetExceeded, BudgetGuard
from packages.platform_contracts.runtime import QueryBudget


def test_budget_guard_rejects_rows_and_cost_overages():
    guard = BudgetGuard(QueryBudget(max_rows=10, max_cost_units=2))
    with pytest.raises(BudgetExceeded, match="row"):
        guard.check_rows(11)
    with pytest.raises(BudgetExceeded, match="cost"):
        guard.check_cost(2.1)


def test_budget_contract_has_bounded_defaults():
    budget = QueryBudget()
    assert budget.timeout_seconds == 30
    assert budget.max_concurrency == 4
