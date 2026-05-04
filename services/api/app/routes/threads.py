# services/api/app/routes/threads.py
"""
Routes for threads + saved questions. All operations are tenant-scoped
through TenantContext.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth.tenant import TenantContext, get_tenant_context
from app.threads import manager

router = APIRouter()


# ── Threads ──────────────────────────────────────────────────────────


@router.get("/threads")
async def list_threads(
    limit: int = 20,
    pinned_only: bool = False,
    ctx: TenantContext = Depends(get_tenant_context),
):
    return {
        "threads": await manager.list_threads(
            ctx.tenant_id, ctx.user_id, limit=limit, pinned_only=pinned_only
        )
    }


@router.get("/threads/{thread_id}")
async def get_thread(
    thread_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
):
    t = await manager.get_thread(ctx.tenant_id, ctx.user_id, thread_id)
    if not t:
        raise HTTPException(status_code=404, detail="Thread not found")
    return t


class PinThreadRequest(BaseModel):
    pinned: bool


@router.post("/threads/{thread_id}/pin")
async def pin_thread(
    thread_id: str,
    body: PinThreadRequest,
    ctx: TenantContext = Depends(get_tenant_context),
):
    ok = await manager.pin_thread(ctx.tenant_id, ctx.user_id, thread_id, body.pinned)
    if not ok:
        raise HTTPException(status_code=404, detail="Thread not found")
    return {"ok": True, "thread_id": thread_id, "pinned": body.pinned}


# ── Saved Questions ──────────────────────────────────────────────────


class SavedQuestionCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    question_text: str = Field(..., min_length=1)
    scope: str = "auto"
    pinned: bool = False


class SavedQuestionUpdate(BaseModel):
    title: Optional[str] = None
    pinned: Optional[bool] = None
    last_result_preview: Optional[str] = None


@router.get("/saved-questions")
async def list_saved_questions(
    pinned_only: bool = False,
    limit: int = 50,
    ctx: TenantContext = Depends(get_tenant_context),
):
    return {
        "saved_questions": await manager.list_saved_questions(
            ctx.tenant_id, ctx.user_id, pinned_only=pinned_only, limit=limit
        )
    }


@router.post("/saved-questions")
async def create_saved_question(
    body: SavedQuestionCreate,
    ctx: TenantContext = Depends(get_tenant_context),
):
    return await manager.create_saved_question(
        ctx.tenant_id,
        ctx.user_id,
        title=body.title,
        question_text=body.question_text,
        scope=body.scope,
        pinned=body.pinned,
    )


@router.put("/saved-questions/{question_id}")
async def update_saved_question(
    question_id: int,
    body: SavedQuestionUpdate,
    ctx: TenantContext = Depends(get_tenant_context),
):
    updated = await manager.update_saved_question(
        ctx.tenant_id,
        ctx.user_id,
        question_id,
        title=body.title,
        pinned=body.pinned,
        last_result_preview=body.last_result_preview,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Saved question not found")
    return updated


@router.delete("/saved-questions/{question_id}")
async def delete_saved_question(
    question_id: int,
    ctx: TenantContext = Depends(get_tenant_context),
):
    ok = await manager.delete_saved_question(ctx.tenant_id, ctx.user_id, question_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Saved question not found")
    return {"ok": True}
