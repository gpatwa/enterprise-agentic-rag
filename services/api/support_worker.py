# services/api/support_worker.py
from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from app.clients.ray_embed import embed_client
from app.clients.secrets.factory import create_secrets_client
from app.clients.vectordb.factory import create_vectordb_client
from app.config import settings
from app.support.indexer import set_clients as set_support_index_clients
from app.support.jobs import support_job_worker

logger = logging.getLogger(__name__)

secrets_client = create_secrets_client(
    settings.SECRETS_PROVIDER,
    region=settings.AWS_REGION,
    prefix=settings.SECRETS_PREFIX,
    vault_url=settings.AZURE_KEY_VAULT_URL,
)
vectordb_client = create_vectordb_client(settings.VECTORDB_PROVIDER)


async def _inject_secrets_from_vault() -> None:
    if settings.SECRETS_PROVIDER == "env":
        return

    secret_map = {
        "DB_PASSWORD": "db-password",
        "REDIS_PASSWORD": "redis-primary-key",
        "OPENAI_API_KEY": "openai-api-key",
        "GOOGLE_API_KEY": "gemini-api-key",
    }
    for attr, vault_key in secret_map.items():
        if getattr(settings, attr, None):
            continue
        value = await secrets_client.get_secret(vault_key)
        if value:
            object.__setattr__(settings, attr, value)


async def run() -> None:
    logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
    await _inject_secrets_from_vault()

    from app.memory.postgres import Base, init_engine

    init_engine()
    from app.memory import postgres as pg

    async with pg.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await embed_client.start()
    await vectordb_client.connect()
    set_support_index_clients(vectordb_client, embed_client)

    support_job_worker.start(
        pg.AsyncSessionLocal,
        poll_seconds=settings.SUPPORT_JOB_POLL_SECONDS,
        stale_after_seconds=settings.SUPPORT_JOB_STALE_SECONDS,
    )
    logger.info("support worker running")

    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await support_job_worker.shutdown()
        await vectordb_client.close()
        await embed_client.close()
        await secrets_client.close()


if __name__ == "__main__":
    with suppress(KeyboardInterrupt):
        asyncio.run(run())
