# Operations runbook: release gate

A release-gate evidence file reports `failing`, `unapproved`, or `missing` on the dashboard, ADS-049..059. Advisory only: the dashboard starts nothing and changes nothing; a person decides.

## Symptom

A packet's evaluation did not meet its thresholds, has no evidence file, or passes against thresholds that a person has not approved.

## Likely causes

- A defence was weakened or a corpus changed (the digest lock catches this).
- A prompt, policy, or compiler change altered behaviour.
- The report was never generated (`make analytics-*-eval`).

## Read-only checks

- Run the packet's make target locally and read the gate list in the report.
- Compare the corpus digest to its lock.
- Read the packet doc's Boundary section for known gaps.

## Mitigation

- Fix the regression, not the threshold. Re-run the evaluation.
- `unapproved` is not a failure of the code: it waits for the user to approve or amend the proposed thresholds.

## Do not

- Do not delete or rewrite runs, evidence envelopes, feedback, or audit rows; they are append-only on purpose.
- Do not edit a threshold, policy, golden, or registry entry to make an alert stop. Changes go through the reviewed path.
- Do not record any approval or mark any packet complete because an alert cleared. Approvals are the user's.
