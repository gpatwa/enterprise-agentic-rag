# OS-058 Search Load Test Plan

The local load gate uses the golden corpus and synthetic tenant-safe requests.
It measures cold-cache and warm-cache query p50/p95/p99, successful queries
per second, provider errors, indexing throughput, recovery time after a
connection interruption, and ACL filter recall.

The test must run in three bounded phases: 10 minutes warm-up, 15 minutes
steady state, and 5 minutes recovery. Results are stored as aggregate numbers
and request class labels only. No query text, ticket body, or vector is logged.

Release thresholds are p95 query latency <= 750 ms at the agreed pilot load,
zero cross-tenant results, and successful recovery without an alias pointing to
an incomplete generation. A live cluster run remains an operational evidence
item, not an Azure deployment performed by this repository change.
