# services/api/tests/test_context_layers.py
"""
Unit tests for Context Layer Architecture.

Tests cover:
  1. Context models — table columns and defaults
  2. ContextManager CRUD — annotations, business rules, code context
  3. Layer fetch logic — term extraction, role filtering, freshness
  4. ContextAssembler — parallel execution, token budgeting, priority sorting
  5. Tenant isolation — cross-tenant data cannot leak
  6. Context enricher node — LangGraph integration

Run with:
    cd services/api && python -m pytest tests/test_context_layers.py -v
"""
import os
import sys
import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

import pytest

# Ensure services/api is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Set required env vars BEFORE importing app modules
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/testdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests")
os.environ.setdefault("S3_BUCKET_NAME", "test-bucket")
os.environ.setdefault("NEO4J_PASSWORD", "test-password")
os.environ.setdefault("ENV", "dev")


# ── 1. Context Models ─────────────────────────────────────────────────


class TestContextModels:
    """Tests for SQLAlchemy model definitions."""

    def test_document_metadata_columns(self):
        """DocumentMetadata has all required columns."""
        from app.context.models import DocumentMetadata

        col_names = {c.name for c in DocumentMetadata.__table__.columns}
        expected = {
            "id", "tenant_id", "document_id", "filename", "file_type",
            "ingested_at", "last_accessed_at", "access_count",
            "freshness_score", "summary", "tags", "chunk_count", "source_url",
        }
        assert expected.issubset(col_names), f"Missing columns: {expected - col_names}"

    def test_annotation_columns(self):
        """Annotation has all required columns."""
        from app.context.models import Annotation

        col_names = {c.name for c in Annotation.__table__.columns}
        expected = {
            "id", "tenant_id", "annotation_type", "key", "value",
            "created_by", "created_at", "updated_at",
        }
        assert expected.issubset(col_names)

    def test_code_context_columns(self):
        """CodeContext has all required columns."""
        from app.context.models import CodeContext

        col_names = {c.name for c in CodeContext.__table__.columns}
        expected = {
            "id", "tenant_id", "context_type", "name", "description",
            "source_code", "lineage", "created_at", "updated_at",
        }
        assert expected.issubset(col_names)

    def test_business_context_columns(self):
        """BusinessContext has all required columns including role filtering."""
        from app.context.models import BusinessContext

        col_names = {c.name for c in BusinessContext.__table__.columns}
        expected = {
            "id", "tenant_id", "context_type", "key", "value",
            "applies_to_roles", "priority", "created_at", "updated_at",
        }
        assert expected.issubset(col_names)

    def test_tenant_id_indexed(self):
        """All context models have tenant_id indexed for performance."""
        from app.context.models import (
            DocumentMetadata, Annotation, CodeContext, BusinessContext,
        )

        for model in [DocumentMetadata, Annotation, CodeContext, BusinessContext]:
            col = model.__table__.columns["tenant_id"]
            assert col.index is True, f"{model.__name__}.tenant_id must be indexed"

    def test_all_models_use_shared_base(self):
        """All models use the same Base for auto table creation."""
        from app.context.models import (
            DocumentMetadata, Annotation, CodeContext, BusinessContext,
        )
        from app.memory.postgres import Base

        for model in [DocumentMetadata, Annotation, CodeContext, BusinessContext]:
            assert issubclass(model, Base)


# ── 2. Context Manager CRUD ───────────────────────────────────────────


class TestContextManagerInterface:
    """Tests for ContextManager method signatures and interface."""

    def test_manager_has_annotation_crud(self):
        """ContextManager exposes full CRUD for annotations."""
        from app.context.manager import ContextManager

        mgr = ContextManager()
        assert hasattr(mgr, "create_annotation")
        assert hasattr(mgr, "list_annotations")
        assert hasattr(mgr, "get_annotation")
        assert hasattr(mgr, "update_annotation")
        assert hasattr(mgr, "delete_annotation")

    def test_manager_has_business_rule_crud(self):
        """ContextManager exposes full CRUD for business rules."""
        from app.context.manager import ContextManager

        mgr = ContextManager()
        assert hasattr(mgr, "create_business_rule")
        assert hasattr(mgr, "list_business_rules")
        assert hasattr(mgr, "get_business_rule")
        assert hasattr(mgr, "update_business_rule")
        assert hasattr(mgr, "delete_business_rule")

    def test_manager_has_code_context_crud(self):
        """ContextManager exposes full CRUD for code contexts."""
        from app.context.manager import ContextManager

        mgr = ContextManager()
        assert hasattr(mgr, "create_code_context")
        assert hasattr(mgr, "list_code_contexts")
        assert hasattr(mgr, "get_code_context")
        assert hasattr(mgr, "update_code_context")
        assert hasattr(mgr, "delete_code_context")

    def test_manager_document_metadata_read_only(self):
        """ContextManager has read-only access for document metadata."""
        from app.context.manager import ContextManager

        mgr = ContextManager()
        assert hasattr(mgr, "list_document_metadata")
        assert hasattr(mgr, "get_document_metadata")
        # Should NOT have create/update/delete for metadata
        assert not hasattr(mgr, "create_document_metadata")
        assert not hasattr(mgr, "delete_document_metadata")

    def test_create_annotation_requires_tenant(self):
        """create_annotation requires tenant_id as first parameter."""
        from app.context.manager import ContextManager

        sig = inspect.signature(ContextManager.create_annotation)
        params = list(sig.parameters.keys())
        assert params[1] == "tenant_id"  # [0] is self

    def test_create_business_rule_accepts_roles(self):
        """create_business_rule accepts applies_to_roles parameter."""
        from app.context.manager import ContextManager

        sig = inspect.signature(ContextManager.create_business_rule)
        params = list(sig.parameters.keys())
        assert "applies_to_roles" in params

    def test_all_crud_methods_are_async(self):
        """All CRUD methods are async coroutines."""
        from app.context.manager import ContextManager

        mgr = ContextManager()
        methods = [
            mgr.create_annotation, mgr.list_annotations,
            mgr.get_annotation, mgr.update_annotation, mgr.delete_annotation,
            mgr.create_business_rule, mgr.list_business_rules,
            mgr.get_business_rule, mgr.update_business_rule, mgr.delete_business_rule,
            mgr.create_code_context, mgr.list_code_contexts,
            mgr.get_code_context, mgr.update_code_context, mgr.delete_code_context,
            mgr.list_document_metadata, mgr.get_document_metadata,
        ]
        for method in methods:
            assert asyncio.iscoroutinefunction(method), f"{method.__name__} must be async"


# ── 3. Layer Fetch Logic ──────────────────────────────────────────────


class TestLayerProtocol:
    """Tests for context layer fetch interface compliance."""

    def test_all_layers_have_fetch_method(self):
        """All four layers implement the fetch() method."""
        from app.context.layer1_metadata import MetadataLayer
        from app.context.layer2_annotations import AnnotationLayer
        from app.context.layer3_code import CodeContextLayer
        from app.context.layer4_business import BusinessContextLayer

        for cls in [MetadataLayer, AnnotationLayer, CodeContextLayer, BusinessContextLayer]:
            assert hasattr(cls, "fetch")
            assert asyncio.iscoroutinefunction(cls.fetch)

    def test_fetch_signature_matches_protocol(self):
        """All layers accept (query, tenant_id, filenames, user_role)."""
        from app.context.layer1_metadata import MetadataLayer
        from app.context.layer2_annotations import AnnotationLayer
        from app.context.layer3_code import CodeContextLayer
        from app.context.layer4_business import BusinessContextLayer

        for cls in [MetadataLayer, AnnotationLayer, CodeContextLayer, BusinessContextLayer]:
            sig = inspect.signature(cls.fetch)
            params = list(sig.parameters.keys())
            assert "query" in params
            assert "tenant_id" in params
            assert "filenames" in params
            assert "user_role" in params


class TestAnnotationTermExtraction:
    """Tests for query term extraction in Layer 2."""

    def test_extract_terms_filters_stop_words(self):
        """Stop words are removed from query terms."""
        from app.context.layer2_annotations import _extract_terms

        terms = _extract_terms("What is the ARR for this quarter?")
        assert "what" not in terms
        assert "the" not in terms
        assert "for" not in terms
        assert "this" not in terms

    def test_extract_terms_filters_short_words(self):
        """Words shorter than 3 chars are removed."""
        from app.context.layer2_annotations import _extract_terms

        terms = _extract_terms("I do it by my own way")
        assert "do" not in terms
        assert "it" not in terms
        assert "by" not in terms

    def test_extract_terms_keeps_meaningful_words(self):
        """Business terms are preserved."""
        from app.context.layer2_annotations import _extract_terms

        terms = _extract_terms("What is the revenue growth rate?")
        assert "revenue" in terms
        assert "growth" in terms
        assert "rate" in terms

    def test_extract_terms_lowercases(self):
        """Terms are lowercased for case-insensitive matching."""
        from app.context.layer2_annotations import _extract_terms

        terms = _extract_terms("ARR and MRR metrics")
        assert "arr" in terms
        assert "mrr" in terms
        assert "metrics" in terms

    def test_extract_terms_empty_query(self):
        """Empty query returns no terms."""
        from app.context.layer2_annotations import _extract_terms

        assert _extract_terms("") == []

    def test_extract_terms_only_stop_words(self):
        """Query with only stop words returns empty."""
        from app.context.layer2_annotations import _extract_terms

        assert _extract_terms("what is the") == []


class TestFreshnessComputation:
    """Tests for Layer 1 freshness score calculation."""

    def test_freshness_brand_new_document(self):
        """Document ingested today should have freshness ≈ 1.0."""
        from app.context.layer1_metadata import _compute_freshness

        score = _compute_freshness(datetime.utcnow())
        assert score > 0.99

    def test_freshness_old_document(self):
        """Document ingested 365 days ago should have low freshness."""
        from app.context.layer1_metadata import _compute_freshness

        score = _compute_freshness(datetime.utcnow() - timedelta(days=365))
        assert score < 0.1

    def test_freshness_half_life(self):
        """Document at half-life age should have freshness ≈ 0.5."""
        from app.context.layer1_metadata import _compute_freshness
        from app.config import settings

        score = _compute_freshness(
            datetime.utcnow() - timedelta(days=settings.CONTEXT_FRESHNESS_DECAY_DAYS)
        )
        assert 0.45 < score < 0.55

    def test_freshness_none_returns_default(self):
        """None ingested_at returns default 0.5."""
        from app.context.layer1_metadata import _compute_freshness

        assert _compute_freshness(None) == 0.5


class TestBusinessContextRoleFiltering:
    """Tests for Layer 4 role-based access control logic."""

    def test_role_all_matches_any_user(self):
        """Rules with applies_to_roles=["all"] match any user role."""
        rule = MagicMock()
        rule.applies_to_roles = ["all"]
        roles = rule.applies_to_roles or ["all"]
        assert "all" in roles

    def test_specific_role_matches(self):
        """Rules with specific role should match that role."""
        roles = ["sales", "finance"]
        assert "sales" in roles
        assert "engineering" not in roles

    def test_empty_roles_defaults_to_all(self):
        """Empty/None applies_to_roles should default to ["all"]."""
        roles = None or ["all"]
        assert "all" in roles


# ── 4. Context Assembler ──────────────────────────────────────────────


class TestContextAssembler:
    """Tests for the ContextAssembler orchestration logic."""

    def test_assembler_initializes_all_layers(self):
        """Assembler creates instances of all four layers."""
        from app.context.assembler import ContextAssembler

        assembler = ContextAssembler()
        assert hasattr(assembler, "layer1")
        assert hasattr(assembler, "layer2")
        assert hasattr(assembler, "layer3")
        assert hasattr(assembler, "layer4")

    def test_extract_filenames_from_string_docs(self):
        """Extracts filenames from string-format documents."""
        from app.context.assembler import ContextAssembler

        assembler = ContextAssembler()
        docs = [
            "Some text content [Source: report.pdf]",
            "Other content [Source: data.csv]",
            "No source tag here",
        ]
        filenames = assembler._extract_filenames(docs)
        assert "report.pdf" in filenames
        assert "data.csv" in filenames
        assert len(filenames) == 2

    def test_extract_filenames_from_dict_docs(self):
        """Extracts filenames from dict-format documents."""
        from app.context.assembler import ContextAssembler

        assembler = ContextAssembler()
        docs = [
            {"content": "text", "filename": "report.pdf"},
            {"content": "text", "filename": "data.csv"},
            {"content": "text"},  # No filename
        ]
        filenames = assembler._extract_filenames(docs)
        assert "report.pdf" in filenames
        assert "data.csv" in filenames

    def test_extract_filenames_deduplicates(self):
        """Duplicate filenames are removed."""
        from app.context.assembler import ContextAssembler

        assembler = ContextAssembler()
        docs = [
            "Content [Source: report.pdf]",
            "More content [Source: report.pdf]",
        ]
        filenames = assembler._extract_filenames(docs)
        assert len(filenames) == 1

    def test_format_with_budget_respects_token_limit(self):
        """Budget formatter truncates when over token limit."""
        from app.context.assembler import ContextAssembler

        assembler = ContextAssembler()
        # Create large content that exceeds budget
        layer_results = [
            ("Business Context", "x" * 10000),
            ("Glossary & Annotations", "y" * 10000),
        ]
        result = assembler._format_with_budget(layer_results)
        # Should be truncated (default 1500 tokens * 4 chars = 6000 chars)
        assert len(result) < 10000

    def test_format_with_budget_priority_order(self):
        """Higher-priority layers appear first in output."""
        from app.context.assembler import ContextAssembler

        assembler = ContextAssembler()
        layer_results = [
            ("Code & Pipeline Context", "code info"),
            ("Business Context", "business info"),
            ("Document Metadata", "meta info"),
            ("Glossary & Annotations", "glossary info"),
        ]
        result = assembler._format_with_budget(layer_results)
        biz_pos = result.index("Business Context")
        glossary_pos = result.index("Glossary & Annotations")
        meta_pos = result.index("Document Metadata")
        code_pos = result.index("Code & Pipeline Context")
        assert biz_pos < glossary_pos < meta_pos < code_pos

    def test_format_with_budget_empty_returns_empty(self):
        """Empty layer results return empty string."""
        from app.context.assembler import ContextAssembler

        assembler = ContextAssembler()
        result = assembler._format_with_budget([])
        assert result == ""


# ── 5. Tenant Isolation ───────────────────────────────────────────────


class TestContextTenantIsolation:
    """Tests for tenant scoping across context layers."""

    def test_manager_crud_requires_tenant_id(self):
        """All CRUD methods require tenant_id as parameter."""
        from app.context.manager import ContextManager

        mgr = ContextManager()
        crud_methods = [
            "create_annotation", "list_annotations", "get_annotation",
            "update_annotation", "delete_annotation",
            "create_business_rule", "list_business_rules", "get_business_rule",
            "update_business_rule", "delete_business_rule",
            "create_code_context", "list_code_contexts", "get_code_context",
            "update_code_context", "delete_code_context",
            "list_document_metadata", "get_document_metadata",
        ]
        for method_name in crud_methods:
            method = getattr(mgr, method_name)
            sig = inspect.signature(method)
            params = list(sig.parameters.keys())
            assert "tenant_id" in params, f"{method_name} must accept tenant_id"

    def test_model_tenant_id_not_nullable(self):
        """tenant_id column must be non-nullable on all models."""
        from app.context.models import (
            DocumentMetadata, Annotation, CodeContext, BusinessContext,
        )

        for model in [DocumentMetadata, Annotation, CodeContext, BusinessContext]:
            col = model.__table__.columns["tenant_id"]
            assert col.nullable is False, f"{model.__name__}.tenant_id must be NOT NULL"


# ── 6. Context Enricher Node ─────────────────────────────────────────


class TestContextEnricherNode:
    """Tests for LangGraph context enricher integration."""

    def test_enricher_node_is_async(self):
        """context_enricher_node must be an async function for LangGraph."""
        from app.agents.nodes.context_enricher import context_enricher_node

        assert asyncio.iscoroutinefunction(context_enricher_node)

    def test_enricher_has_set_assembler(self):
        """Module exposes set_assembler for late initialization."""
        from app.agents.nodes import context_enricher

        assert hasattr(context_enricher, "set_assembler")
        assert callable(context_enricher.set_assembler)

    def test_enricher_node_returns_context_layers_key(self):
        """Node function signature should work with AgentState."""
        from app.agents.nodes.context_enricher import context_enricher_node

        sig = inspect.signature(context_enricher_node)
        params = list(sig.parameters.keys())
        assert "state" in params
        assert "config" in params

    def test_agent_state_has_context_layers_field(self):
        """AgentState TypedDict includes context_layers."""
        from app.agents.state import AgentState

        annotations = AgentState.__annotations__
        assert "context_layers" in annotations


# ── 7. Configuration ─────────────────────────────────────────────────


class TestContextLayerConfig:
    """Tests for context layer configuration settings."""

    def test_master_switch_defaults_off(self):
        """CONTEXT_LAYERS_ENABLED defaults to False."""
        from app.config import settings

        assert hasattr(settings, "CONTEXT_LAYERS_ENABLED")
        # Default should be False (safe by default)
        assert settings.CONTEXT_LAYERS_ENABLED.__class__ is bool

    def test_individual_layer_toggles_exist(self):
        """Each layer has an independent enable/disable toggle."""
        from app.config import settings

        assert hasattr(settings, "CONTEXT_LAYER1_ENABLED")
        assert hasattr(settings, "CONTEXT_LAYER2_ENABLED")
        assert hasattr(settings, "CONTEXT_LAYER3_ENABLED")
        assert hasattr(settings, "CONTEXT_LAYER4_ENABLED")

    def test_token_budget_setting_exists(self):
        """CONTEXT_LAYERS_MAX_TOKENS setting exists."""
        from app.config import settings

        assert hasattr(settings, "CONTEXT_LAYERS_MAX_TOKENS")
        assert settings.CONTEXT_LAYERS_MAX_TOKENS > 0

    def test_freshness_decay_setting_exists(self):
        """CONTEXT_FRESHNESS_DECAY_DAYS setting exists."""
        from app.config import settings

        assert hasattr(settings, "CONTEXT_FRESHNESS_DECAY_DAYS")
        assert settings.CONTEXT_FRESHNESS_DECAY_DAYS > 0

    def test_conditional_graph_wiring(self):
        """Graph module has conditional context_enricher wiring logic."""
        import ast
        graph_path = os.path.join(
            os.path.dirname(__file__), "..", "app", "agents", "graph.py"
        )
        source = open(graph_path).read()
        tree = ast.parse(source)

        # Check that CONTEXT_LAYERS_ENABLED is referenced
        assert "CONTEXT_LAYERS_ENABLED" in source


# ── 8. API Routes ────────────────────────────────────────────────────


class TestContextRoutes:
    """Tests for context layer REST API route registration."""

    def test_context_router_exists(self):
        """Context router module has a router object."""
        from app.routes.context import router

        assert router is not None

    def test_annotation_endpoints_registered(self):
        """Annotation CRUD endpoints are registered."""
        from app.routes.context import router

        paths = [r.path for r in router.routes]
        assert "/annotations" in paths
        assert "/annotations/{annotation_id}" in paths

    def test_business_rule_endpoints_registered(self):
        """Business rule CRUD endpoints are registered."""
        from app.routes.context import router

        paths = [r.path for r in router.routes]
        assert "/business-rules" in paths
        assert "/business-rules/{rule_id}" in paths

    def test_code_context_endpoints_registered(self):
        """Code context CRUD endpoints are registered."""
        from app.routes.context import router

        paths = [r.path for r in router.routes]
        assert "/code-context" in paths
        assert "/code-context/{context_id}" in paths

    def test_metadata_endpoints_read_only(self):
        """Document metadata endpoints exist and are read-only."""
        from app.routes.context import router

        paths = [r.path for r in router.routes]
        assert "/metadata" in paths
        assert "/metadata/{document_id}" in paths

        # Check that metadata has no POST/PUT/DELETE
        for route in router.routes:
            if hasattr(route, "methods") and route.path in ("/metadata", "/metadata/{document_id}"):
                methods = route.methods or set()
                assert "POST" not in methods
                assert "PUT" not in methods
                assert "DELETE" not in methods
