# services/api/app/context/models.py
"""
SQLAlchemy models for the four Context Layers.

Layer 1: DocumentMetadata  — document-level metadata, usage signals, freshness
Layer 2: Annotation        — human-curated glossary terms, KPI definitions, notes
Layer 3: CodeContext       — code/pipeline context, data lineage
Layer 4: BusinessContext   — institutional terminology, business rules, role-based context

All tables are tenant-scoped and auto-created on startup via Base.metadata.create_all().
"""
from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, Float, Integer, String, Text

from app.memory.postgres import Base


class DocumentMetadata(Base):
    """Layer 1 — Document metadata & usage signals.

    Populated during ingestion. Updated at query time (access tracking).
    """
    __tablename__ = "document_metadata"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(255), index=True, nullable=False)
    document_id = Column(String(255), index=True)
    filename = Column(String(500))
    file_type = Column(String(50))
    ingested_at = Column(DateTime, default=datetime.utcnow)
    last_accessed_at = Column(DateTime)
    access_count = Column(Integer, default=0)
    freshness_score = Column(Float, default=1.0)
    summary = Column(Text)
    tags = Column(JSON, default=list)
    chunk_count = Column(Integer, default=0)
    source_url = Column(String(1000))


class Annotation(Base):
    """Layer 2 — Human annotations, glossary terms, KPI definitions.

    Admin-curated via the Context Admin API.
    """
    __tablename__ = "annotations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(255), index=True, nullable=False)
    annotation_type = Column(String(50), nullable=False)  # "glossary", "kpi", "description", "note"
    key = Column(String(500), nullable=False)
    value = Column(Text, nullable=False)
    created_by = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)


class CodeContext(Base):
    """Layer 3 — Code & pipeline context, data lineage.

    Can be populated via Admin API or ingestion-time code indexer.
    """
    __tablename__ = "code_context"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(255), index=True, nullable=False)
    context_type = Column(String(50), nullable=False)  # "etl_pipeline", "sql_query", "api_endpoint", "data_lineage"
    name = Column(String(500), nullable=False)
    description = Column(Text)
    source_code = Column(Text)
    lineage = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)


class BusinessContext(Base):
    """Layer 4 — Institutional/business context.

    Admin-curated terminology, business rules, org-specific context.
    Filtered by user role at query time.
    """
    __tablename__ = "business_context"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(255), index=True, nullable=False)
    context_type = Column(String(50), nullable=False)  # "terminology", "business_rule", "role_context", "org_structure"
    key = Column(String(500), nullable=False)
    value = Column(Text, nullable=False)
    applies_to_roles = Column(JSON, default=lambda: ["all"])
    priority = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)
