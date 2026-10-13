# ADS-073: Ambiguity, Abstention, Unsupported-Question, and Calibration Evaluation

Status: **Review** (evaluated locally; thresholds **proposed, not approved**; **one open gap recorded**)
Milestone: M7 (wave 7B)
Depends on: ADS-039, ADS-070

## Decisions made under the user's delegation ("make the decision")

1. **Replace the model's output, run the whole pipeline.** 30 cases feed chosen model outputs through the governed service on DuckDB: 3 unsupported, 4 hostile (raw SQL, injection in ids),
   6 malformed or out-of-bounds, 5 uncertified (unknown metric/dataset/dimension, wrong contract version, a contract of another tenant), 2 cross-tenant, 4 ambiguous, and 6 valid controls.
   The corpus is pinned by digest; thresholds are proposed.
2. **A defect found and fixed.** A model that declared a request unsupported produced `failed / planner_unavailable / retryable: true`, indistinguishable from a model outage (a client
   would retry forever), although the outcome contract already has `refuse / unsupported_request`. The intent node now raises a distinct `unsupported_request` error and the service reports a refusal with that reason and a remediation. The run's terminal kind stays `failed`
   (the evidence envelope reserves `refused` for policy denials) and triage still files it as an intent-stage fault; the smoke journey and three tests were updated to the new outcome. Malformed model output is unchanged (`failed / planner_unavailable`). A test reverts the fix and shows the new gate fails.
3. **Calibration.** No confidence value exists or is claimed (`confidence` is always null), so the gate is zero confidence claims. Calibrating a real model's confidence is not evaluated.
4. **The gap this found was closed afterwards (M7-H2).** (Original text:)  The scripted keyword model answered all 4 near-miss questions ("Show total profit", ...) with a certified metric. That is a property of the scripted
   model, but it also shows the pipeline has no *intent-echo* check (comparing the question to the extracted intent). A real model, or such a check, must close it before a pilot; this is a decision for the user.

## Deliverable

- `reference_stack/abstention_eval.py`, `m7/abstention-corpus-v1.json`, `m7/abstention-thresholds.proposed.json`, `make analytics-m7-abstention`, report `reports/ADS-073-abstention-report.{md,json}`, `tests/test_ads073_abstention.py`
- Runtime fix: `app/runtime/intent_node.py`, `graph_runner.py`, `analyze_service.py`

## Boundary

- No real model was used. Abstention of a real model, calibration, and near-miss behaviour are open. Approval of the thresholds is the user's.

## Update: intent-echo check (M7-H2)

After the first run, a deterministic intent-echo check was added (`app/runtime/intent_echo.py`, wired into the ontology resolution node): every metric and grouping in the intent must be named in the question by a certified term, and a grouping phrase ("by X", "per X", "for each X") must name a certified dimension or a time unit that the intent also groups by. All 8 near-miss questions are now refused as unsupported (gate `near_miss_answered <= 0`), and none of the 60 valid corpus answers is refused. The check is lexical and conservative: an unusual phrasing of a valid question can be refused, and it does not understand meaning. Each other defence is tested with the echo off so it cannot mask them.
