"""The raw documents of an ingestion run as a Ray Dataset with ``path`` and ``bytes`` columns."""

from __future__ import annotations

from typing import Any, Mapping

from pipelines.ingestion.options import int_env


def read_source(ray_data: Any, env: Mapping[str, str], bucket_name: str, prefix: str):
    """``INGEST_SOURCE=s3`` (default) reads ``s3://bucket/prefix`` with Ray Data. ``INGEST_SOURCE=azure_blob`` treats
    ``bucket_name`` as the container, lists the blobs under ``prefix`` and fetches them on the workers with the pod's
    workload identity (no storage key)."""
    source = (env.get("INGEST_SOURCE") or "s3").strip().lower()
    if source == "s3":
        return ray_data.read_binary_files(paths=f"s3://{bucket_name}/{prefix}", include_paths=True)
    if source == "azure_blob":
        from pipelines.ingestion.loaders.azure_blob import AzureBlobFetcher, list_blob_paths, source_paths

        account = env["AZURE_STORAGE_ACCOUNT_NAME"]
        paths = list_blob_paths(account, bucket_name, prefix)
        if not paths:
            raise SystemExit(f"No blobs under az://{bucket_name}/{prefix}")
        print(f"Found {len(paths)} blob(s) under az://{bucket_name}/{prefix}")
        return ray_data.from_items(source_paths(paths)).map_batches(
            AzureBlobFetcher, concurrency=int_env(env, "INGEST_FETCH_CONCURRENCY", 2), batch_size=4
        )
    raise ValueError(f"INGEST_SOURCE must be 's3' or 'azure_blob', got {source!r}")
