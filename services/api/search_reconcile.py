from __future__ import annotations

import argparse
import asyncio
import json

from app.search.factory import create_search_provider


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare support source rows with an OpenSearch generation")
    parser.add_argument("--tenant-id")
    parser.add_argument("--provider", required=True, dest="source_provider")
    parser.add_argument("--index")
    return parser


async def run(args: argparse.Namespace) -> dict:
    from app.config import settings
    from app.memory import postgres as pg
    from app.memory.postgres import init_engine
    from app.search.reconcile import search_reconciler

    init_engine()
    provider = create_search_provider("opensearch")
    await provider.connect()
    try:
        async with pg.AsyncSessionLocal() as session:
            report = await search_reconciler.reconcile(
                session,
                tenant_id=args.tenant_id,
                provider=provider,
                source_provider=args.source_provider,
                index=args.index or settings.OPENSEARCH_INDEX_ALIAS,
            )
        return report.as_dict()
    finally:
        await provider.close()
        if pg.engine is not None:
            await pg.engine.dispose()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run(_parser().parse_args())), sort_keys=True))
