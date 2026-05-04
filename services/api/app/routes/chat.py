# services/api/app/routes/chat.py
import asyncio
import uuid
import json
import logging
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.auth.tenant import TenantContext, get_tenant_context
# Import classes for type hinting
from app.cache.semantic import SemanticCache, semantic_cache as global_cache
from app.memory.postgres import PostgresMemory, postgres_memory as global_memory
from app.clients.ray_llm import RayLLMClient, llm_client as global_llm
from app.agents.graph import agent_app
from app.agents.state import AgentState

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Thread persistence helper ────────────────────────────────────────
async def _upsert_thread_safe(
    tenant_id: str, user_id: str, session_id: str, first_user_message: str
) -> None:
    """
    Touch the threads row for this session: create if missing (using the
    first user message as title), increment message count, bump updated_at.
    Best-effort — never raises; failures are logged.
    """
    try:
        from app.threads.manager import derive_title, upsert_thread

        await upsert_thread(
            tenant_id=tenant_id,
            user_id=user_id,
            thread_id=session_id,
            title=derive_title(first_user_message),
            increment_count=True,
        )
    except Exception as e:
        logger.warning("thread upsert failed for session %s: %s", session_id, e)

# --- Dependency Providers (DI) ---
# These wrappers allow us to override dependencies easily in pytest
# e.g., app.dependency_overrides[get_llm_client] = MockLLMClient

def get_semantic_cache() -> SemanticCache:
    return global_cache

def get_memory() -> PostgresMemory:
    return global_memory

def get_llm_client() -> RayLLMClient:
    return global_llm

# --- Schemas ---
class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="The user's query")
    session_id: Optional[str] = Field(default=None, description="UUID for the conversation thread")

# --- Routes ---

@router.post("/stream")
async def chat_stream(
    req: ChatRequest,
    background_tasks: BackgroundTasks,
    ctx: TenantContext = Depends(get_tenant_context),
    # Inject dependencies via FastAPI Depends
    cache: SemanticCache = Depends(get_semantic_cache),
    memory: PostgresMemory = Depends(get_memory),
    llm: RayLLMClient = Depends(get_llm_client)
):
    """
    Main Chat Endpoint (Streaming).
    Orchestrates the RAG flow: Cache -> History -> Agent -> Stream.

    Session ownership is enforced: a session_id created by tenant-A / user-A
    cannot be accessed by tenant-B or user-B.
    """
    # 1. Setup Session Context
    session_id = req.session_id or str(uuid.uuid4())
    user_id = ctx.user_id
    tenant_id = ctx.tenant_id

    logger.info(f"Chat request for session {session_id} from user {user_id} (tenant={tenant_id})")

    # 1b. Session Ownership Check (prevents cross-tenant data access)
    if req.session_id:
        # Only validate ownership for existing sessions (user supplied a session_id)
        ownership = await memory.session_belongs_to(session_id, user_id, tenant_id)
        if ownership is False:
            # Session exists but belongs to another user/tenant → 403
            logger.warning(
                f"Session ownership denied: session={session_id} user={user_id} tenant={tenant_id}"
            )
            raise HTTPException(
                status_code=403,
                detail="You do not have access to this session.",
            )
        # ownership is True (same user+tenant) or None (new session) — both OK

    # 2. Semantic Cache Check (Fast Path)
    # Also captures the query embedding to reuse in the retriever (avoids duplicate embed call).
    cached_ans, query_embedding = await cache.get_cached_response_with_embedding(
        req.message, tenant_id=tenant_id
    )

    if cached_ans:
        logger.info(f"Cache hit for session {session_id}")

        # Generator for cached response
        async def stream_cache():
            yield json.dumps({
                "type": "answer",
                "content": cached_ans,
                "session_id": session_id
            }) + "\n"

        # Async Background: Log interaction even if cached
        background_tasks.add_task(
            memory.add_message, session_id, "user", req.message, user_id, tenant_id
        )
        background_tasks.add_task(
            memory.add_message, session_id, "assistant", cached_ans, user_id, tenant_id
        )
        background_tasks.add_task(_upsert_thread_safe, tenant_id, user_id, session_id, req.message)

        return StreamingResponse(stream_cache(), media_type="application/x-ndjson")

    # 3. Load Conversation History + Long-Term Memories (in parallel)
    history_objs, memory_objs = await asyncio.gather(
        memory.get_history(session_id, limit=6, user_id=user_id, tenant_id=tenant_id),
        memory.get_user_memories(user_id, tenant_id),
    )
    history_dicts = [
        {"role": msg.role, "content": msg.content} for msg in history_objs
    ]
    # Append current user message
    history_dicts.append({"role": "user", "content": req.message})
    user_memories = [
        f"[{m.memory_type}] {m.content}" for m in memory_objs
    ]

    # 4. Initialize Agent State (LangGraph)
    initial_state = AgentState(
        messages=history_dicts,
        current_query=req.message,
        documents=[],
        plan=[],
        action="",
        tool_name="",
        tool_input="",
        tool_result="",
        iteration_count=0,
        plan_steps=[],
        current_step_index=-1,
        step_results=[],
        eval_score=0,
        eval_reasoning="",
        retry_count=0,
        user_memories=user_memories,
        query_embedding=query_embedding,  # Reuse embedding from cache check
        context_layers="",  # Populated by context_enricher node (if enabled)
        data_query_sql="",
        data_query_result="",
        data_query_error="",
        data_query_time_ms=0,
    )

    # 5. Define Generator for Streaming Response
    async def event_generator() -> AsyncGenerator[str, None]:
        final_answer = ""

        try:
            # Run the LangGraph
            # Pass tenant context in 'configurable' so agent nodes can use it
            # (e.g. retriever node can filter Qdrant/Neo4j by tenant_id)
            async for event in agent_app.astream(
                initial_state,
                config={
                    "configurable": {
                        "llm": llm,
                        "user_id": user_id,
                        "tenant_id": tenant_id,
                    }
                }
            ):

                # event is a dict like {'retriever': {...state updates...}}
                node_name = list(event.keys())[0]
                node_data = event[node_name]

                # Emit Status Update
                yield json.dumps({
                    "type": "status",
                    "node": node_name,
                    "session_id": session_id,
                    "info": f"Completed step: {node_name}"
                }) + "\n"

                # Stream tool execution results
                if node_name == "tool_node":
                    tool_result = node_data.get("tool_result", "")
                    yield json.dumps({
                        "type": "tool_result",
                        "tool_name": node_data.get("tool_name", ""),
                        "content": tool_result[:500],
                        "session_id": session_id,
                    }) + "\n"

                # Stream evaluation results
                if node_name == "evaluator":
                    yield json.dumps({
                        "type": "evaluation",
                        "score": node_data.get("eval_score", 0),
                        "reasoning": node_data.get("eval_reasoning", ""),
                        "session_id": session_id,
                    }) + "\n"

                # Stream retry notification
                if node_name == "retry":
                    yield json.dumps({
                        "type": "status",
                        "node": "retry",
                        "session_id": session_id,
                        "info": "Answer quality below threshold, retrying with refined query...",
                    }) + "\n"

                # Stream multi-step progress
                if node_name == "step_advance":
                    yield json.dumps({
                        "type": "step_progress",
                        "current_step": node_data.get("current_step_index", 0),
                        "session_id": session_id,
                    }) + "\n"

                # Stream retrieved images to frontend (multimodal)
                if node_name == "retriever":
                    docs = node_data.get("documents", [])
                    image_docs = [
                        d for d in docs
                        if isinstance(d, dict) and d.get("type") == "image"
                    ]
                    if image_docs:
                        yield json.dumps({
                            "type": "context_images",
                            "images": [
                                {
                                    "url": d.get("url", ""),
                                    "caption": d.get("caption", ""),
                                    "filename": d.get("filename", ""),
                                }
                                for d in image_docs
                            ],
                            "session_id": session_id,
                        }) + "\n"

                # Stream context layers to frontend (business context, glossary)
                if node_name == "context_enricher":
                    ctx_layers = node_data.get("context_layers", "")
                    if ctx_layers:
                        yield json.dumps({
                            "type": "context_layers",
                            "content": ctx_layers,
                            "session_id": session_id,
                        }) + "\n"

                # Stream data analytics results
                if node_name == "data_analytics":
                    sql = node_data.get("data_query_sql", "")
                    time_ms = node_data.get("data_query_time_ms", 0)
                    result_json = node_data.get("data_query_result", "")
                    error = node_data.get("data_query_error", "")

                    logger.info(
                        "data_analytics event: sql=%d chars, result=%d chars, error=%s",
                        len(sql), len(result_json), error or "none",
                    )

                    if sql:
                        yield json.dumps({
                            "type": "sql_query",
                            "sql": sql,
                            "time_ms": time_ms,
                            "session_id": session_id,
                        }) + "\n"

                    if result_json:
                        try:
                            from app.analytics.formatter import (
                                format_as_table_html, suggest_chart_spec,
                            )
                            result_data = json.loads(result_json)
                            chart_spec = suggest_chart_spec(
                                result_data["columns"],
                                result_data["rows"],
                                req.message,
                            )
                            yield json.dumps({
                                "type": "data_result",
                                "columns": result_data["columns"],
                                "rows": result_data["rows"][:50],
                                "row_count": result_data["row_count"],
                                "table_html": format_as_table_html(
                                    result_data["columns"], result_data["rows"]
                                ),
                                "chart_spec": chart_spec,
                                "session_id": session_id,
                            }) + "\n"
                        except Exception as fmt_err:
                            logger.error("Data result formatting error: %s", fmt_err, exc_info=True)

                    if error:
                        yield json.dumps({
                            "type": "data_error",
                            "content": error,
                            "session_id": session_id,
                        }) + "\n"

                # Capture Final Answer from Responder Node
                if node_name == "responder":
                    # The responder node appends the final AI message to state['messages']
                    if "messages" in node_data and node_data["messages"]:
                        ai_msg = node_data["messages"][-1]
                        final_answer = ai_msg.get("content", "")

                        # Stream the chunk
                        yield json.dumps({
                            "type": "answer",
                            "content": final_answer,
                            "session_id": session_id
                        }) + "\n"

            # 6. Post-Processing — persist and cache after stream completes
            if final_answer:
                try:
                    await asyncio.gather(
                        memory.add_message(session_id, "user", req.message, user_id, tenant_id),
                        memory.add_message(session_id, "assistant", final_answer, user_id, tenant_id),
                        cache.set_cached_response(req.message, final_answer, tenant_id=tenant_id),
                        _upsert_thread_safe(tenant_id, user_id, session_id, req.message),
                        return_exceptions=True,
                    )
                except Exception as post_err:
                    logger.error(f"Post-processing error: {post_err}", exc_info=True)

                # Extract long-term memories in background (non-blocking, best-effort)
                async def _extract_memories():
                    try:
                        from app.memory.postgres import extract_and_store_memories
                        await extract_and_store_memories(
                            req.message, final_answer, user_id, tenant_id
                        )
                    except Exception as mem_err:
                        logger.error(f"Memory extraction error: {mem_err}", exc_info=True)

                asyncio.create_task(_extract_memories())

        except Exception as e:
            logger.error(f"Error in chat stream: {e}", exc_info=True)
            yield json.dumps({
                "type": "error",
                "content": "An internal error occurred."
            }) + "\n"

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")
