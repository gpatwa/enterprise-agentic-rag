"""Deterministic query budget enforcement before execution."""
from __future__ import annotations

from packages.platform_contracts.runtime import QueryBudget


class BudgetExceeded(ValueError):
    pass


class BudgetGuard:
    def __init__(self, budget: QueryBudget):
        self.budget = budget

    def check_rows(self, rows: int) -> None:
        if rows > self.budget.max_rows:
            raise BudgetExceeded("row budget exceeded")

    def check_cost(self, cost_units: float) -> None:
        if cost_units > self.budget.max_cost_units:
            raise BudgetExceeded("cost budget exceeded")
