from __future__ import annotations

from app.search.compatibility import (
    MappingCompatibilityKind,
    classify_mapping_compatibility,
)
from app.search.mappings import build_support_index_definition


def test_identical_mappings_are_idempotent():
    mapping = build_support_index_definition(768)["mappings"]

    result = classify_mapping_compatibility(mapping, mapping.copy())

    assert result.kind is MappingCompatibilityKind.IDENTICAL
    assert result.is_compatible is True
    assert result.reasons == ()


def test_new_field_is_additive():
    existing = build_support_index_definition(768)["mappings"]
    proposed = build_support_index_definition(768)["mappings"]
    proposed["properties"]["resolution_team"] = {"type": "keyword"}

    result = classify_mapping_compatibility(existing, proposed)

    assert result.kind is MappingCompatibilityKind.ADDITIVE
    assert result.is_compatible is True
    assert result.reasons == ("field added: resolution_team",)


def test_removed_or_changed_field_is_breaking():
    existing = build_support_index_definition(768)["mappings"]
    proposed = build_support_index_definition(768)["mappings"]
    del proposed["properties"]["locale"]
    proposed["properties"]["embedding"]["dimension"] = 1536

    result = classify_mapping_compatibility(existing, proposed)

    assert result.kind is MappingCompatibilityKind.BREAKING
    assert result.is_compatible is False
    assert result.reasons == (
        "field definition changed: embedding",
        "field removed: locale",
    )


def test_additive_and_breaking_changes_are_breaking_together():
    existing = build_support_index_definition(768)["mappings"]
    proposed = build_support_index_definition(768)["mappings"]
    proposed["properties"]["new_filter"] = {"type": "keyword"}
    proposed["properties"]["title"]["type"] = "keyword"

    result = classify_mapping_compatibility(existing, proposed)

    assert result.kind is MappingCompatibilityKind.BREAKING
    assert "field added: new_filter" in result.reasons
    assert "field definition changed: title" in result.reasons
