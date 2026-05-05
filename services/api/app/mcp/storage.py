# services/api/app/mcp/storage.py
"""
Persistence layer for MCPConnection rows.

Why a separate module
---------------------
Keeping DB queries out of `manager.py` lets us:
  - unit-test the manager's spawn/dispatch logic against an in-memory
    fake without faking SQLAlchemy
  - surface a tight, audit-friendly query surface to callers
  - swap the backing store later (e.g., DynamoDB for control-plane)
    without touching the orchestration code

All public functions take a SQLAlchemy session as their first argument.
The manager owns session lifecycle; this module is "dumb" data access.

Returned dicts (not ORM objects) cross the public API to avoid leaking
SQLAlchemy session-bound state into long-lived caches.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select, update, delete

from app.mcp.crypto import get_cipher
from app.mcp.errors import MCPCryptoError
from app.mcp.models import MCPConnection
from app.mcp.types import MCPConnectionStatus

logger = logging.getLogger(__name__)


def _serialize(row: MCPConnection, *, decrypt: bool = False) -> dict[str, Any]:
    """ORM → plain dict. Optionally decrypts credentials for spawn callers."""
    out: dict[str, Any] = {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "server_name": row.server_name,
        "status": row.status,
        "last_health_check": (
            row.last_health_check.replace(microsecond=0).isoformat() + "Z"
            if row.last_health_check
            else None
        ),
        "error_message": row.error_message,
        "created_at": row.created_at.replace(microsecond=0).isoformat() + "Z",
        "updated_at": row.updated_at.replace(microsecond=0).isoformat() + "Z",
    }
    if decrypt:
        try:
            out["credentials"] = get_cipher().decrypt(row.encrypted_config)
        except MCPCryptoError:
            # The row is corrupt / wrong key. Surface as a missing-creds
            # signal rather than a 500 — the caller (manager) will retire
            # the connection to ERROR.
            out["credentials"] = None
            out["error_message"] = "credential decrypt failed"
    return out


async def list_for_tenant(
    session, tenant_id: str, *, only_enabled: bool = False
) -> list[dict[str, Any]]:
    """All connections for a tenant. `only_enabled` filters to status=enabled."""
    stmt = select(MCPConnection).where(MCPConnection.tenant_id == tenant_id)
    if only_enabled:
        stmt = stmt.where(MCPConnection.status == MCPConnectionStatus.ENABLED.value)
    stmt = stmt.order_by(MCPConnection.server_name)
    rows = (await session.execute(stmt)).scalars().all()
    return [_serialize(r) for r in rows]


async def get(
    session, tenant_id: str, server_name: str, *, decrypt: bool = False
) -> Optional[dict[str, Any]]:
    """Fetch a single connection. None if it doesn't exist."""
    stmt = select(MCPConnection).where(
        MCPConnection.tenant_id == tenant_id,
        MCPConnection.server_name == server_name,
    )
    row = (await session.execute(stmt)).scalars().first()
    if row is None:
        return None
    return _serialize(row, decrypt=decrypt)


async def upsert(
    session,
    *,
    tenant_id: str,
    server_name: str,
    credentials: dict[str, Any],
    status: MCPConnectionStatus = MCPConnectionStatus.PENDING,
) -> dict[str, Any]:
    """
    Create or replace a connection's credentials in one round-trip.

    Update path preserves created_at; insert path stamps both timestamps.
    """
    encrypted = get_cipher().encrypt(credentials)
    existing_stmt = select(MCPConnection).where(
        MCPConnection.tenant_id == tenant_id,
        MCPConnection.server_name == server_name,
    )
    existing = (await session.execute(existing_stmt)).scalars().first()
    if existing is None:
        row = MCPConnection(
            tenant_id=tenant_id,
            server_name=server_name,
            status=status.value,
            encrypted_config=encrypted,
        )
        session.add(row)
        await session.flush()
    else:
        existing.encrypted_config = encrypted
        existing.status = status.value
        existing.error_message = None
        existing.updated_at = datetime.utcnow()
        row = existing
    await session.commit()
    return _serialize(row)


async def set_status(
    session,
    *,
    tenant_id: str,
    server_name: str,
    status: MCPConnectionStatus,
    error_message: Optional[str] = None,
    health_check_now: bool = False,
) -> bool:
    """Status flip with optional error message + health-check stamp. Returns True if a row matched."""
    values: dict[str, Any] = {
        "status": status.value,
        "error_message": error_message,
        "updated_at": datetime.utcnow(),
    }
    if health_check_now:
        values["last_health_check"] = datetime.utcnow()
    stmt = (
        update(MCPConnection)
        .where(
            MCPConnection.tenant_id == tenant_id,
            MCPConnection.server_name == server_name,
        )
        .values(**values)
    )
    result = await session.execute(stmt)
    await session.commit()
    return (result.rowcount or 0) > 0


async def remove(session, *, tenant_id: str, server_name: str) -> bool:
    """Hard-delete a connection. Caller should reap any live subprocess separately."""
    stmt = delete(MCPConnection).where(
        MCPConnection.tenant_id == tenant_id,
        MCPConnection.server_name == server_name,
    )
    result = await session.execute(stmt)
    await session.commit()
    return (result.rowcount or 0) > 0
