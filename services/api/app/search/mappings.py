from __future__ import annotations

from typing import Any

SUPPORT_SEARCH_MAPPING_VERSION = "support-search-mapping-v1"
SUPPORT_SEARCH_TEXT_ANALYZER = "support_text_v1"


def build_support_index_definition(vector_dimensions: int) -> dict[str, Any]:
    """Build a deterministic OpenSearch index definition for support documents."""
    if vector_dimensions < 1 or vector_dimensions > 10000:
        raise ValueError("vector_dimensions must be between 1 and 10000")

    return {
        "settings": {
            "index": {
                "knn": True,
                "number_of_shards": 1,
                "number_of_replicas": 0,
            },
            "analysis": {
                "analyzer": {
                    SUPPORT_SEARCH_TEXT_ANALYZER: {
                        "type": "custom",
                        "tokenizer": "standard",
                        "filter": ["lowercase"],
                    }
                }
            },
        },
        "mappings": {
            "dynamic": False,
            "properties": {
                "schema_version": {"type": "keyword"},
                "document_id": {"type": "keyword"},
                "tenant_id": {"type": "keyword"},
                "acl_tokens": {"type": "keyword"},
                "source_type": {"type": "keyword"},
                "source_id": {"type": "keyword"},
                "provider": {"type": "keyword"},
                "title": {
                    "type": "text",
                    "analyzer": SUPPORT_SEARCH_TEXT_ANALYZER,
                    "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
                },
                "text": {"type": "text", "analyzer": SUPPORT_SEARCH_TEXT_ANALYZER},
                "status": {"type": "keyword"},
                "priority": {"type": "keyword"},
                "category": {"type": "keyword"},
                "channel": {"type": "keyword"},
                "locale": {"type": "keyword"},
                "tags": {"type": "keyword"},
                "source_uri": {"type": "keyword", "index": False},
                "created_at": {"type": "date"},
                "updated_at": {"type": "date"},
                "content_hash": {"type": "keyword"},
                "content_version": {"type": "keyword"},
                "permission_version": {"type": "keyword"},
                "embedding_model_version": {"type": "keyword"},
                "embedding": {
                    "type": "knn_vector",
                    "dimension": vector_dimensions,
                    "method": {
                        "name": "hnsw",
                        "engine": "lucene",
                        "space_type": "cosinesimil",
                        "parameters": {"ef_construction": 128, "m": 16},
                    },
                },
                "freshness_score": {"type": "float"},
                "quality_score": {"type": "float"},
                "resolution_confidence": {"type": "float"},
                "popularity_score": {"type": "float"},
                "engagement_score": {"type": "float"},
                "metadata": {"type": "object", "enabled": False},
            },
        },
    }
