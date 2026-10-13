# ADS-065: End-to-End Traces, Metrics, Logs, Redaction, and Correlation

Status: **Review** (implemented and locally verified; independent review of the code pending)
Milestone: M6 (wave 6B)
Depends on: ADS-042, ADS-064

## Decisions made under the user's delegation ("make the decision")

1. **One trace per run, not per request.** The trace ID derives from the tenant and run ID (`trace_id_for_run`), so the analyze call
   and every later clarify, review, or status call on the same run join the same trace. `GovernedAnalyzeService.derive_run_id`
   (extracted from `analyze`, same formula) lets the wrapper know the run before the call starts.
2. **Telemetry is built so it cannot carry data.** Span attributes and metric labels are *allow-lists* (anything else is dropped and
   counted), every string passes the redactor, and the wrappers read only IDs, codes, and counts. Runs are correlated with a
   `run_ref` (a short hash), never the run ID.
3. **No OpenTelemetry or Prometheus dependency.** The model is OTel-shaped (trace, span, parent, attributes, status) and the metrics
   render Prometheus text, but the packet ships in-memory exporters only; a real exporter is deployment work.
4. **Proxies, not edits.** The API, graph nodes, context retrieval, gateway, and evidence store are wrapped (`TracedService`,
   `traced_node`, `TracedGateway`, `TracedEvidenceStore`); the governed code does not know it is observed.
5. **Per-tenant metric labels are allowed but capped** (200 distinct values, then one `other` bucket), because ADS-066's cost attribution
   needs a tenant dimension and an unbounded label is a denial-of-service on the registry.

## Deliverable

- `app/observability/core.py`: `Tracer` (context-propagated spans with trace, parent, layer, timings, status, allow-listed
  attributes), `Metrics` (counters and histograms, allow-listed capped labels, Prometheus text exposition), `StructuredLog` (JSON lines
  carrying the current trace and span), and `Observability` (all three plus `telemetry_text()`, everything it would export).
- `app/observability/redaction.py`: `Redactor` removes JWTs, bearer tokens, credentials in URLs, `password=`/`token:`-style pairs,
  e-mail addresses, and SQL; replaces registered literals; truncates long text; and never emits a structure whole.
- `app/observability/instrumentation.py`: the five wrappers and the layer mapping (the `retrieve` node is the context layer, other nodes
  the graph layer).
- Nothing mounts any of it; `app.main` and `api_v2` do not import it.

## Evidence

- `tests/test_ads065_observability.py` (21 tests): **one run produces one trace containing all five layers** as a connected tree rooted
  at `api.analyze`, with the query span under the execute node and the sealing span under the API span; every node span, log line, and
  the API span correlate by `run_ref` and trace ID and the run ID itself never appears; a run that pauses for review and resumes (plus a
  later status call) stays in one trace across three requests; concurrent runs get separate traces with no cross-parenting; **no
  question text, token, run ID, SQL, physical name, or result value is anywhere in the exported telemetry**, even when a careless caller
  logs them; the redactor handles eight classes of sensitive text, registered literals, long text, and structures; unlisted attributes
  are dropped and counted; metrics count requests, nodes, gateway calls, and seals and expose valid Prometheus text; labels are
  allow-listed and capped; refusals, policy denials, cost failures, and a failed API call are visible in spans, metrics, and logs, and a
  refused run never shows a gateway span; and an observed run gives the same answer and evidence as an unobserved one.
- Two redactor defects found and fixed by those tests: a URL password was partly caught by the e-mail rule first (a fragment of the password
  survived), and a `DELETE FROM …` statement was not recognised as SQL.

## Boundary

- In-memory only: spans, metrics, and logs are not exported, sampled, or retained anywhere, and nothing here is a dashboard or an alert
  (ADS-069 builds on it).
- Redaction is pattern-based. It is a safety net behind the allow-lists, not proof that no sensitive string can slip through a free-text
  field; the allow-lists (which never accept request text, rows, or SQL) are the primary control.
- The data-plane agent (ADS-064) is not instrumented; spans stop at the boundary, and joining a customer-side trace is future work.
- Latency numbers here are wall-clock on a local machine, not an SLO measurement (ADS-066, ADS-076).
