"""Lifecycle and fail-closed resolution tests for the local semantic registry."""
import json
from copy import deepcopy
from pathlib import Path

import pytest

from app.config import Settings
from app.semantic_registry import SemanticContractNotFoundError, SemanticRegistry

SERVICE_ROOT = Path(__file__).parent.parent
SAMPLE_DOCUMENT = SERVICE_ROOT / "semantic_registry" / "contracts" / "olist-commerce-v1.json"


def sample_document() -> dict:
    return json.loads(SAMPLE_DOCUMENT.read_text())


def write_document(root: Path, filename: str, document: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / filename).write_text(json.dumps(document))


def test_default_registry_contains_a_resolvable_certified_contract():
    registry = SemanticRegistry(Settings(_env_file=None).semantic_registry_path)

    document = registry.get_certified("olist-commerce", "2026-08-20")

    assert document.lifecycle == "certified"
    assert document.contract.metrics[0].id == "delivered_revenue"


def test_registry_reports_all_lifecycle_states_and_invalid_documents(tmp_path):
    certified = sample_document()
    draft = deepcopy(certified)
    draft["lifecycle"] = "draft"
    draft["contract"]["id"] = "draft-commerce"
    deprecated = deepcopy(certified)
    deprecated["lifecycle"] = "deprecated"
    deprecated["contract"]["id"] = "legacy-commerce"
    invalid = deepcopy(certified)
    invalid["contract"]["id"] = "broken-commerce"
    invalid["contract"]["metrics"][0]["measure_field_id"] = "unknown.field"

    write_document(tmp_path, "certified.json", certified)
    write_document(tmp_path, "draft.json", draft)
    write_document(tmp_path, "deprecated.json", deprecated)
    write_document(tmp_path, "invalid.json", invalid)

    entries = SemanticRegistry(tmp_path).list_entries()

    assert {entry.state for entry in entries} == {"draft", "certified", "deprecated", "invalid"}
    invalid_entry = next(entry for entry in entries if entry.state == "invalid")
    assert invalid_entry.contract_id == "broken-commerce"
    assert invalid_entry.error == "invalid semantic contract document"


def test_registry_returns_exact_versions_and_fails_closed_for_non_certified_contracts(tmp_path):
    draft = sample_document()
    draft["lifecycle"] = "draft"
    draft["contract"]["id"] = "draft-commerce"
    write_document(tmp_path, "draft.json", draft)
    registry = SemanticRegistry(tmp_path)

    assert registry.get("draft-commerce", "2026-08-20").lifecycle == "draft"
    with pytest.raises(SemanticContractNotFoundError, match="not certified"):
        registry.get_certified("draft-commerce", "2026-08-20")
    with pytest.raises(SemanticContractNotFoundError, match="was not found"):
        registry.get("draft-commerce", "missing-version")


def test_registry_rejects_ambiguous_contract_versions(tmp_path):
    document = sample_document()
    write_document(tmp_path, "first.json", document)
    write_document(tmp_path, "second.json", document)

    with pytest.raises(SemanticContractNotFoundError, match="is ambiguous"):
        SemanticRegistry(tmp_path).get("olist-commerce", "2026-08-20")
