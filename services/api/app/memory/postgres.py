# services/api/app/memory/postgres.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, String, JSON, DateTime, Integer, Text, select, and_, func, true
from datetime import datetime
from app.config import settings

# Single-tenant mode flag — when True, skip tenant_id filtering
_single_tenant = settings.SINGLE_TENANT_MODE

# 1. Database Setup
Base = declarative_base()

# Default tenant for backward compatibility
DEFAULT_TENANT_ID = "default"

# 2. Define the Chat History Table
class ChatHistory(Base):
    """
    Stores every conversation turn.
    """
    __tablename__ = "chat_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, index=True)       # User's conversation ID
    user_id = Column(String, index=True)
    tenant_id = Column(String, index=True, default=DEFAULT_TENANT_ID, server_default=DEFAULT_TENANT_ID)
    role = Column(String)                          # "user" or "assistant"
    content = Column(Text)                         # The text message
    metadata_ = Column(JSON, default={})           # Extra info (latency, tokens used)
    created_at = Column(DateTime, default=datetime.utcnow)


class UserMemory(Base):
    """Persistent cross-session memory for user preferences and facts."""
    __tablename__ = "user_memories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(255), index=True, nullable=False)
    tenant_id = Column(String(255), index=True, nullable=False, default=DEFAULT_TENANT_ID)
    memory_type = Column(String(50), nullable=False)  # "preference" or "fact"
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


# Import context layer models so Base.metadata.create_all() creates their tables
try:
    from app.context.models import DocumentMetadata, Annotation, CodeContext, BusinessContext  # noqa: F401
except ImportError:
    pass  # Context layer not installed (optional)

# Import threads + saved_questions models so their tables are auto-created
try:
    from app.threads.models import Thread, SavedQuestion  # noqa: F401
except ImportError:
    pass

# 3. Async Engine & Session
#    The engine is lazily initialised so that secrets injected via
#    Key Vault during the lifespan hook are available before the first
#    database call.
engine = None
AsyncSessionLocal = None


def init_engine(database_url: str | None = None):
    """
    Create the async engine and session factory.

    Called from the FastAPI lifespan hook after secrets have been
    injected from Key Vault.  Falls back to settings.get_database_url()
    if no explicit URL is provided.
    """
    global engine, AsyncSessionLocal
    url = database_url or settings.get_database_url()
    engine = create_async_engine(
        url,
        echo=False,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_pre_ping=True,
        pool_recycle=300,
    )
    AsyncSessionLocal = sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )

class PostgresMemory:
    """
    Manager for persisting conversation state.
    All operations are scoped by tenant_id to enforce data isolation.
    """
    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        user_id: str,
        tenant_id: str = DEFAULT_TENANT_ID,
    ):
        """Store a single conversation turn, tagged with tenant_id."""
        async with AsyncSessionLocal() as session:
            async with session.begin():
                msg = ChatHistory(
                    session_id=session_id,
                    role=role,
                    content=content,
                    user_id=user_id,
                    tenant_id=tenant_id,
                )
                session.add(msg)
                # Commit happens automatically via 'async with session.begin()'

    async def get_history(
        self,
        session_id: str,
        limit: int = 10,
        user_id: str | None = None,
        tenant_id: str = DEFAULT_TENANT_ID,
    ):
        """
        Fetch last N messages for context window.

        Filters by session_id AND tenant_id.
        Optionally also by user_id for session ownership validation.
        """
        async with AsyncSessionLocal() as session:
            conditions = [
                ChatHistory.session_id == session_id,
            ]
            if not _single_tenant:
                conditions.append(ChatHistory.tenant_id == tenant_id)
            if user_id is not None:
                conditions.append(ChatHistory.user_id == user_id)

            result = await session.execute(
                select(ChatHistory)
                .where(and_(*conditions))
                .order_by(ChatHistory.created_at.desc())
                .limit(limit)
            )
            # Reverse to get chronological order (Oldest -> Newest)
            return result.scalars().all()[::-1]

    async def session_belongs_to(
        self,
        session_id: str,
        user_id: str,
        tenant_id: str,
    ) -> bool | None:
        """
        Verify that a session belongs to the given user+tenant.

        Returns:
            True  – session exists and belongs to this user+tenant
            False – session exists but belongs to someone else (cross-tenant!)
            None  – session is brand new (no messages yet)

        In single-tenant mode, only checks user ownership (no tenant filter).
        """
        async with AsyncSessionLocal() as session:
            # Check if any messages exist for this session_id at all
            result = await session.execute(
                select(ChatHistory.user_id, ChatHistory.tenant_id)
                .where(ChatHistory.session_id == session_id)
                .limit(1)
            )
            row = result.first()

            if row is None:
                # Brand-new session — anyone can claim it
                return None

            # Session exists — verify ownership
            if _single_tenant:
                return row.user_id == user_id
            return row.user_id == user_id and row.tenant_id == tenant_id


    async def get_user_memories(
        self,
        user_id: str,
        tenant_id: str = DEFAULT_TENANT_ID,
        limit: int = 10,
    ):
        """Load persisted memories for a user (max 10, newest first)."""
        async with AsyncSessionLocal() as session:
            conditions = [UserMemory.user_id == user_id]
            if not _single_tenant:
                conditions.append(UserMemory.tenant_id == tenant_id)
            result = await session.execute(
                select(UserMemory)
                .where(and_(*conditions))
                .order_by(UserMemory.created_at.desc())
                .limit(limit)
            )
            return result.scalars().all()

    async def add_user_memory(
        self,
        user_id: str,
        tenant_id: str,
        memory_type: str,
        content: str,
    ):
        """Store a new memory. Enforces max 10 per user by deleting the oldest."""
        async with AsyncSessionLocal() as session:
            async with session.begin():
                mem_conditions = [UserMemory.user_id == user_id]
                if not _single_tenant:
                    mem_conditions.append(UserMemory.tenant_id == tenant_id)

                count_result = await session.execute(
                    select(func.count(UserMemory.id))
                    .where(and_(*mem_conditions))
                )
                count = count_result.scalar()

                if count >= 10:
                    oldest = await session.execute(
                        select(UserMemory)
                        .where(and_(*mem_conditions))
                        .order_by(UserMemory.created_at.asc())
                        .limit(1)
                    )
                    old_mem = oldest.scalars().first()
                    if old_mem:
                        await session.delete(old_mem)

                session.add(UserMemory(
                    user_id=user_id,
                    tenant_id=tenant_id,
                    memory_type=memory_type,
                    content=content,
                ))


postgres_memory = PostgresMemory()


# --- Long-term memory extraction (background task) ---

import logging
from app.agents.json_utils import extract_json

logger = logging.getLogger(__name__)

MEMORY_EXTRACT_PROMPT = """Analyze this conversation and extract any user preferences or important facts worth remembering for future conversations.

Conversation:
{conversation}

If there are memorable items, output JSON:
{{
    "memories": [
        {{"type": "preference", "content": "User prefers concise answers"}},
        {{"type": "fact", "content": "Their fiscal year starts in April"}}
    ]
}}

If nothing is worth remembering, output:
{{"memories": []}}

Only extract clear, explicit preferences or facts. Do not infer or guess."""


async def extract_and_store_memories(
    user_message: str,
    assistant_message: str,
    user_id: str,
    tenant_id: str,
):
    """Background task: extract memories from the latest exchange."""
    from app.clients.ray_llm import llm_client

    conversation = f"User: {user_message}\nAssistant: {assistant_message}"

    try:
        response_text = await llm_client.chat_completion(
            messages=[{
                "role": "user",
                "content": MEMORY_EXTRACT_PROMPT.format(conversation=conversation),
            }],
            temperature=0.0,
        )
        result = extract_json(response_text)
        memories = result.get("memories", [])

        memory_store = PostgresMemory()
        for mem in memories:
            await memory_store.add_user_memory(
                user_id=user_id,
                tenant_id=tenant_id,
                memory_type=mem.get("type", "fact"),
                content=mem.get("content", ""),
            )

        if memories:
            logger.info(f"Extracted {len(memories)} memories for user {user_id}")

    except Exception as e:
        logger.error(f"Memory extraction failed: {e}")
