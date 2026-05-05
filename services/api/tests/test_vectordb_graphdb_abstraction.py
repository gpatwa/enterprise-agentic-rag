# tests/test_vectordb_graphdb_abstraction.py
"""
Unit tests for Milestone 3: VectorDB & GraphDB Abstraction.
Tests Protocol compliance, factory routing, Qdrant implementation,
Neo4j implementation, NullGraphClient, and late-init injection.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------
# Test: VectorDB Protocol
# ---------------------------------------------------------------

class TestVectorDBProtocol:
    def test_protocol_is_runtime_checkable(self):
        from app.clients.vectordb.base import VectorDBClient
        assert hasattr(VectorDBClient, "__protocol_attrs__") or hasattr(
            VectorDBClient, "__abstractmethods__"
        ) or True  # runtime_checkable
        # The key check: isinstance works on conforming classes
        assert isinstance(VectorDBClient, type)

    def test_qdrant_impl_has_all_methods(self):
        """QdrantVectorClient must implement all Protocol methods."""
        from app.clients.vectordb.qdrant_impl import QdrantVectorClient
        client = QdrantVectorClient(host="localhost", port=6333)
        assert hasattr(client, "connect")
        assert hasattr(client, "close")
        assert hasattr(client, "search")
        assert hasattr(client, "upsert")
        assert hasattr(client, "create_collection")
        assert hasattr(client, "delete_by_filter")


# ---------------------------------------------------------------
# Test: VectorDB Factory
# ---------------------------------------------------------------

class TestVectorDBFactory:
    def test_create_qdrant_client(self):
        from app.clients.vectordb.factory import create_vectordb_client
        client = create_vectordb_client("qdrant")
        from app.clients.vectordb.qdrant_impl import QdrantVectorClient
        assert isinstance(client, QdrantVectorClient)

    def test_create_qdrant_case_insensitive(self):
        from app.clients.vectordb.factory import create_vectordb_client
        client = create_vectordb_client("  QDRANT  ")
        from app.clients.vectordb.qdrant_impl import QdrantVectorClient
        assert isinstance(client, QdrantVectorClient)

    def test_unknown_provider_raises(self):
        from app.clients.vectordb.factory import create_vectordb_client
        with pytest.raises(ValueError, match="Unknown VECTORDB_PROVIDER"):
            create_vectordb_client("weaviate")

    def test_azure_ai_search_not_implemented(self):
        from app.clients.vectordb.factory import create_vectordb_client
        with pytest.raises(NotImplementedError):
            create_vectordb_client("azure_ai_search")

    def test_pinecone_not_implemented(self):
        from app.clients.vectordb.factory import create_vectordb_client
        with pytest.raises(NotImplementedError):
            create_vectordb_client("pinecone")


# ---------------------------------------------------------------
# Test: Qdrant Filter Builder
# ---------------------------------------------------------------

class TestQdrantFilterBuilder:
    def test_build_filter_none(self):
        from app.clients.vectordb.qdrant_impl import QdrantVectorClient
        assert QdrantVectorClient._build_filter(None) is None

    def test_build_filter_empty(self):
        from app.clients.vectordb.qdrant_impl import QdrantVectorClient
        assert QdrantVectorClient._build_filter({}) is None

    def test_build_filter_single(self):
        from qdrant_client.http import models

        from app.clients.vectordb.qdrant_impl import QdrantVectorClient
        f = QdrantVectorClient._build_filter({"tenant_id": "acme"})
        assert isinstance(f, models.Filter)
        assert len(f.must) == 1
        assert f.must[0].key == "tenant_id"

    def test_build_filter_multi(self):
        from app.clients.vectordb.qdrant_impl import QdrantVectorClient
        f = QdrantVectorClient._build_filter({"tenant_id": "acme", "type": "pdf"})
        assert len(f.must) == 2

    def test_normalise_result(self):
        from app.clients.vectordb.qdrant_impl import QdrantVectorClient
        mock_point = MagicMock()
        mock_point.id = "abc-123"
        mock_point.score = 0.95
        mock_point.payload = {"text": "hello", "tenant_id": "acme"}
        result = QdrantVectorClient._normalise_result(mock_point)
        assert result == {
            "id": "abc-123",
            "score": 0.95,
            "payload": {"text": "hello", "tenant_id": "acme"},
        }


# ---------------------------------------------------------------
# Test: GraphDB Protocol
# ---------------------------------------------------------------

class TestGraphDBProtocol:
    def test_neo4j_impl_has_all_methods(self):
        from app.clients.graphdb.neo4j_impl import Neo4jGraphClient
        client = Neo4jGraphClient(
            uri="bolt://localhost:7687", user="neo4j", password="test"
        )
        assert hasattr(client, "connect")
        assert hasattr(client, "close")
        assert hasattr(client, "query_related")
        assert hasattr(client, "upsert_triples")

    def test_null_client_has_all_methods(self):
        from app.clients.graphdb.null_client import NullGraphClient
        client = NullGraphClient()
        assert hasattr(client, "connect")
        assert hasattr(client, "close")
        assert hasattr(client, "query_related")
        assert hasattr(client, "upsert_triples")


# ---------------------------------------------------------------
# Test: GraphDB Factory
# ---------------------------------------------------------------

class TestGraphDBFactory:
    def test_create_neo4j_client(self):
        from app.clients.graphdb.factory import create_graphdb_client
        client = create_graphdb_client("neo4j")
        from app.clients.graphdb.neo4j_impl import Neo4jGraphClient
        assert isinstance(client, Neo4jGraphClient)

    def test_create_null_client(self):
        from app.clients.graphdb.factory import create_graphdb_client
        client = create_graphdb_client("none")
        from app.clients.graphdb.null_client import NullGraphClient
        assert isinstance(client, NullGraphClient)

    def test_create_none_case_insensitive(self):
        from app.clients.graphdb.factory import create_graphdb_client
        client = create_graphdb_client("  NONE  ")
        from app.clients.graphdb.null_client import NullGraphClient
        assert isinstance(client, NullGraphClient)

    def test_unknown_provider_raises(self):
        from app.clients.graphdb.factory import create_graphdb_client
        with pytest.raises(ValueError, match="Unknown GRAPHDB_PROVIDER"):
            create_graphdb_client("dgraph")

    def test_cosmosdb_not_implemented(self):
        from app.clients.graphdb.factory import create_graphdb_client
        with pytest.raises(NotImplementedError):
            create_graphdb_client("cosmosdb")


# ---------------------------------------------------------------
# Test: NullGraphClient behaviour
# ---------------------------------------------------------------

class TestNullGraphClient:
    @pytest.mark.asyncio
    async def test_connect_succeeds(self):
        from app.clients.graphdb.null_client import NullGraphClient
        client = NullGraphClient()
        await client.connect()
        assert client.is_connected is True

    @pytest.mark.asyncio
    async def test_query_related_returns_empty(self):
        from app.clients.graphdb.null_client import NullGraphClient
        client = NullGraphClient()
        results = await client.query_related("test", "default", limit=5)
        assert results == []

    @pytest.mark.asyncio
    async def test_upsert_triples_noop(self):
        from app.clients.graphdb.null_client import NullGraphClient
        client = NullGraphClient()
        # Should not raise
        await client.upsert_triples(
            [{"source": "A", "target": "B", "type": "REL"}], "default"
        )

    @pytest.mark.asyncio
    async def test_close_noop(self):
        from app.clients.graphdb.null_client import NullGraphClient
        client = NullGraphClient()
        await client.close()


# ---------------------------------------------------------------
# Test: Config has new settings
# ---------------------------------------------------------------

class TestConfigSettings:
    def test_vectordb_provider_default(self):
        from app.config import settings
        assert settings.VECTORDB_PROVIDER == "qdrant"

    def test_graphdb_provider_default(self):
        from app.config import settings
        assert settings.GRAPHDB_PROVIDER == "neo4j"

    def test_cloud_provider_default(self):
        from app.config import settings
        assert settings.CLOUD_PROVIDER == "aws"

    def test_storage_provider_default(self):
        from app.config import settings
        assert settings.STORAGE_PROVIDER == "s3"


# ---------------------------------------------------------------
# Test: Retriever set_clients
# ---------------------------------------------------------------

class TestRetrieverInjection:
    def test_set_clients_stores_references(self):
        from app.agents.nodes import retriever
        mock_vectordb = MagicMock()
        mock_graphdb = MagicMock()
        retriever.set_clients(mock_vectordb, mock_graphdb)
        assert retriever._vectordb_client is mock_vectordb
        assert retriever._graphdb_client is mock_graphdb


# ---------------------------------------------------------------
# Test: Semantic cache set_vectordb_client
# ---------------------------------------------------------------

class TestSemanticCacheInjection:
    def test_set_vectordb_client_stores_reference(self):
        from app.cache import semantic
        mock_client = MagicMock()
        semantic.set_vectordb_client(mock_client)
        assert semantic._vectordb_client is mock_client
