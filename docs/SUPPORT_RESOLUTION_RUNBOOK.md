# Support Resolution Intelligence Runbook

This runbook covers the first production wave for Customer Support Resolution Intelligence: Zendesk/Intercom ingestion, durable sync/index jobs, worker deployment, and operator recovery.

## Production Shape

- API pods serve the customer UI and REST contract.
- `api-support-worker` pods execute durable support sync/index jobs from the `support_jobs` table.
- API pods should set `SUPPORT_JOB_WORKER_ENABLED=false` in staging/prod so work is not duplicated inside request-serving pods.
- Worker pods should run `python support_worker.py` with `SUPPORT_JOB_WORKER_ENABLED=true`.
- Jobs are tenant-scoped and move through `queued`, `running`, `succeeded`, `failed`, or `canceled`.
- Failed jobs are the dead-letter queue until an operator retries them.

## Required Migration

Run migrations before rolling API or worker pods:

```bash
cd services/api
DATABASE_URL="$DATABASE_URL" alembic upgrade head
```

Staging and production Helm values enable the migration hook, so normal deploys run this automatically before API/worker rollout:

```bash
helm upgrade --install api deploy/helm/api \
  -f deploy/helm/api/values-azure.yaml \
  -f deploy/helm/api/values-staging.yaml \
  --set image.repository=$ACR_REGISTRY/rag-backend-api \
  --set image.tag=$IMAGE_TAG \
  --wait --timeout 180s
```

Then verify rollout:

```bash
kubectl rollout status deployment/api-deployment --timeout=180s
kubectl rollout status deployment/api-support-worker --timeout=180s
```

## Connector Setup

Recommended SaaS mode is Nango because customer OAuth credentials and refresh tokens stay outside Compass.

Required secrets for Nango mode:

```bash
NANGO_SECRET_KEY=nango_sk_...
NANGO_PROVIDER_CONFIG_KEY_ZENDESK=zendesk
NANGO_PROVIDER_CONFIG_KEY_INTERCOM=intercom
```

Per tenant, enable the connection through the support-integrations API:

```bash
curl -X POST "$BASE_URL/api/v1/support-integrations/connections" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "zendesk",
    "auth_mode": "nango",
    "nango_connection_id": "tenant-zendesk-connection",
    "provider_config_key": "zendesk"
  }'
```

Direct connectors are for local/private deployments only:

```bash
ZENDESK_SUBDOMAIN=your-subdomain
ZENDESK_EMAIL=admin@example.com
ZENDESK_API_TOKEN=...
INTERCOM_ACCESS_TOKEN=...
```

## Job Operations

Start a sync/index job:

```bash
curl -X POST "$BASE_URL/api/v1/support/jobs/sync-index" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"providers":["zendesk","intercom"],"limit":100,"seed_demo":false}'
```

List and inspect jobs:

```bash
curl "$BASE_URL/api/v1/support/jobs?limit=20" -H "Authorization: Bearer $TOKEN"
curl "$BASE_URL/api/v1/support/jobs/$JOB_ID" -H "Authorization: Bearer $TOKEN"
curl "$BASE_URL/api/v1/support/jobs/summary" -H "Authorization: Bearer $TOKEN"
```

Cancel a queued/running job:

```bash
curl -X POST "$BASE_URL/api/v1/support/jobs/$JOB_ID/cancel" -H "Authorization: Bearer $TOKEN"
```

Retry a failed/canceled job:

```bash
curl -X POST "$BASE_URL/api/v1/support/jobs/$JOB_ID/retry" -H "Authorization: Bearer $TOKEN"
```

## Stuck Job Recovery

The worker reclaims stale `running` jobs when `locked_at` is older than `SUPPORT_JOB_STALE_SECONDS`.

- If attempts remain, the job is requeued with `current_step=requeued_after_stale_lock`.
- If attempts are exhausted, the job becomes `failed` with `current_step=dead_lettered_after_stale_lock`.
- If cancellation was requested, the job becomes `canceled`.

Default retry controls:

```bash
SUPPORT_JOB_STALE_SECONDS=900
SUPPORT_JOB_MAX_ATTEMPTS=3
SUPPORT_JOB_RETRY_BASE_SECONDS=30
SUPPORT_JOB_RETRY_MAX_SECONDS=300
```

## Metrics And Alerts

Scrape process metrics:

```bash
curl "$BASE_URL/health/metrics"
```

Poll tenant job health:

```bash
curl "$BASE_URL/api/v1/support/jobs/summary" -H "Authorization: Bearer $TOKEN"
```

Initial alert policy:

- Page if `stale_running_count > 0` for 15 minutes.
- Page if `dead_letter_count` increases for a production tenant.
- Ticket if `counts.failed / terminal_count > 5%` over a business day.
- Ticket if `api-support-worker` has zero ready replicas for 5 minutes.
- Ticket if connector health is `error` after credential rotation.

## Rollback

Rollback API/worker code first, not the database migration:

```bash
helm rollback api
kubectl rollout status deployment/api-deployment --timeout=180s
kubectl rollout status deployment/api-support-worker --timeout=180s
```

Do not downgrade the `support_jobs` migration in production unless the table is empty and there are no active customer syncs.
