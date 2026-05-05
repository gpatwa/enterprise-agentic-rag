# services/api/app/audit/manager.py
"""
Audit log writer. Best-effort, never raises into the request path.
Falls back to stdout logging if the DB is unavailable.
"""
import logging
from datetime import datetime
from typing import Any, Optional

import app.memory.postgres as _pg
from app.audit.models import AuditLog

logger = logging.getLogger("audit")


async def log_event(
    *,
    tenant_id: str,
    user_id: str,
    role: Optional[str],
    event_type: str,
    request_id: Optional[str] = None,
    method: Optional[str] = None,
    path: Optional[str] = None,
    status_code: Optional[int] = None,
    duration_ms: Optional[int] = None,
    pii_redacted: bool = False,
    sources_used: Optional[list[str]] = None,
    payload_summary: Optional[str] = None,
    extra: Optional[dict[str, Any]] = None,
) -> None:
    """Persist one audit row. Logs but doesn't raise on failure."""
    if _pg.AsyncSessionLocal is None:
        logger.info(
            "audit (no DB) %s tenant=%s user=%s status=%s",
            event_type, tenant_id, user_id, status_code,
        )
        return
    try:
        async with _pg.AsyncSessionLocal() as s:
            row = AuditLog(
                request_id=request_id,
                tenant_id=tenant_id,
                user_id=user_id,
                role=role,
                event_type=event_type,
                method=method,
                path=path,
                status_code=status_code,
                duration_ms=duration_ms,
                pii_redacted=pii_redacted,
                sources_used=sources_used or [],
                payload_summary=(payload_summary or "")[:2000] or None,
                extra=extra or {},
                created_at=datetime.utcnow(),
            )
            s.add(row)
            await s.commit()
    except Exception as e:
        # Never block the request — but DO log loudly.
        logger.error("audit write failed: %s", e, exc_info=True)


async def list_events(
    tenant_id: str,
    limit: int = 100,
    user_id: Optional[str] = None,
    event_type: Optional[str] = None,
) -> list[dict]:
    """Read recent audit events for compliance review."""
    if _pg.AsyncSessionLocal is None:
        return []
    from sqlalchemy import desc, select

    async with _pg.AsyncSessionLocal() as s:
        stmt = select(AuditLog).where(AuditLog.tenant_id == tenant_id)
        if user_id:
            stmt = stmt.where(AuditLog.user_id == user_id)
        if event_type:
            stmt = stmt.where(AuditLog.event_type == event_type)
        stmt = stmt.order_by(desc(AuditLog.created_at)).limit(limit)
        rows = (await s.execute(stmt)).scalars().all()
        return [
            {
                "id": r.id,
                "request_id": r.request_id,
                "tenant_id": r.tenant_id,
                "user_id": r.user_id,
                "role": r.role,
                "event_type": r.event_type,
                "method": r.method,
                "path": r.path,
                "status_code": r.status_code,
                "duration_ms": r.duration_ms,
                "pii_redacted": r.pii_redacted,
                "sources_used": r.sources_used,
                "payload_summary": r.payload_summary,
                "created_at": r.created_at.replace(microsecond=0).isoformat() + "Z",
            }
            for r in rows
        ]


async def delete_for_user(tenant_id: str, user_id: str) -> int:
    """Right-to-be-forgotten: wipe audit rows. Logs the deletion itself."""
    if _pg.AsyncSessionLocal is None:
        return 0
    from sqlalchemy import delete

    async with _pg.AsyncSessionLocal() as s:
        result = await s.execute(
            delete(AuditLog).where(
                AuditLog.tenant_id == tenant_id, AuditLog.user_id == user_id
            )
        )
        await s.commit()
    deleted = result.rowcount or 0
    # Log a high-level forensic record (no user content).
    logger.warning(
        "GDPR forget: deleted %d audit rows for tenant=%s user=%s",
        deleted, tenant_id, user_id,
    )
    return deleted
