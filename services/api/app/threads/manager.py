# services/api/app/threads/manager.py
"""
CRUD for threads and saved questions. Uses lazy session access so it
works regardless of when init_engine() ran during the lifespan.
"""
from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import desc, select, update
from sqlalchemy.exc import IntegrityError

import app.memory.postgres as _pg
from app.threads.models import SavedQuestion, Thread

# ── Helpers ──────────────────────────────────────────────────────────


def _make_thread_id() -> str:
    """Short URL-safe ID."""
    return uuid4().hex[:16]


def _thread_to_dict(t: Thread, *, active_window_seconds: int = 900) -> dict:
    """Render Thread as the API response shape."""
    is_active = (datetime.utcnow() - t.updated_at).total_seconds() < active_window_seconds
    return {
        "id": t.id,
        "title": t.title,
        "updated_at": t.updated_at.replace(microsecond=0).isoformat() + "Z",
        "message_count": t.message_count,
        "active": is_active,
        "pinned": t.pinned,
    }


def _saved_to_dict(s: SavedQuestion) -> dict:
    return {
        "id": str(s.id),
        "title": s.title,
        "question_text": s.question_text,
        "scope": s.scope,
        "pinned": s.pinned,
        "last_run_at": s.last_run_at.replace(microsecond=0).isoformat() + "Z" if s.last_run_at else None,
        "last_result_preview": s.last_result_preview,
    }


# ── Threads CRUD ─────────────────────────────────────────────────────


async def list_threads(tenant_id: str, user_id: str, limit: int = 20, pinned_only: bool = False):
    if _pg.AsyncSessionLocal is None:
        return []
    async with _pg.AsyncSessionLocal() as s:
        stmt = (
            select(Thread)
            .where(Thread.tenant_id == tenant_id, Thread.user_id == user_id)
            .order_by(desc(Thread.updated_at))
            .limit(limit)
        )
        if pinned_only:
            stmt = stmt.where(Thread.pinned == True)  # noqa: E712
        result = await s.execute(stmt)
        return [_thread_to_dict(t) for t in result.scalars().all()]


async def get_thread(tenant_id: str, user_id: str, thread_id: str) -> Optional[dict]:
    if _pg.AsyncSessionLocal is None:
        return None
    async with _pg.AsyncSessionLocal() as s:
        result = await s.execute(
            select(Thread).where(
                Thread.id == thread_id,
                Thread.tenant_id == tenant_id,
                Thread.user_id == user_id,
            )
        )
        t = result.scalar_one_or_none()
        return _thread_to_dict(t) if t else None


async def update_thread_title(
    tenant_id: str, user_id: str, thread_id: str, title: str
) -> bool:
    """Replace the thread title (used after LLM auto-titling)."""
    if _pg.AsyncSessionLocal is None or not title.strip():
        return False
    async with _pg.AsyncSessionLocal() as s:
        result = await s.execute(
            update(Thread)
            .where(
                Thread.id == thread_id,
                Thread.tenant_id == tenant_id,
                Thread.user_id == user_id,
            )
            .values(title=title.strip()[:500])
        )
        await s.commit()
        return result.rowcount > 0


async def upsert_thread(
    tenant_id: str,
    user_id: str,
    thread_id: str,
    title: Optional[str] = None,
    increment_count: bool = False,
) -> dict:
    """
    Idempotent. Creates the thread if missing, updates title and message
    count if provided. Always bumps updated_at.
    """
    if _pg.AsyncSessionLocal is None:
        raise RuntimeError("Postgres not initialised")
    async with _pg.AsyncSessionLocal() as s:
        result = await s.execute(
            select(Thread).where(
                Thread.id == thread_id,
                Thread.tenant_id == tenant_id,
                Thread.user_id == user_id,
            )
        )
        t = result.scalar_one_or_none()
        now = datetime.utcnow()
        if t is None:
            t = Thread(
                id=thread_id,
                tenant_id=tenant_id,
                user_id=user_id,
                title=title or "Untitled thread",
                message_count=1 if increment_count else 0,
                created_at=now,
                updated_at=now,
            )
            s.add(t)
        else:
            if title and t.title == "Untitled thread":
                t.title = title
            if increment_count:
                t.message_count = (t.message_count or 0) + 1
            t.updated_at = now
        try:
            await s.commit()
            await s.refresh(t)
        except IntegrityError:
            await s.rollback()
            raise
        return _thread_to_dict(t)


async def pin_thread(tenant_id: str, user_id: str, thread_id: str, pinned: bool) -> bool:
    if _pg.AsyncSessionLocal is None:
        return False
    async with _pg.AsyncSessionLocal() as s:
        result = await s.execute(
            update(Thread)
            .where(
                Thread.id == thread_id,
                Thread.tenant_id == tenant_id,
                Thread.user_id == user_id,
            )
            .values(pinned=pinned)
        )
        await s.commit()
        return result.rowcount > 0


# ── Saved Questions CRUD ─────────────────────────────────────────────


async def list_saved_questions(tenant_id: str, user_id: str, pinned_only: bool = False, limit: int = 50):
    if _pg.AsyncSessionLocal is None:
        return []
    async with _pg.AsyncSessionLocal() as s:
        stmt = (
            select(SavedQuestion)
            .where(SavedQuestion.tenant_id == tenant_id, SavedQuestion.user_id == user_id)
            .order_by(desc(SavedQuestion.last_run_at).nulls_last(), desc(SavedQuestion.created_at))
            .limit(limit)
        )
        if pinned_only:
            stmt = stmt.where(SavedQuestion.pinned == True)  # noqa: E712
        result = await s.execute(stmt)
        return [_saved_to_dict(q) for q in result.scalars().all()]


async def create_saved_question(
    tenant_id: str,
    user_id: str,
    title: str,
    question_text: str,
    scope: str = "auto",
    pinned: bool = False,
) -> dict:
    if _pg.AsyncSessionLocal is None:
        raise RuntimeError("Postgres not initialised")
    async with _pg.AsyncSessionLocal() as s:
        q = SavedQuestion(
            tenant_id=tenant_id,
            user_id=user_id,
            title=title,
            question_text=question_text,
            scope=scope,
            pinned=pinned,
        )
        s.add(q)
        await s.commit()
        await s.refresh(q)
        return _saved_to_dict(q)


async def update_saved_question(
    tenant_id: str,
    user_id: str,
    question_id: int,
    *,
    title: Optional[str] = None,
    pinned: Optional[bool] = None,
    last_run_at: Optional[datetime] = None,
    last_result_preview: Optional[str] = None,
) -> Optional[dict]:
    if _pg.AsyncSessionLocal is None:
        return None
    values = {}
    if title is not None:
        values["title"] = title
    if pinned is not None:
        values["pinned"] = pinned
    if last_run_at is not None:
        values["last_run_at"] = last_run_at
    if last_result_preview is not None:
        values["last_result_preview"] = last_result_preview
    if not values:
        # Nothing to update — just return the existing
        async with _pg.AsyncSessionLocal() as s:
            row = await s.execute(
                select(SavedQuestion).where(
                    SavedQuestion.id == question_id,
                    SavedQuestion.tenant_id == tenant_id,
                    SavedQuestion.user_id == user_id,
                )
            )
            q = row.scalar_one_or_none()
            return _saved_to_dict(q) if q else None

    async with _pg.AsyncSessionLocal() as s:
        await s.execute(
            update(SavedQuestion)
            .where(
                SavedQuestion.id == question_id,
                SavedQuestion.tenant_id == tenant_id,
                SavedQuestion.user_id == user_id,
            )
            .values(**values)
        )
        await s.commit()
        row = await s.execute(
            select(SavedQuestion).where(
                SavedQuestion.id == question_id,
                SavedQuestion.tenant_id == tenant_id,
                SavedQuestion.user_id == user_id,
            )
        )
        q = row.scalar_one_or_none()
        return _saved_to_dict(q) if q else None


def derive_title(message: str, max_len: int = 60) -> str:
    """
    Auto-derive a thread title from the first user message.
    Trim, drop trailing punctuation, cap length.
    """
    title = (message or "").strip().split("\n", 1)[0]
    title = title.rstrip(" .?!,:;")
    if len(title) > max_len:
        title = title[: max_len - 1].rstrip() + "…"
    return title or "Untitled thread"


async def delete_saved_question(tenant_id: str, user_id: str, question_id: int) -> bool:
    if _pg.AsyncSessionLocal is None:
        return False
    async with _pg.AsyncSessionLocal() as s:
        result = await s.execute(
            select(SavedQuestion).where(
                SavedQuestion.id == question_id,
                SavedQuestion.tenant_id == tenant_id,
                SavedQuestion.user_id == user_id,
            )
        )
        q = result.scalar_one_or_none()
        if not q:
            return False
        await s.delete(q)
        await s.commit()
        return True
