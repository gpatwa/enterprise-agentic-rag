from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from app.clients.secrets.factory import create_secrets_client
from app.config import settings
from app.search.factory import create_search_provider
from app.search.indexing import SupportSearchEventProcessor
from app.search.worker import SearchIndexWorker

logger = logging.getLogger(__name__)

secrets_client = create_secrets_client(
    settings.SECRETS_PROVIDER,
    region=settings.AWS_REGION,
    prefix=settings.SECRETS_PREFIX,
    vault_url=settings.AZURE_KEY_VAULT_URL,
)


async def _inject_secrets_from_vault() -> None:
    if settings.SECRETS_PROVIDER == "env":
        return
    for attr, vault_key in {
        "DB_PASSWORD": "db-password",
        "OPENSEARCH_PASSWORD": "opensearch-password",
        "OPENSEARCH_API_KEY": "opensearch-api-key",
    }.items():
        if getattr(settings, attr, None):
            continue
        value = await secrets_client.get_secret(vault_key)
        if value:
            object.__setattr__(settings, attr, value)


async def run() -> None:
    logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
    await _inject_secrets_from_vault()

    from app.memory import postgres as pg
    from app.memory.postgres import Base, init_engine

    init_engine()
    async with pg.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    provider = create_search_provider("opensearch")
    await provider.connect()
    processor = SupportSearchEventProcessor(provider, pg.AsyncSessionLocal)
    worker = SearchIndexWorker(processor)
    worker.start(
        pg.AsyncSessionLocal,
        poll_seconds=settings.SEARCH_INDEX_WORKER_POLL_SECONDS,
        batch_size=settings.SEARCH_INDEX_WORKER_BATCH_SIZE,
        lease_seconds=settings.SEARCH_INDEX_WORKER_LEASE_SECONDS,
        retry_base_seconds=settings.SEARCH_INDEX_WORKER_RETRY_BASE_SECONDS,
        retry_max_seconds=settings.SEARCH_INDEX_WORKER_RETRY_MAX_SECONDS,
    )
    logger.info("enterprise search worker running worker_id=%s", worker.worker_id)

    try:
        await asyncio.Event().wait()
    finally:
        await worker.shutdown()
        await provider.close()
        await secrets_client.close()


if __name__ == "__main__":
    with suppress(KeyboardInterrupt):
        asyncio.run(run())
