# OpenSearch Operations Runbook

## Yellow or red cluster

Check cluster health, node capacity, disk watermark, pending tasks, and recent
mapping errors. Stop canary traffic, preserve the active alias, and restore the
previous generation if query correctness or authorization is uncertain.

## Throttling or latency

Reduce canary percentage, inspect p95/p99 and retry counts, then bound worker
concurrency. Do not increase retries without checking duplicate indexing and
cost impact.

## Mapping rejection or stale index

Pause the indexing worker, inspect the compatibility report, create a new
generation, run bounded reconciliation, and swap the alias only after the
reconciliation is green. The prior generation is the rollback target.

## Data deletion

Delete the canonical tenant data first, enqueue index tombstones, run the
bounded worker, verify zero tenant documents, and record the reconciliation
evidence. Expired interaction events are deleted separately by retention jobs.
