# services/api/app/mcp/models.py
"""
SQLAlchemy model for tenant ↔ MCP-server connections.

One row per (tenant_id, server_name). Credentials are encrypted at rest
via app/mcp/crypto.py — `encrypted_config` is a Fernet ciphertext of a
JSON dict. The DB never sees plaintext tokens.

`status` mirrors MCPConnectionStatus; we keep the column nullable+string
rather than a DB enum so adding states later doesn't require an ALTER.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.memory.postgres import Base


class MCPConnection(Base):
    __tablename__ = "mcp_connections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(255), nullable=False, index=True)
    server_name = Column(String(64), nullable=False, index=True)
    # MCPConnectionStatus value. Default "pending" until first health check.
    status = Column(String(32), nullable=False, default="pending")
    # Fernet ciphertext of a JSON-encoded credentials dict. Decrypted in
    # memory only at subprocess spawn time; never logged.
    encrypted_config = Column(Text, nullable=False)
    last_health_check = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "server_name", name="uq_mcp_tenant_server"),
        Index("idx_mcp_tenant_status", "tenant_id", "status"),
    )

    def __repr__(self) -> str:  # pragma: no cover — debug helper
        return (
            f"<MCPConnection id={self.id} tenant={self.tenant_id} "
            f"server={self.server_name} status={self.status}>"
        )
