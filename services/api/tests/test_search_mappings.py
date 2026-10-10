from __future__ import annotations

import json

import pytest


def test_support_mapping_is_deterministic_and_versioned():
    from app.search.mappings import (
        SUPPORT_SEARCH_MAPPING_VERSION,
        SUPPORT_SEARCH_TEXT_ANALYZER,
        build_support_index_definition,
    )

    first = build_support_index_definition(1536)
    second = build_support_index_definition(1536)

    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert SUPPORT_SEARCH_MAPPING_VERSION == "support-search-mapping-v1"
    assert first["settings"]["index"]["knn"] is True
    assert first["mappings"]["dynamic"] is False
    assert first["settings"]["analysis"]["analyzer"][SUPPORT_SEARCH_TEXT_ANALYZER]["tokenizer"] == "standard"


def test_support_mapping_has_security_search_and_ranking_fields():
    from app.search.mappings import build_support_index_definition

    properties = build_support_index_definition(768)["mappings"]["properties"]
    assert properties["tenant_id"] == {"type": "keyword"}
    assert properties["acl_tokens"] == {"type": "keyword"}
    assert properties["title"]["type"] == "text"
    assert properties["text"]["type"] == "text"
    assert properties["embedding"]["type"] == "knn_vector"
    assert properties["embedding"]["dimension"] == 768
    assert properties["embedding"]["method"]["name"] == "hnsw"
    assert properties["freshness_score"]["type"] == "float"
    assert properties["quality_score"]["type"] == "float"
    assert properties["metadata"] == {"type": "object", "enabled": False}


@pytest.mark.parametrize("dimensions", [0, -1, 10001])
def test_support_mapping_rejects_invalid_vector_dimensions(dimensions):
    from app.search.mappings import build_support_index_definition

    with pytest.raises(ValueError, match="between 1 and 10000"):
        build_support_index_definition(dimensions)
