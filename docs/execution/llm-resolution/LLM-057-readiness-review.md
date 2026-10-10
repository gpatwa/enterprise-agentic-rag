# LLM-057 Resolution Intelligence Readiness Review

Status: **local demo approved; production approval not granted**

Review scope: the repository state through LLM-056, including the resolution
contracts, trust controls, local evaluation, shadow isolation, adversarial
tests, and the support-web demo path. This review is credential-free and
local-only. It does not deploy Azure resources, contact a live provider, or
approve production traffic.

> Historical scope note: Azure staging was deployed separately on 2026-08-23.
> That deployment does not change this document's local-only decision or grant
> production approval; see [`AZURE-STAGING-DEPLOYMENT-2026-08-23.md`](../azure/AZURE-STAGING-DEPLOYMENT-2026-08-23.md).

## Decision

The LLM resolution intelligence program is ready for a controlled local demo.
The demo can show a messy support ticket becoming an evidence-backed
resolution and a typed, reviewable command while deterministic controls retain
tenant isolation, citation validation, abstention, policy approval, and audit
boundaries.

The program is **not production-ready**. Production approval is blocked until
the external evidence and operational sign-offs listed below are completed.
Local passing tests and scripted-model results must not be presented as live
OpenSearch, frontier-model, scale, or production-operations evidence.

## What Is Demo-Ready Locally

- The support-web flow renders grounded resolution state, evidence, citations,
  confidence/abstention, and the reviewable command boundary.
- The model-enabled local path uses a scripted fake model and an in-memory
  search provider; the model-disabled path falls back deterministically and
  abstains before command generation.
- Exact, lexical, hybrid, ACL-filtered retrieval, candidate fusion,
  deterministic/closed-world reranking, evidence packaging, synthesis,
  verification, typed command generation, policy review, and audit
  representation are exercised by local fixtures.
- Shadow mode is non-blocking, supervised, bounded by timeout, kill-switchable,
  failure-isolated, and does not expose shadow output to users or actions.
- The demo stops at `require_human_review`; it does not execute a customer
  action or call an external connector.

## Verified Local Evidence

The following evidence was inspected in the repository and can be reproduced
without credentials, network access, Azure, or a running OpenSearch cluster:

| Area | Evidence | Result |
|---|---|---|
| Contracts and trust boundaries | LLM-001 through LLM-044 packet records and targeted tests | Present; deterministic authorization, validation, abstention, approval, and audit controls are covered |
| Feedback, registry, telemetry | LLM-050 through LLM-052 implementation and tests | Present; interaction events, versioned configuration, and redacted metrics are covered |
| Offline quality harness | `LLM-053-offline-evaluation-report.md` and `app.resolution.evaluate` | Reproducible deterministic vs scripted-model comparison; metrics are fixture evidence only |
| Shadow isolation | `app/resolution/shadow.py` and `test_resolution_shadow.py` | Primary response is independent; shadow failure/output is isolated |
| Adversarial trust | `test_llm_resolution_security.py` | 8 focused cases passed for injection, tenant/ACL isolation, citations, unsafe commands, timeout, replay, and redaction |
| Local demo | `LLM-056-demo-record.md` and acceptance script | Model-on and model-off paths passed; 20 focused tests passed |

The LLM-053 scripted-model offline path recorded citation precision, supported
claim rate, abstention accuracy, and action validity of `1.0` for its fixture
cases. That is a deterministic harness result, not a claim about a real model.
The deterministic path remains useful as a safety baseline and is not a
production quality target by itself.

## Acceptance Evidence Commands

Run from the repository root:

```bash
PYTHONPATH="$PWD/services/api:$PWD" pytest \
  services/api/tests/test_llm_resolution_security.py \
  services/api/tests/test_resolution_shadow.py \
  services/api/tests/test_resolution_evaluate.py -q
```

```bash
PYTHONPATH="$PWD/services/api:$PWD" python3 -m app.resolution.evaluate
PYTHONPATH="$PWD/services/api:$PWD" python3 scripts/llm_resolution_demo_acceptance.py
git diff --check
npm --prefix apps/support-web run typecheck
npm --prefix apps/support-web run build
```

The commands above establish local repeatability only. They do not establish
provider availability, production latency, scale, cost, TLS, backup recovery,
or operational readiness.

## Go/No-Go Matrix

| Decision area | Local status | Production decision | Required evidence or owner |
|---|---|---|---|
| Demo workflow and UI | **Go** | Not sufficient | Engineering: keep the local acceptance script and packet evidence current |
| Tenant/ACL isolation | **Go for fixtures** | **No-go** until live-path evidence | Security/platform: test isolation against the deployed provider and real identity context |
| Citation grounding and abstention | **Go for fixtures** | **No-go** until real-model calibration | Resolution owner: calibrate supported-claim, citation, abstention, and unsafe-command thresholds |
| LLM quality and cost | **No-go** | **No-go** | ML/ product: run representative corpus with the selected model, token pricing, latency, and quality gates |
| OpenSearch/vector retrieval | **No-go** | **No-go** | Search owner: produce live BM25/vector/hybrid, ACL, shard, and failure evidence |
| TLS, backup, and restore | **No-go** | **No-go** | Platform/SRE: complete production-like TLS and backup/restore drills |
| Load and performance | **No-go** | **No-go** | Performance owner: measure p50/p95/p99, throughput, timeouts, queue behavior, and cost under load |
| Security and operations | **No-go** | **No-go** | Security/SRE: threat review, alerting, incident/runbook review, and formal sign-off |
| Azure deployment | **Staging deployed** | **No-go for production** | Platform: complete DNS, TLS, live OpenSearch, operational drills, and named sign-off |

## Remaining External Work

1. **Live OpenSearch/vector integration evidence:** validate real indexes,
   BM25/vector/hybrid behavior, ACL filtering, mappings, shard/failure modes,
   and provider observability.
2. **Real-model quality and cost calibration:** replay a representative,
   approved corpus with the selected model versions; measure answer support,
   citation correctness, abstention, unsafe-command rate, latency, token use,
   and estimated cost against explicit thresholds.
3. **Production TLS and backup/restore drills:** verify certificate handling,
   secret rotation, encrypted transport, backup integrity, restore time, and
   recovery-point/recovery-time objectives.
4. **Load/performance evidence:** test bounded concurrency, retrieval and
   model timeouts, shadow overhead, queue behavior, rate limits, p95/p99
   latency, and failure recovery.
5. **Security and operational sign-off:** complete threat modeling, red-team
   review, identity/ACL review, logging and redaction review, alert/runbook
   review, and named owner approval.
6. **Azure production readiness:** staging is deployed separately, but DNS,
   TLS, live OpenSearch, operational drills, and named sign-off remain open.

## Residual Risks

- Scripted models and in-memory search can hide real model drift, provider
  errors, index quality problems, and network behavior.
- Offline token estimates and zero/default pricing do not establish real spend;
  shadow traffic can still consume model budget when enabled.
- Fixture ACL tests do not prove identity propagation or authorization under
  production tenancy, connectors, or operational failure.
- Local latency and test pass rates do not predict production tail latency,
  throughput, recovery behavior, or cost at enterprise scale.
- Human approval is represented and enforced locally, but no live connector
  execution has been approved or tested here.
- This review is a release checkpoint for a demo, not a production change
  record, security certification, or customer commitment.

## Owner-Oriented Next Actions

| Owner | Next action | Exit evidence |
|---|---|---|
| Search/platform | Run live OpenSearch/vector integration and TLS/backup drills | Reproducible run records with failures and recovery results |
| ML/resolution | Calibrate real-model quality, cost, routing, and abstention thresholds | Versioned evaluation report and approved thresholds |
| Performance | Execute load and tail-latency test plan | p50/p95/p99, throughput, timeout, and cost report |
| Security/SRE | Complete adversarial review, observability/runbooks, and sign-off | Named approval with tracked residual risks |
| Product/demo | Use only the local acceptance path for prospect demos until the production gates close | Demo script cites LLM-056 and this review; no production claim |
| Platform | Track Azure staging separately and close production gates before approval | Separate deployment decision record |
