"""Durable analytics query-outcome records, independent of any customer warehouse."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Index, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Metadata owned exclusively by the Analytics control store."""


class AnalyticsQueryOutcome(Base):
    """Persisted envelope for a future v2 query outcome and its public evidence."""

    __tablename__ = "analytics_query_outcomes"
    __table_args__ = (
        Index("ix_analytics_query_outcomes_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    query_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    dataset: Mapped[str] = mapped_column(String(100), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    contract_version: Mapped[str] = mapped_column(String(16), nullable=False)
    policy_decision_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    request_fingerprint: Mapped[str | None] = mapped_column(String(255), nullable=True)
    response_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )
