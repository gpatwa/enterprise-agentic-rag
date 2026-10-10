# ADS-007: Current V1 Baseline Report

Status: Review
Milestone: M0, Program and graph foundations
Owner: Analytics evaluation
Run date: 2026-09-04

## Purpose

Record a reproducible local baseline before the typed agent graph changes the
analytics path. This is fixture and harness evidence, not a customer-quality or
production-performance claim.

## Immutable inputs

| Input | Value |
|---|---|
| Olist fixture set | `7cc0d437fe33d5276f2879f9b745d65ca30d4142ced7860fad728f24e1f28821` |
| Evaluation suite | `ef51d340b40d023732b37ea6ca0954962f3a55fe631cb26947bd40fa330fde54` |
| Evaluation suite version | `demo-suite-v1` |
| Runtime mode | Local deterministic tests and scripted demo behavior only |
| Network services | None |
| External model | None; no live LLM call |

The fixture digest is calculated by sorting files under
`services/analytics-api/tests/fixtures/olist/`, hashing each filename and file
content with separators, and taking the SHA-256 of the resulting stream. The
evaluation-suite digest is the SHA-256 of
`services/analytics-api/tests/fixtures/evaluation/demo-suite-v1.json`.

## Correctness baseline

Command:

```bash
cd services/analytics-api
PYTHONPATH=.:../.. pytest -q
```

Observed result: **160 passed in 0.93s** on the local Python 3.12 environment.

The canonical fixture checks establish:

- Delivered revenue: `370.00 BRL`
- Delivered orders: `5`
- Average order value: `74.00 BRL`
- Delivered item GMV: `370.00 BRL`
- Average review score: `3.80`
- Average delivery duration: `3.40 days`
- Late delivery rate: `0.40`
- Deliberate raw payment/item fanout: `470.00 BRL`, proving the fixture catches
  a known join error rather than only checking happy-path arithmetic
- Reordered source rows produce the same metric results

The evaluation harness covers one answer, one ambiguity/clarification case, and
one unauthorized/refusal case. Its release gate requires a 100% pass rate for
the supplied result list.

## Latency and cost baseline

The current deterministic demo path returns a fixed `time_ms` value of `18` in
`ANALYTICS_DEMO_MODE`; this is a product fixture value, not a measured database
latency. A local harness serialization benchmark over 100 iterations produced:

| Operation | Iterations | P50 | P95 | P99 |
|---|---:|---:|---:|---:|
| Canonical fixture JSON serialization | 100 | 0.0193 ms | 0.0227 ms | 0.0643 ms |

No LLM tokens, model charges, warehouse charges, cloud charges, or network
latency are represented in this baseline. Those values remain **not measured**
until a provider-pinned benchmark and a real or controlled database boundary are
available.

## Failure baseline

The current V1 tests prove deterministic rejection for:

- destructive SQL and multi-statement SQL;
- unknown tables and columns;
- `pg_sleep` and selected cost-guard violations;
- invalid typed analytical intent, unknown semantic IDs, and invalid time ranges;
- ambiguity and unauthorized outcomes in the evaluation suite;
- missing analytics database or LLM configuration outside demo mode.

Crash/resume, durable checkpoint, cross-tenant policy, live provider failure,
and graph-loop behavior are not yet baseline capabilities. They belong to
`ADS-003` through `ADS-006` and later milestone gates.

## Interpretation and limitations

This report establishes a repeatable pre-agent baseline and the known failure
surface. It does not establish production SLOs, customer accuracy, real-model
quality, warehouse throughput, or cost per request. Future reports must retain
these fixture digests and separate deterministic harness measurements from live
boundary measurements.

## Reproduction evidence

```bash
cd services/analytics-api
PYTHONPATH=.:../.. pytest -q tests/test_canonical_olist_metrics.py tests/test_evaluation.py
```

Observed result: **8 passed in 0.13s**.

No Azure, OpenAI, OpenSearch, PostgreSQL, or other external service was called
for this report.
