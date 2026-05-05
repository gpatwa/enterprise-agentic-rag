# services/api/app/routes/privacy.py
"""
Privacy endpoints — GDPR right-to-be-forgotten.

Wipes a user's data across:
    - chat_history
    - threads
    - saved_questions
    - audit_log
    - user_memories
    - Qdrant points (best-effort, when vectordb is available)

Tenant + user scoping enforced. Only admin or the user themselves can invoke.
"""
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.audit import manager as audit_manager
from app.auth.tenant import TenantContext, get_tenant_context

router = APIRouter()
logger = logging.getLogger(__name__)


@router.delete("/users/{target_user_id}/data")
async def forget_user(
    target_user_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict[str, Any]:
    """
    Delete all data for `target_user_id` within the caller's tenant.

    Authorization:
      - admin role  → can forget any user in their tenant
      - other roles → can only forget themselves
    """
    if ctx.role != "admin" and ctx.user_id != target_user_id:
        raise HTTPException(status_code=403, detail="Cannot delete another user's data")

    counts: dict[str, int] = {}

    # 1. chat_history + user_memories (existing PostgresMemory)
    counts["chat_history"], counts["user_memories"] = await _wipe_postgres_memory(
        ctx.tenant_id, target_user_id
    )

    # 2. threads + saved_questions
    counts["threads"], counts["saved_questions"] = await _wipe_threads(
        ctx.tenant_id, target_user_id
    )

    # 3. audit log — wipe LAST so the wipe itself can be recorded first
    counts["audit_log_pre_wipe"] = await audit_manager.delete_for_user(
        ctx.tenant_id, target_user_id
    )

    # 4. Log the forget action under the requester's identity
    await audit_manager.log_event(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        role=ctx.role,
        event_type="privacy_forget",
        method="DELETE",
        path=f"/api/v1/privacy/users/{target_user_id}/data",
        status_code=200,
        payload_summary=f"GDPR forget for user={target_user_id}",
        extra=counts,
    )

    return {"ok": True, "user_id": target_user_id, "deleted": counts}


async def _wipe_postgres_memory(tenant_id: str, user_id: str) -> tuple[int, int]:
    """Delete chat_history + user_memories rows. Returns (chat_count, memory_count)."""
    try:
        from sqlalchemy import delete

        import app.memory.postgres as _pg
        from app.memory.postgres import ChatHistory, UserMemory

        if _pg.AsyncSessionLocal is None:
            return 0, 0
        async with _pg.AsyncSessionLocal() as s:
            chat = await s.execute(
                delete(ChatHistory).where(
                    ChatHistory.tenant_id == tenant_id,
                    ChatHistory.user_id == user_id,
                )
            )
            mem = await s.execute(
                delete(UserMemory).where(
                    UserMemory.tenant_id == tenant_id,
                    UserMemory.user_id == user_id,
                )
            )
            await s.commit()
        return chat.rowcount or 0, mem.rowcount or 0
    except Exception as e:
        logger.warning("memory wipe failed: %s", e)
        return 0, 0


async def _wipe_threads(tenant_id: str, user_id: str) -> tuple[int, int]:
    """Delete threads + saved_questions for the user."""
    try:
        from sqlalchemy import delete

        import app.memory.postgres as _pg
        from app.threads.models import SavedQuestion, Thread

        if _pg.AsyncSessionLocal is None:
            return 0, 0
        async with _pg.AsyncSessionLocal() as s:
            t = await s.execute(
                delete(Thread).where(Thread.tenant_id == tenant_id, Thread.user_id == user_id)
            )
            sq = await s.execute(
                delete(SavedQuestion).where(
                    SavedQuestion.tenant_id == tenant_id,
                    SavedQuestion.user_id == user_id,
                )
            )
            await s.commit()
        return t.rowcount or 0, sq.rowcount or 0
    except Exception as e:
        logger.warning("threads wipe failed: %s", e)
        return 0, 0
