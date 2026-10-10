"""Read-only view of a dbt project limited to approved schema files (ADS-053).

Nothing here writes, shells out, or runs dbt. `render_edit` returns text for a diff and for tests; the
proposal carries the structured edit, which is the source of truth for a reviewer.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_APPROVED = ("models/**/schema.yml",)


class DbtProjectError(ValueError):
    pass


@dataclass(frozen=True)
class ModelLocation:
    file_path: str  # relative to the project root
    text: str
    document: dict[str, Any]


class DbtProject:
    def __init__(self, root: Path | str, approved_patterns: tuple[str, ...] = DEFAULT_APPROVED) -> None:
        self.root = Path(root).resolve()
        self.approved_patterns = tuple(approved_patterns)
        if not self.root.is_dir():
            raise DbtProjectError("dbt project root does not exist")

    def approved_files(self) -> list[str]:
        found: set[str] = set()
        for pattern in self.approved_patterns:
            for path in self.root.glob(pattern):
                resolved = path.resolve()
                if resolved.is_file() and self.root in resolved.parents:  # no symlink escapes
                    found.add(resolved.relative_to(self.root).as_posix())
        return sorted(found)

    def locate_model(self, model: str) -> ModelLocation | None:
        for relative in self.approved_files():
            text = (self.root / relative).read_text()
            document = yaml.safe_load(text) or {}
            if any(isinstance(m, dict) and m.get("name") == model for m in document.get("models", [])):
                return ModelLocation(relative, text, document)
        return None


def canonical(text: str) -> str:
    """The form `render_edit` diffs against (PyYAML round trip; comments and flow style are not kept)."""
    return yaml.safe_dump(yaml.safe_load(text) or {}, sort_keys=False)


def find_column(document: dict[str, Any], model: str, column: str) -> dict[str, Any] | None:
    for item in document.get("models", []):
        if isinstance(item, dict) and item.get("name") == model:
            for col in item.get("columns", []) or []:
                if isinstance(col, dict) and col.get("name") == column:
                    return col
    return None


def tests_key(column: dict[str, Any]) -> str:
    return "tests" if "tests" in column else "data_tests"


def has_test(column: dict[str, Any], test_name: str) -> bool:
    for entry in column.get(tests_key(column), []) or []:
        if entry == test_name or (isinstance(entry, dict) and test_name in entry):
            return True
    return False


def render_edit(text: str, model: str, column: str, *, description: str | None, test_name: str | None) -> str:
    """The schema text after the edit. Raises if the model or column is absent."""
    document = yaml.safe_load(text) or {}
    target = find_column(document, model, column)
    if target is None:
        raise DbtProjectError("model or column not found in the schema file")
    if description is not None:
        target["description"] = description
    if test_name is not None:
        target.setdefault(tests_key(target), []).append(test_name)
    return yaml.safe_dump(document, sort_keys=False)


def unified_diff(path: str, before: str, after: str) -> str:
    return "\n".join(
        difflib.unified_diff(before.splitlines(), after.splitlines(), f"a/{path}", f"b/{path}", lineterm="")
    )
