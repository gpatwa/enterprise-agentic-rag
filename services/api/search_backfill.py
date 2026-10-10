from __future__ import annotations

import argparse
import asyncio
import json

from app.search.backfill import SOURCE_TYPES, support_search_backfill


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Queue canonical support documents for enterprise search")
    parser.add_argument("--tenant-id")
    parser.add_argument("--provider", required=True)
    parser.add_argument("--source-type", action="append", choices=SOURCE_TYPES)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--max-records", type=int)
    parser.add_argument("--dry-run", action="store_true")
    return parser


async def run(args: argparse.Namespace) -> dict:
    from app.memory import postgres as pg
    from app.memory.postgres import init_engine

    init_engine()
    async with pg.AsyncSessionLocal() as session:
        report = await support_search_backfill.run(
            session,
            tenant_id=args.tenant_id,
            provider=args.provider,
            source_types=args.source_type or SOURCE_TYPES,
            batch_size=args.batch_size,
            max_records=args.max_records,
            dry_run=args.dry_run,
        )
    if pg.engine is not None:
        await pg.engine.dispose()
    return report.as_dict()


if __name__ == "__main__":
    args = _parser().parse_args()
    print(json.dumps(asyncio.run(run(args)), sort_keys=True))
