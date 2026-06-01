# services/api/app/support/models.py
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.memory.postgres import Base


class SupportCustomer(Base):
    __tablename__ = "support_customers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(255), nullable=False, index=True)
    provider = Column(String(64), nullable=False, index=True)
    external_id = Column(String(255), nullable=False)
    email = Column(String(500), nullable=True)
    name = Column(String(500), nullable=True)
    role = Column(String(100), nullable=True)
    raw = Column(JSON, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "provider", "external_id", name="uq_support_customer"),
        Index("idx_support_customer_tenant_provider", "tenant_id", "provider"),
        Index("idx_support_customer_tenant_email", "tenant_id", "email"),
    )


class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(255), nullable=False, index=True)
    provider = Column(String(64), nullable=False, index=True)
    external_id = Column(String(255), nullable=False)
    subject = Column(String(1000), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(100), nullable=True, index=True)
    priority = Column(String(100), nullable=True)
    category = Column(String(100), nullable=True)
    channel = Column(String(100), nullable=True)
    requester_external_id = Column(String(255), nullable=True)
    assignee_external_id = Column(String(255), nullable=True)
    organization_external_id = Column(String(255), nullable=True)
    tags = Column(JSON, default=list)
    custom_fields = Column(JSON, default=dict)
    raw = Column(JSON, default=dict)
    source_url = Column(String(1500), nullable=True)
    created_at_external = Column(DateTime, nullable=True)
    updated_at_external = Column(DateTime, nullable=True)
    first_seen_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_synced_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "provider", "external_id", name="uq_support_ticket"),
        Index("idx_support_ticket_tenant_provider_status", "tenant_id", "provider", "status"),
        Index("idx_support_ticket_tenant_updated", "tenant_id", "updated_at_external"),
        Index("idx_support_ticket_requester", "tenant_id", "provider", "requester_external_id"),
    )


class SupportTicketComment(Base):
    __tablename__ = "support_ticket_comments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(255), nullable=False, index=True)
    provider = Column(String(64), nullable=False, index=True)
    ticket_external_id = Column(String(255), nullable=False)
    external_id = Column(String(255), nullable=False)
    author_external_id = Column(String(255), nullable=True)
    body_text = Column(Text, nullable=True)
    body_html = Column(Text, nullable=True)
    is_public = Column(Boolean, nullable=False, default=True)
    raw = Column(JSON, default=dict)
    created_at_external = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "provider",
            "ticket_external_id",
            "external_id",
            name="uq_support_ticket_comment",
        ),
        Index("idx_support_comment_ticket", "tenant_id", "provider", "ticket_external_id"),
    )


class SupportArticle(Base):
    __tablename__ = "support_articles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(255), nullable=False, index=True)
    provider = Column(String(64), nullable=False, index=True)
    external_id = Column(String(255), nullable=False)
    title = Column(String(1000), nullable=False)
    body_text = Column(Text, nullable=True)
    body_html = Column(Text, nullable=True)
    locale = Column(String(50), nullable=True)
    source_url = Column(String(1500), nullable=True)
    raw = Column(JSON, default=dict)
    updated_at_external = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "provider", "external_id", name="uq_support_article"),
        Index("idx_support_article_tenant_provider", "tenant_id", "provider"),
    )


class SupportSyncRun(Base):
    __tablename__ = "support_sync_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(255), nullable=False, index=True)
    provider = Column(String(64), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="running")
    cursor_started_at = Column(String(100), nullable=True)
    cursor_finished_at = Column(String(100), nullable=True)
    records_seen = Column(Integer, nullable=False, default=0)
    records_upserted = Column(Integer, nullable=False, default=0)
    records_skipped = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    metadata_ = Column(JSON, default=dict)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    created_by = Column(String(255), nullable=True)

    __table_args__ = (
        Index("idx_support_sync_tenant_provider_started", "tenant_id", "provider", "started_at"),
        Index("idx_support_sync_tenant_status", "tenant_id", "status"),
    )


class SupportIndexRecord(Base):
    __tablename__ = "support_index_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(255), nullable=False, index=True)
    provider = Column(String(64), nullable=False, index=True)
    source_type = Column(String(32), nullable=False, index=True)
    source_id = Column(String(255), nullable=False)
    content_hash = Column(String(64), nullable=False)
    chunk_count = Column(Integer, nullable=False, default=0)
    index_version = Column(String(64), nullable=False)
    indexed_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "provider",
            "source_type",
            "source_id",
            name="uq_support_index_record",
        ),
        Index("idx_support_index_tenant_provider", "tenant_id", "provider"),
        Index("idx_support_index_tenant_source", "tenant_id", "source_type", "source_id"),
    )


class SupportJob(Base):
    __tablename__ = "support_jobs"

    id = Column(String(64), primary_key=True)
    tenant_id = Column(String(255), nullable=False, index=True)
    requested_by = Column(String(255), nullable=False)
    job_type = Column(String(64), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="queued", index=True)
    providers = Column(JSON, default=list)
    limit = Column(Integer, nullable=False, default=100)
    seed_demo = Column(Boolean, nullable=False, default=False)
    current_step = Column(String(255), nullable=True)
    result = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=1)
    locked_by = Column(String(255), nullable=True)
    locked_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index("idx_support_job_tenant_status_created", "tenant_id", "status", "created_at"),
        Index("idx_support_job_status_locked", "status", "locked_at"),
        Index("idx_support_job_type_status", "job_type", "status"),
    )
