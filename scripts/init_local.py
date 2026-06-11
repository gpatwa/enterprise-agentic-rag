#!/usr/bin/env python3
"""
One-command local environment initializer.
Usage: python scripts/init_local.py
  OR:  make init

Runs all setup steps:
  1. Postgres — creates tables (chat_history)
  2. Qdrant   — creates collections (rag_collection, semantic_cache)
  3. Neo4j    — creates fulltext index + constraints
  4. MinIO    — creates the S3 bucket
"""
import asyncio
import os
import sys

from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "services", "api"))


# ── 1. Postgres ──────────────────────────────────────────────────────────────
async def init_postgres():
    print("\n[1/4] Postgres — creating tables...")
    from services.api.app.memory.postgres import Base, init_engine

    init_engine()
    from services.api.app.memory.postgres import engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _repair_local_support_jobs_schema(conn)

    from sqlalchemy import inspect
    async with engine.connect() as conn:
        tables = await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).get_table_names()
        )
    await engine.dispose()
    print(f"  ✅ Tables: {tables}")


async def _repair_local_support_jobs_schema(conn):
    """Repair dev DBs created by ORM metadata before support_jobs migrations existed."""
    exists = await conn.scalar(text("SELECT to_regclass('public.support_jobs')"))
    if exists is None:
        return

    repair_statements = [
        "ALTER TABLE support_jobs ADD COLUMN IF NOT EXISTS cancel_requested BOOLEAN NOT NULL DEFAULT false",
        "ALTER TABLE support_jobs ADD COLUMN IF NOT EXISTS canceled_at TIMESTAMP NULL",
        "ALTER TABLE support_jobs ADD COLUMN IF NOT EXISTS retry_of_job_id VARCHAR(64) NULL",
        "ALTER TABLE support_jobs ADD COLUMN IF NOT EXISTS next_run_at TIMESTAMP NULL",
        "CREATE INDEX IF NOT EXISTS ix_support_jobs_tenant_id ON support_jobs (tenant_id)",
        "CREATE INDEX IF NOT EXISTS ix_support_jobs_job_type ON support_jobs (job_type)",
        "CREATE INDEX IF NOT EXISTS ix_support_jobs_status ON support_jobs (status)",
        (
            "CREATE INDEX IF NOT EXISTS idx_support_job_tenant_status_created "
            "ON support_jobs (tenant_id, status, created_at)"
        ),
        "CREATE INDEX IF NOT EXISTS idx_support_job_status_locked ON support_jobs (status, locked_at)",
        "CREATE INDEX IF NOT EXISTS idx_support_job_type_status ON support_jobs (job_type, status)",
    ]
    for statement in repair_statements:
        await conn.execute(text(statement))


# ── 2. Qdrant ────────────────────────────────────────────────────────────────
def _detect_embed_dim() -> int:
    """
    Auto-detect embedding dimensionality by sending a probe text
    to the configured embed endpoint (Ollama / Ray Serve).

    Falls back to 768 (nomic-embed-text default) if detection fails.
    """
    import httpx
    from services.api.app.config import settings

    print(f"  Detecting dimensions for model '{settings.EMBED_MODEL}'...")
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                settings.RAY_EMBED_ENDPOINT,
                json={"model": settings.EMBED_MODEL, "prompt": "dimension probe"},
            )
            resp.raise_for_status()
            dim = len(resp.json()["embedding"])
            print(f"  ✅ Detected dimension: {dim}")
            return dim
    except Exception as e:
        print(f"  ⚠️  Auto-detect failed ({e}), defaulting to 768")
        return 768


def init_qdrant():
    print("\n[2/4] Qdrant — creating collections...")
    from qdrant_client import QdrantClient
    from qdrant_client.http import models
    from services.api.app.config import settings

    vector_dim = _detect_embed_dim()

    client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
    existing = [c.name for c in client.get_collections().collections]

    for name in [settings.QDRANT_COLLECTION, "semantic_cache"]:
        if name in existing:
            # Check if existing collection has matching dimensions
            info = client.get_collection(name)
            existing_dim = info.config.params.vectors.size
            if existing_dim != vector_dim:
                print(f"  ⚠️  '{name}' has dim={existing_dim}, need dim={vector_dim}")
                print("      Recreating collection...")
                client.delete_collection(collection_name=name)
                client.create_collection(
                    collection_name=name,
                    vectors_config=models.VectorParams(
                        size=vector_dim,
                        distance=models.Distance.COSINE,
                    ),
                )
                print(f"  ✅ Recreated '{name}' (dim={vector_dim}, cosine)")
            else:
                print(f"  ⏭️  '{name}' already exists (dim={existing_dim})")
        else:
            client.create_collection(
                collection_name=name,
                vectors_config=models.VectorParams(
                    size=vector_dim,
                    distance=models.Distance.COSINE,
                ),
            )
            print(f"  ✅ Created '{name}' (dim={vector_dim}, cosine)")


# ── 3. Neo4j ─────────────────────────────────────────────────────────────────
def init_neo4j():
    print("\n[3/4] Neo4j — creating indexes...")
    from neo4j import GraphDatabase
    from services.api.app.config import settings

    driver = GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
    )

    with driver.session() as session:
        try:
            session.run(
                "CREATE CONSTRAINT entity_name IF NOT EXISTS "
                "FOR (e:Entity) REQUIRE e.name IS UNIQUE"
            )
            print("  ✅ Uniqueness constraint on Entity.name")
        except Exception as e:
            print(f"  ⏭️  Constraint: {e}")

        try:
            session.run(
                "CREATE FULLTEXT INDEX entity_index IF NOT EXISTS "
                "FOR (n:Entity) ON EACH [n.name]"
            )
            print("  ✅ Fulltext index 'entity_index'")
        except Exception as e:
            print(f"  ⏭️  Fulltext index: {e}")

    driver.close()


# ── 4. MinIO (S3 bucket) ─────────────────────────────────────────────────────
def init_minio():
    print("\n[4/4] MinIO — creating S3 bucket...")
    import boto3
    from botocore.exceptions import ClientError
    from services.api.app.config import settings

    if not settings.S3_ENDPOINT_URL:
        print("  ⏭️  S3_ENDPOINT_URL not set — skipping (using real AWS)")
        return

    s3 = boto3.client(
        "s3",
        endpoint_url=settings.S3_ENDPOINT_URL,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_REGION,
    )

    try:
        s3.head_bucket(Bucket=settings.S3_BUCKET_NAME)
        print(f"  ⏭️  Bucket '{settings.S3_BUCKET_NAME}' already exists")
    except ClientError:
        s3.create_bucket(Bucket=settings.S3_BUCKET_NAME)
        print(f"  ✅ Created bucket '{settings.S3_BUCKET_NAME}'")


# ── Main ──────────────────────────────────────────────────────────────────────
async def main():
    print("=" * 55)
    print("  RAG Platform — Local Environment Setup")
    print("=" * 55)

    await init_postgres()
    init_qdrant()
    init_neo4j()
    init_minio()

    print("\n" + "=" * 55)
    print("  ✅  All done!  Run `make dev` to start the API.")
    print("=" * 55)


if __name__ == "__main__":
    asyncio.run(main())
