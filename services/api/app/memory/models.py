# services/api/app/memory/models.py
from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, Integer, String, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class ChatHistory(Base):
    """
    SQLAlchemy Model for the 'chat_history' table.
    Stores the raw conversation log for auditing and context.
    """
    __tablename__ = "chat_history"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Session ID links messages to a specific conversation thread
    session_id = Column(String(255), index=True, nullable=False)

    # User ID for per-user filtering
    user_id = Column(String(255), index=True, nullable=False)

    # Tenant ID for multi-tenant isolation
    # Defaults to "default" for backward compatibility with pre-tenant data
    tenant_id = Column(String(255), index=True, nullable=False, default="default", server_default="default")

    # Role: 'user', 'assistant', or 'system'
    role = Column(String(50), nullable=False)

    # The actual message content
    content = Column(Text, nullable=False)

    # Metadata: Token usage, latency, model version used
    metadata_ = Column(JSON, default={}, nullable=True)

    # Timestamp
    created_at = Column(DateTime, default=datetime.utcnow)
