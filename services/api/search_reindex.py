from __future__ import annotations

import argparse
import asyncio
import json

from app.search.factory import create_search_provider


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build and gate a new enterprise search index generation")
    parser.add_argument("--tenant-id")
    parser.add_argument("--provider", required=True, dest="source_provider")
    parser.add_argument("--alias")
    parser.add_argument("--generation")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--max-mismatches", type=int, default=0)
    return parser


async def run(args: argparse.Namespace) -> dict:
    from app.config import settings
    from app.memory import postgres as pg
    from app.memory.postgres import init_engine
    from app.search.reindex import search_reindex_coordinator

    init_engine()
    provider = create_search_provider("opensearch")
    await provider.connect()
    try:
        async with pg.AsyncSessionLocal() as session:
            result = await search_reindex_coordinator.run(
                session,
                tenant_id=args.tenant_id,
                provider_name=args.source_provider,
                provider=provider,
                alias=args.alias or settings.OPENSEARCH_INDEX_ALIAS,
                generation=args.generation,
                batch_size=args.batch_size,
                max_mismatches=args.max_mismatches,
            )
        return result.as_dict()
    finally:
        await provider.close()
        if pg.engine is not None:
            await pg.engine.dispose()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run(_parser().parse_args())), sort_keys=True))
