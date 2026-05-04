# services/api/app/threads/models.py
"""
SQLAlchemy models for Threads + Saved Questions.

Threads are the durable wrapper around `chat_history` rows — they carry
title, pin state, last-activity timestamp, and tenant scope.

Saved Questions are user-bookmarked queries with their last-result preview,
re-runnable on demand.

These models register against the existing `Base` so that
`Base.metadata.create_all()` (called from main.py lifespan) auto-creates
their tables on first run.
"""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, Text

from app.memory.postgres import Base


class Thread(Base):
    """
    A persistent conversation. Title is auto-derived from the first user
    message; users can rename or pin.

    The `id` is a string (UUID-ish) so it's URL-safe in /threads/:id.
    """

    __tablename__ = "threads"

    id = Column(String(64), primary_key=True)
    tenant_id = Column(String(255), nullable=False)
    user_id = Column(String(255), nullable=False)
    title = Column(String(500), nullable=False, default="Untitled thread")
    pinned = Column(Boolean, nullable=False, default=False)
    message_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index("idx_threads_tenant_user_updated", "tenant_id", "user_id", "updated_at"),
        Index("idx_threads_tenant_pinned", "tenant_id", "pinned"),
    )


class SavedQuestion(Base):
    """
    User-bookmarked question. Re-runnable; we cache the last result preview
    so the Home page can show "12 rows · R$ 14.2M" without re-running the agent.
    """

    __tablename__ = "saved_questions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(255), nullable=False)
    user_id = Column(String(255), nullable=False)
    title = Column(String(500), nullable=False)
    question_text = Column(Text, nullable=False)
    scope = Column(String(20), nullable=False, default="auto")  # auto/data/docs/code/web
    pinned = Column(Boolean, nullable=False, default=False)
    last_run_at = Column(DateTime, nullable=True)
    last_result_preview = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_saved_q_tenant_user_pinned", "tenant_id", "user_id", "pinned"),
    )
