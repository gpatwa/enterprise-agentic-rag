# Alpha — Ops Runbook

Internal-alpha operations: feedback channel, error tracking, uptime
monitoring. Pair with `docs/ALPHA_LOOM_SCRIPT.md` for the user-facing
walkthrough.

---

## 1. Feedback (B.1)

The app has a floating "Feedback" button bottom-right on every in-app
page (mounted in `AppShell`, hidden by `VITE_FEEDBACK_DISABLED=1`).
Submissions POST to `/api/v1/feedback` which:

1. Validates the payload (1–4000 char message, category in {bug, idea,
   comment}).
2. Audit-logs `event_type="feedback.submitted"` with the user, tenant,
   page URL.
3. Best-effort relays to a Slack incoming webhook.

### One-time setup

1. Create a Slack channel — `#compass-alpha` is the convention.
2. In your Slack workspace: **Apps → Incoming Webhooks → Add to Slack
   → choose channel → Add**. Copy the webhook URL.
3. Set the env var on the API pod / docker-compose / your deploy:
   ```
   FEEDBACK_SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T.../B.../...
   ```
4. Restart the API. From any in-app page, click the Feedback button →
   send a test → confirm it shows up in Slack.

### What stakeholders see

- 🐛 / 💡 / 💬 emoji header per category
- The message body, with `@channel` / `@here` / `@everyone` rendered as
  literal text (not as Slack mentions — server-side stripping)
- A context line with a clickable link to the page they were on, plus
  `user`, `tenant`, `role`

### Operating without a webhook

If `FEEDBACK_SLACK_WEBHOOK_URL` is unset (e.g. local dev, or a deploy
where Slack is offline), the endpoint still returns 200 and the
submission is captured in the audit log. Query `audit_log` filtered to
`event_type='feedback.submitted'` to read it back.

```sql
SELECT created_at, user_id, payload_summary, extra->>'category' AS category, extra->>'current_url' AS url
FROM audit_log
WHERE event_type = 'feedback.submitted'
ORDER BY created_at DESC
LIMIT 50;
```

### Rotating the webhook

If the webhook is leaked or the channel changes:
1. Revoke the old webhook in Slack (Apps → Incoming Webhooks → ⋯ → Disable).
2. Create a new one and update `FEEDBACK_SLACK_WEBHOOK_URL`.
3. Restart the API.

No data migration needed — historical audit rows reference the
submission, not the webhook.

---

## 2. Error tracking with Sentry (B.3)

Both the FastAPI backend and the React frontend ship with optional
Sentry integration. Both **no-op cleanly when DSN is unset** so a deploy
without a Sentry project boots normally.

### Setup

1. **Create a Sentry project** at https://sentry.io. Pick:
   - "FastAPI" platform → get backend DSN
   - "React" platform → get frontend DSN
   - These can be the *same project* (one DSN works for both, but
     separate projects are easier to triage).

2. **Backend**: install + set env var.
   ```bash
   # In the API container / pod's requirements.txt — uncomment:
   #   sentry-sdk[fastapi]>=2.0,<3.0
   pip install 'sentry-sdk[fastapi]>=2.0,<3.0'

   # Then set:
   SENTRY_DSN=https://abc@o123.ingest.sentry.io/456
   SENTRY_ENVIRONMENT=alpha
   SENTRY_RELEASE=$(git rev-parse --short HEAD)   # set in CI
   SENTRY_TRACES_SAMPLE_RATE=0.0                  # 0.0 = errors only; 0.1 = 10% perf traces
   ```

3. **Frontend**: set the build-time env var.
   ```bash
   # In .env.local or CI:
   VITE_SENTRY_DSN=https://abc@o123.ingest.sentry.io/456
   VITE_SENTRY_ENVIRONMENT=alpha
   VITE_SENTRY_RELEASE=$(git rev-parse --short HEAD)
   ```

   The frontend pulls these at `npm run build` time and bakes them into
   the bundle. Rebuilding is needed to change them.

### What's captured

- **Backend**: every uncaught exception in a route. Auto-instruments
  FastAPI request handlers, SQLAlchemy queries, async tasks. Request
  bodies and cookies are NOT shipped (`send_default_pii=False`).
- **Frontend**: React render-phase errors via `Sentry.ErrorBoundary` at
  the app root + uncaught promise rejections. URLs in events have query
  strings redacted (`?[redacted]`) before send to keep tokens out.

### Cost (free tier)

Sentry's Developer plan gives you 5,000 errors/month + 10,000 perf
traces/month. The traces sample rate defaults to 0 — set it to 0.1 once
you want to see latency budgets.

### Rotating the DSN

Sentry DSNs are project-scoped and not, strictly, secrets — anyone who
has the DSN can submit events but can't read them. Still, treat them
like API keys:

1. Sentry → Project → Settings → Client Keys → ⋯ → Disable
2. Create a new key, update env var, redeploy.

---

## 3. Uptime monitoring (B.4)

### Endpoints (already in the app)

| Path | When to use |
|---|---|
| `GET /health/liveness` | Just checks the process is up. Use for K8s liveness. |
| `GET /health/readiness` | Probes Postgres + Redis + vector + graph. Returns 200 if all up, 503 if any down. **Use this for external uptime checks.** |
| `GET /health/deep` | Operator-facing — per-dependency status + latency. Don't poll this every minute; it's expensive. |

### Recommended: UptimeRobot (free)

Why: 50 monitors free, 5-minute interval, native Slack integration.

1. Sign up at https://uptimerobot.com (free).
2. Add a HTTP(s) monitor:
   - URL: `https://<your-alpha-domain>/health/readiness`
   - Friendly name: `Compass alpha — readiness`
   - Interval: 5 minutes
   - Alerts: enable Slack via UptimeRobot → My Settings → Alert
     Contacts → Add → Slack. Drop in the `#compass-alpha` webhook.
3. Recommended thresholds:
   - "Down" alert when 2 consecutive checks fail (10 min).
   - Public status page (free) — Compass team can subscribe to it.

### Self-hosted alternative

If you'd rather not depend on a SaaS uptime service, there's a small
script `scripts/uptime_watcher.py` that polls `/health/readiness` and
posts to a Slack webhook on transitions. Run from cron every 5
minutes. Suits a dev box or a tiny VM.

```bash
# Once per minute:
* * * * * /usr/bin/env COMPASS_URL=https://alpha.compass.example.com \
   SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T/.../... \
   /usr/bin/python3 /opt/scalable-rag-pipeline/scripts/uptime_watcher.py >> /var/log/compass-uptime.log 2>&1
```

The script writes its previous-status to `/tmp/compass-uptime-state`
(configurable via `STATE_FILE` env) and only Slack-pings on transitions
(up→down, down→up). No spam.

---

## Putting it together

For a fresh alpha deploy, the full one-time ops setup is:

```
┌─────────────────────────────────────────────────────────────┐
│  1. Create Slack channel       #compass-alpha               │
│  2. Slack incoming webhook  →  FEEDBACK_SLACK_WEBHOOK_URL   │
│  3. Sentry project (×2)     →  SENTRY_DSN + VITE_SENTRY_DSN │
│  4. UptimeRobot monitor     →  /health/readiness, 5-min     │
│     (or scripts/uptime_watcher.py from cron)                │
└─────────────────────────────────────────────────────────────┘
```

After that:
- Errors → Sentry alerts you.
- Downtime → UptimeRobot alerts you.
- User feedback → Slack channel.
- Audit trail → `audit_log` table for forensics.

---

## Quick reference — env vars

| Var | Layer | Required for | Default |
|---|---|---|---|
| `FEEDBACK_SLACK_WEBHOOK_URL` | backend | Slack relay | unset → audit-only |
| `SENTRY_DSN` | backend | Backend error capture | unset → disabled |
| `SENTRY_ENVIRONMENT` | backend | Tag events | `ENV` value |
| `SENTRY_TRACES_SAMPLE_RATE` | backend | Performance traces | `0.0` |
| `VITE_SENTRY_DSN` | frontend (build) | Frontend error capture | unset → disabled |
| `VITE_SENTRY_ENVIRONMENT` | frontend (build) | Tag events | `alpha` (when DSN set) |
| `VITE_FEEDBACK_DISABLED` | frontend (build) | Hide widget in prod | unset → widget shown |
