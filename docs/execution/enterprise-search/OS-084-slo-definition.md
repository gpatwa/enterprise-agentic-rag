# OS-084 Search SLI/SLO Definition

SLIs are measured by tenant-safe aggregate labels: availability, query p95 and
p99 latency, retryable/non-retryable error rate, indexing lag, alias age,
mapping rejection rate, and ACL defense rejections. No raw query or document
content is a metric label.

Pilot targets: 99.9% successful search requests, p95 <= 750 ms, p99 <= 1500
ms, indexing lag <= 10 minutes, and zero ACL leakage. Alerts use a fast burn
window and a slow burn window, with rollback to the previous alias as the
first mitigation for relevance or mapping regressions.
