"""A size-bounded mapping for the process-local run handoff stores (M7 fix D5).

Result rows, explanations, validation reports, and compiled plans are handed between nodes in memory. Without a bound a long-running
process kept every run's rows for ever. The oldest entries are dropped first; a run whose entry was dropped falls back to its durable
material (plans) or reports the answer as unavailable (rows), which is the same as after a restart.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")
DEFAULT_MAX_ENTRIES = 2_000


class BoundedDict(OrderedDict, Generic[K, V]):
    def __init__(self, max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        super().__init__()
        self.max_entries = max_entries

    def __setitem__(self, key: K, value: V) -> None:
        if key in self:
            self.move_to_end(key)
        super().__setitem__(key, value)
        while len(self) > self.max_entries:
            self.popitem(last=False)
