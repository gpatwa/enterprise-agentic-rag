# services/api/app/audit/models.py
"""
Audit log table. One row per ask/answer turn or admin action. SOC2-grade.

Fields:
    event_type      "chat", "tool_call", "data_query", "context_admin", ...
    user_id, tenant_id, role
    method + path   for HTTP-driven events
    sources_used    list of source identifiers the agent touched
    pii_redacted    True if redactor scrubbed anything
    duration_ms     end-to-end latency
    status_code
    request_id      correlation id for tracing
"""
from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, Index, Integer, String, Text

from app.memory.postgres import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    request_id = Column(String(64), index=True)
    tenant_id = Column(String(255), nullable=False, index=True)
    user_id = Column(String(255), nullable=False, index=True)
    role = Column(String(64))
    event_type = Column(String(64), nullable=False, index=True)
    method = Column(String(10))
    path = Column(String(500))
    status_code = Column(Integer)
    duration_ms = Column(Integer)
    pii_redacted = Column(Boolean, default=False)
    sources_used = Column(JSON, default=list)
    payload_summary = Column(Text)
    extra = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("idx_audit_tenant_created", "tenant_id", "created_at"),
        Index("idx_audit_user_created", "user_id", "created_at"),
        Index("idx_audit_event_type_created", "event_type", "created_at"),
    )
