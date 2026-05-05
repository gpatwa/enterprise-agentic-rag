# services/api/main.py
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app.agents.nodes.retriever import set_clients as set_retriever_clients
from app.cache.redis import redis_client
from app.cache.semantic import set_vectordb_client as set_semantic_vectordb
from app.clients.graphdb.factory import create_graphdb_client
from app.clients.ray_embed import embed_client
from app.clients.ray_llm import llm_client
from app.clients.reranker.factory import create_reranker_client
from app.clients.secrets.factory import create_secrets_client
from app.clients.storage.factory import create_storage_client
from app.clients.vectordb.factory import create_vectordb_client
from app.config import settings
from app.routes import audit as audit_routes
from app.routes import auth, chat, context, documents, health, home, privacy, system, upload
from app.routes import mcp as mcp_routes
from app.routes import sources as sources_routes
from app.routes import threads as threads_routes
from app.routes.health import set_clients as set_health_clients

logger = logging.getLogger(__name__)

# Create VectorDB, GraphDB, Secrets, and Reranker clients via provider factories
vectordb_client = create_vectordb_client(settings.VECTORDB_PROVIDER)
graphdb_client = create_graphdb_client(settings.GRAPHDB_PROVIDER)
secrets_client = create_secrets_client(
    settings.SECRETS_PROVIDER,
    region=settings.AWS_REGION,
    prefix=settings.SECRETS_PREFIX,
    vault_url=settings.AZURE_KEY_VAULT_URL,
)
reranker_client = create_reranker_client(
    settings.RERANKER_PROVIDER,
    score_threshold=settings.RERANKER_SCORE_THRESHOLD,
)

# Storage client (for presigned download URLs — used by multimodal retriever)
storage_client = create_storage_client(settings.STORAGE_PROVIDER)

# Gemini embed client (for multimodal collection queries)
gemini_embed_client = None
if settings.MULTIMODAL_ENABLED:
    try:
        from app.clients.gemini_embed import GeminiEmbedClient
        gemini_embed_client = GeminiEmbedClient()
    except ImportError as e:
        logger.warning(f"Could not import GeminiEmbedClient: {e}")
        gemini_embed_client = None


async def _inject_secrets_from_vault():
    """
    Fetch sensitive values from Key Vault / Secrets Manager and inject
    them into settings *before* any database client is initialised.

    This runs only when SECRETS_PROVIDER is not "env".  When using the
    "env" provider, secrets are already present as environment variables
    (injected via K8s Secret or .env file).
    """
    if settings.SECRETS_PROVIDER == "env":
        logger.info("Secrets provider: env — secrets loaded from environment")
        return

    logger.info(f"Secrets provider: {settings.SECRETS_PROVIDER} — fetching from vault")

    # Map of setting attribute -> vault secret name
    secret_map = {
        "DB_PASSWORD":    "db-password",
        "JWT_SECRET_KEY": "jwt-secret-key",
        "NEO4J_PASSWORD": "neo4j-password",
        "REDIS_PASSWORD": "redis-primary-key",
        "OPENAI_API_KEY": "openai-api-key",
        "GOOGLE_API_KEY": "gemini-api-key",
        "TAVILY_API_KEY": "tavily-api-key",
    }

    for attr, vault_key in secret_map.items():
        current = getattr(settings, attr, None)
        if current:
            # Already set via env var — don't overwrite
            continue
        value = await secrets_client.get_secret(vault_key)
        if value:
            # Inject into the settings singleton (bypass frozen validation)
            object.__setattr__(settings, attr, value)
            logger.info(f"  Injected {attr} from vault")
        else:
            logger.warning(f"  Secret '{vault_key}' not found in vault for {attr}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Centralized Resource Management.

    Order of operations:
      1. Fetch secrets from Key Vault (if configured)
      2. Initialise database engine (using injected secrets)
      3. Connect all clients
      4. Wire up route dependencies
    """
    # 1. Inject secrets from vault BEFORE initialising DB connections
    await _inject_secrets_from_vault()

    # 2. Initialise Postgres engine (now that DB_PASSWORD is available)
    from app.memory.postgres import Base, init_engine
    init_engine()
    # Auto-create tables (chat_history, user_memories) if they don't exist
    from app.memory.postgres import engine as db_engine
    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database engine initialised, tables verified")

    # 3. Connect core clients
    await redis_client.connect()
    try:
        await llm_client.start()
    except Exception as e:
        logger.warning(f"LLM client init skipped: {e}")
    try:
        await embed_client.start()
    except Exception as e:
        logger.warning(f"Embed client init skipped: {e}")

    # Abstracted DB clients (VectorDB + GraphDB)
    await vectordb_client.connect()
    await graphdb_client.connect()

    # Re-ranker client
    try:
        await reranker_client.start()
    except Exception as e:
        logger.warning(f"Reranker client init skipped: {e}")

    # Multimodal: init Gemini embed client + create multimodal Qdrant collection
    if gemini_embed_client:
        try:
            await gemini_embed_client.start()
            await vectordb_client.create_collection(
                settings.MULTIMODAL_COLLECTION,
                vector_size=settings.GEMINI_EMBED_DIMENSIONS,
            )
            logger.info(
                f"Multimodal enabled: collection={settings.MULTIMODAL_COLLECTION}, "
                f"dims={settings.GEMINI_EMBED_DIMENSIONS}"
            )
        except Exception as e:
            logger.warning(f"Multimodal init skipped: {e}")

    # 4. Inject abstracted clients into modules that need them
    set_retriever_clients(
        vectordb_client, graphdb_client, reranker_client,
        storage=storage_client, gemini_embed=gemini_embed_client,
    )
    set_semantic_vectordb(vectordb_client)
    set_health_clients(vectordb_client, graphdb_client)

    # 5. Context Layers — init assembler if enabled
    if settings.CONTEXT_LAYERS_ENABLED:
        from app.agents.nodes.context_enricher import set_assembler
        from app.context.assembler import ContextAssembler
        set_assembler(ContextAssembler())
        logger.info("Context layers enabled — assembler initialized")

    # 6. Data Analytics — init engine if enabled
    if settings.DATA_ANALYTICS_ENABLED:
        from app.agents.nodes.data_analytics import set_analytics_llm
        from app.analytics.engine import init_analytics_engine
        init_analytics_engine()
        set_analytics_llm(llm_client)
        logger.info("Data analytics enabled — engine initialized")

    # Load per-tenant configurations
    from app.tenants.registry import tenant_registry
    await tenant_registry.load(source=settings.TENANT_CONFIG_SOURCE)

    # Initialize JWKS fetcher for external IdP (Auth0, Azure AD, Cognito)
    if settings.AUTH_PROVIDER != "local" and settings.JWT_JWKS_URL:
        from app.auth.jwks import init_jwks_fetcher
        await init_jwks_fetcher(settings.JWT_JWKS_URL)
        logger.info(f"JWKS fetcher initialised for {settings.AUTH_PROVIDER}")

    # Wire up OpenTelemetry observability (tracing + auto-instrumentation)
    try:
        from app.observability import setup_observability
        setup_observability(app)
        logger.info("Observability instrumented")
    except Exception as e:
        logger.warning(f"Observability setup skipped (optional deps missing): {e}")

    # MCP — Tier-1 SaaS connectors. Lazy: stays off unless MCP_ENABLED.
    # If the master key isn't reachable from the vault, log loudly but
    # don't crash boot — we don't want a missing optional dep to take
    # down the whole API.
    if settings.MCP_ENABLED:
        try:
            from app.mcp.crypto import init_cipher
            from app.mcp.manager import mcp_manager
            from app.mcp.process_pool import MCPProcessPool

            mcp_key = settings.MCP_ENCRYPTION_KEY
            if not mcp_key:
                # Try the secrets vault (matches the rest of the secret-injection style)
                mcp_key = await secrets_client.get_secret("MCP_ENCRYPTION_KEY")
            if not mcp_key:
                logger.warning(
                    "MCP_ENABLED but no MCP_ENCRYPTION_KEY available — MCP stays disabled"
                )
            else:
                init_cipher(mcp_key)
                pool = MCPProcessPool(
                    max_processes=settings.MCP_MAX_PROCESSES,
                    idle_seconds=settings.MCP_IDLE_REAP_SECONDS,
                    tool_timeout_seconds=settings.MCP_TOOL_TIMEOUT_SECONDS,
                )
                pool.start()
                mcp_manager.configure(
                    enabled=True,
                    pool=pool,
                    tool_timeout_seconds=settings.MCP_TOOL_TIMEOUT_SECONDS,
                )
                logger.info(
                    "MCP enabled — pool max=%d idle=%ds timeout=%ds",
                    settings.MCP_MAX_PROCESSES,
                    settings.MCP_IDLE_REAP_SECONDS,
                    settings.MCP_TOOL_TIMEOUT_SECONDS,
                )
        except Exception as e:
            logger.warning("MCP init failed (continuing without MCP): %s", e)

    yield

    # Shutdown
    logger.info("Closing clients...")
    # Drain MCP pool first so its child subprocesses don't outlive their parents.
    try:
        from app.mcp.manager import mcp_manager as _mgr
        await _mgr.shutdown()
    except Exception as e:
        logger.warning(f"MCP shutdown error (non-fatal): {e}")
    await secrets_client.close()
    await vectordb_client.close()
    await graphdb_client.close()
    await reranker_client.close()
    await redis_client.close()
    await llm_client.close()
    await embed_client.close()
    if gemini_embed_client:
        await gemini_embed_client.close()

# FastAPI Application
app = FastAPI(title="Enterprise RAG Platform", version="1.0.0", lifespan=lifespan)

# CORS Middleware — explicit allowlist required outside dev/staging.
# Refuses to start in prod with wildcard, matching enterprise security review.
origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
if settings.ENV == "prod" and (not origins or origins == ["*"]):
    raise RuntimeError(
        "CORS_ORIGINS must be an explicit allowlist in production "
        "(wildcard '*' is rejected). Set e.g. "
        "CORS_ORIGINS='https://app.compass.ai,https://staging.compass.ai'."
    )
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    # Prefer explicit method/header allowlists in prod; '*' is fine in dev/staging.
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-Tenant-ID"],
    max_age=600,
)

# Include Routes
app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(chat.router, prefix="/api/v1/chat", tags=["Chat"])
app.include_router(upload.router, prefix="/api/v1/upload", tags=["Upload"])
app.include_router(health.router, prefix="/health", tags=["Health"])
app.include_router(system.router, prefix="/api/v1/system", tags=["System"])
app.include_router(documents.router, prefix="/api/v1/documents", tags=["Documents"])
app.include_router(context.router, prefix="/api/v1/context", tags=["Context"])
app.include_router(home.router, prefix="/api/v1/home", tags=["Home"])
app.include_router(threads_routes.router, prefix="/api/v1", tags=["Threads"])
app.include_router(sources_routes.router, prefix="/api/v1/sources", tags=["Sources"])
app.include_router(audit_routes.router, prefix="/api/v1/audit", tags=["Audit"])
app.include_router(privacy.router, prefix="/api/v1/privacy", tags=["Privacy"])
app.include_router(mcp_routes.router, prefix="/api/v1/mcp", tags=["MCP"])

# Serve Chat UI at root "/"
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
SPA_DIST_DIR = os.path.join(os.path.dirname(__file__), "frontend", "dist")
SPA_AVAILABLE = os.path.isdir(SPA_DIST_DIR) and os.path.isfile(os.path.join(SPA_DIST_DIR, "index.html"))


# Mount the new SPA's static assets (always available when built)
if SPA_AVAILABLE:
    app.mount(
        "/assets",
        StaticFiles(directory=os.path.join(SPA_DIST_DIR, "assets")),
        name="spa-assets",
    )

# Legacy v1 chat UI — always available at /v1
@app.get("/v1", include_in_schema=False)
@app.get("/v1/", include_in_schema=False)
async def serve_legacy_ui():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/", include_in_schema=False)
async def serve_ui():
    """
    Serve the new Compass SPA when NEW_UI_ENABLED=true and the build exists,
    otherwise fall back to the legacy v1 UI. The legacy UI stays reachable
    at /v1 either way.
    """
    if settings.NEW_UI_ENABLED and SPA_AVAILABLE:
        return FileResponse(os.path.join(SPA_DIST_DIR, "index.html"))
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


# SPA client-side routes — return index.html for any unknown path under the SPA
# (so /threads, /saved, /solutions/finance, etc. all hit the React Router).
@app.get("/{spa_path:path}", include_in_schema=False)
async def serve_spa_route(spa_path: str):
    if not (settings.NEW_UI_ENABLED and SPA_AVAILABLE):
        return Response(status_code=404)
    # Don't shadow API or asset paths
    if spa_path.startswith(("api/", "auth/", "health/", "assets/", "v1/", "static/")):
        return Response(status_code=404)
    # Serve actual files if present
    candidate = os.path.join(SPA_DIST_DIR, spa_path)
    if os.path.isfile(candidate):
        return FileResponse(candidate)
    # Otherwise, hand off to React Router
    return FileResponse(os.path.join(SPA_DIST_DIR, "index.html"))


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    if SPA_AVAILABLE and os.path.isfile(os.path.join(SPA_DIST_DIR, "compass-favicon.svg")):
        return FileResponse(os.path.join(SPA_DIST_DIR, "compass-favicon.svg"))
    return Response(status_code=204)

if __name__ == "__main__":
    import uvicorn
    # In production, this is run via Gunicorn/Uvicorn in Docker
    uvicorn.run(app, host="0.0.0.0", port=8000)
