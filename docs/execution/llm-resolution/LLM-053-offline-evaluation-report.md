# LLM-053 Offline Evaluation

This report is produced locally from the LLM-002 corpus and contains aggregate
metrics only. It does not use credentials, live services, shadow traffic, or
exporters.

## Command

```bash
PYTHONPATH="$PWD/services/api:$PWD" python -m app.resolution.evaluate
```

Use `--corpus PATH` to replay another validated corpus. Malformed corpus data
fails closed.

## Machine-readable summary

The command prints one JSON object with this shape:

```json
{
  "schema_version": "llm-053-v1",
  "corpus_cases": 0,
  "paths": {
    "deterministic": {
      "cases": 0,
      "metrics": {"citation_precision": 0, "supported_claim_rate": 0, "abstention_accuracy": 0, "action_validity": 0},
      "latency_ms": 0, "input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0
    },
    "scripted_model": {}
  }
}
```

Token counts are bounded character estimates for this offline harness; cost is
calculated from supplied rates (zero by default). No raw ticket text or model
output is written to the report.
