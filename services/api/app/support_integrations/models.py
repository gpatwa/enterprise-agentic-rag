# services/api/app/support_integrations/models.py
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.memory.postgres import Base


class SupportIntegrationConnection(Base):
    """
    Tenant-visible support connector state.

    Customer OAuth credentials live in Nango. Direct connectors use environment
    credentials for local/private deployments, so this table stores metadata
    and connection identifiers, not raw secrets.
    """

    __tablename__ = "support_integration_connections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(255), nullable=False, index=True)
    provider = Column(String(64), nullable=False, index=True)
    auth_mode = Column(String(32), nullable=False, default="nango")
    status = Column(String(32), nullable=False, default="pending")
    nango_connection_id = Column(String(255), nullable=True)
    provider_config_key = Column(String(255), nullable=True)
    external_account_id = Column(String(255), nullable=True)
    metadata_ = Column(JSON, default={})
    last_health_check = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "provider", name="uq_support_conn_tenant_provider"),
        Index("idx_support_conn_tenant_status", "tenant_id", "status"),
    )
