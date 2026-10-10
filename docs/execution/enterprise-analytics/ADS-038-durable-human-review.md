# ADS-038: Durable Human Review

Status: **Complete**
Milestone: M3
Depends on: ADS-005, ADS-037

## Deliverable

Migration `0003_durable_analytics_reviews` adds tenant-, purpose-, run-,
fingerprint-, requester-, expiry-, revision-, and reviewer-bound review
records. Graph waits checkpoint as `waiting_approval` and release their worker
lease. Resume is allowed only after a persisted decision; approval/rejection
checks scope, current paused run, exact plan fingerprint, expiry, and
separation between requester and reviewer. An edited plan supersedes the
pending review and must restart as a new run with a changed fingerprint.

## Evidence

- `services/analytics-api/alembic/versions/0003_durable_analytics_reviews.py`
- `services/analytics-api/app/runtime/control_store.py`
- `services/analytics-api/app/runtime/graph_runner.py`
- `services/analytics-api/app/runtime/governed_stages.py`
- Static validation: Ruff and `git diff --check` pass.

## Boundary

The public review UI/API is not exposed until ADS-045. Reviewer identity must
come from the authenticated application layer; this repository method is not
an authentication provider.
