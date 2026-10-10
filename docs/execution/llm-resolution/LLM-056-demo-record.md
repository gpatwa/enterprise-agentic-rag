# LLM-056 Local Demo Record

Status: **passed locally**

This record captures the credential-free acceptance run for the LLM resolution
workflow. It is intentionally local-only and does not approve production
deployment.

## Command

From the repository root:

```bash
PYTHONPATH="$PWD/services/api:$PWD" python3 scripts/llm_resolution_demo_acceptance.py
```

The command uses `tests.fakes.llm.ScriptedLLM` and the in-memory search
provider. It does not require network access, credentials, a live OpenSearch
cluster, Azure, or a running API server.

## Covered Path

The model-enabled path passed through:

1. Messy support ticket input.
2. Strict intent extraction.
3. Exact, lexical, and hybrid OpenSearch-like fixture queries.
4. Tenant and group ACL filtering before resolution.
5. Candidate fusion/deduplication and closed-world reranking.
6. Versioned evidence packet construction.
7. Citation-grounded resolution synthesis and deterministic verification.
8. A typed `send_customer_reply` proposal.
9. Policy evaluation returning `require_human_review`.
10. An in-memory audit representation with `executed: false`.

The model-disabled path used the deterministic fallbacks, returned an explicit
abstention with `route_to_human`, created no command, and recorded no execution.
The disabled sentinel asserted that no model response was available.

## Result

The acceptance command printed `LLM resolution local demo acceptance: PASS`.
The report identified these local fixture versions:

- index: `demo-opensearch-v1`
- embedding: `fixture-embedding-v1`
- evidence: `demo-evidence-v1`
- command: `support-command.v1`

The enabled path produced only tenant-authorized Acme IDs; the finance-group
document and other-tenant document were absent. Its command stopped at human
approval. The disabled path abstained and stopped before command generation.

## Verification

```text
PYTHONPATH="$PWD/services/api:$PWD" pytest services/api/tests/test_llm_resolution_security.py services/api/tests/test_resolution_evaluation.py -q
20 passed
```

```text
git diff --check
passed
```

## Limitations and External Gaps

- The search fixture is not a live OpenSearch cluster and does not establish
  BM25/vector recall, billion-scale performance, shard behavior, or TLS.
- The scripted model is not evidence of frontier-model quality, latency, or
  cost under production traffic.
- No connector or customer-support system was changed; execution remains
  blocked behind the existing approval boundary.
- Production TLS/backup drills, live-provider evidence, load testing,
  operational sign-off, and Azure deployment remain pending by design.
