import json

import pytest

from app.search.mapping import (
    CatalogMappingVersions,
    compatibility_errors,
    generate_catalog_mapping,
    is_compatible_mapping,
)


def test_mapping_contains_versioned_required_fields_and_types() -> None:
    mapping = generate_catalog_mapping()
    properties = mapping["mappings"]["properties"]

    assert mapping["mappings"]["dynamic"] == "strict"
    assert mapping["_meta"]["embedding_dimensions"] == 384
    assert properties["experience_id"]["type"] == "keyword"
    assert properties["title"]["type"] == "text"
    assert properties["title"]["fields"]["keyword"]["type"] == "keyword"
    assert properties["embedding"]["type"] == "knn_vector"
    assert properties["embedding"]["dimension"] == 384
    assert properties["embedding"]["method"]["space_type"] == "cosine"
    assert "imd-catalog-read" in mapping["aliases"]


def test_mapping_serialization_is_stable() -> None:
    versions = CatalogMappingVersions(generation="7")
    first = json.dumps(generate_catalog_mapping(versions), sort_keys=True, separators=(",", ":"))
    second = json.dumps(generate_catalog_mapping(versions), sort_keys=True, separators=(",", ":"))

    assert first == second
    assert versions.index_name.endswith("-7")


def test_unchanged_contract_is_compatible_across_generations() -> None:
    previous = generate_catalog_mapping(CatalogMappingVersions(generation="1"))
    current = generate_catalog_mapping(CatalogMappingVersions(generation="2"))

    assert is_compatible_mapping(previous, current)
    assert compatibility_errors(previous, current) == ()


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("_meta", "embedding_dimensions"), 768, "metadata.embedding_dimensions changed"),
        (("_meta", "embedding_similarity"), "dot_product", "metadata.embedding_similarity changed"),
        (("_meta", "analyzer_version"), "imd-analyzer-v2", "metadata.analyzer_version changed"),
        (
            ("mappings", "properties", "title", "type"),
            "keyword",
            "field title type changed from text to keyword",
        ),
        (("mappings", "properties", "embedding", "method", "space_type"), "l2", "embedding similarity changed"),
    ],
)
def test_incompatible_contract_changes_are_rejected(path, value, message) -> None:
    previous = generate_catalog_mapping()
    current = generate_catalog_mapping()
    target = current
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    errors = compatibility_errors(previous, current)
    assert message in errors
    assert not is_compatible_mapping(previous, current)


def test_missing_required_field_is_rejected() -> None:
    previous = generate_catalog_mapping()
    current = generate_catalog_mapping()
    del current["mappings"]["properties"]["safety_state"]

    errors = compatibility_errors(previous, current)
    assert "required field safety_state is missing" in errors
    assert not is_compatible_mapping(previous, current)
