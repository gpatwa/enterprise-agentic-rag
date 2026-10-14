# Operations runbook: security finding

The security gate is failing or a finding is not `resolved`, ADS-067. Advisory only: the dashboard starts nothing and changes nothing; a person decides.

## Symptom

A security case regressed, or a finding in the register is open or an open decision.

## Likely causes

- A defence was weakened in the compiler, gateway, identity, or redaction path.
- A new threat without a test (the threat-model test fails).
- An open decision (for example F-03, small-cohort suppression) that the security owner has not made.

## Read-only checks

- `make analytics-security-eval` and read the failing case id and the finding it maps to.
- Read the threat model row for the case and its verification test.
- Run the named test.

## Mitigation

- Restore the defence and add a case for any new bypass.
- Accepting a residual risk, or deciding an open finding, is the security owner's decision; record it only with their words.

## Do not

- Do not delete or rewrite runs, evidence envelopes, feedback, or audit rows; they are append-only on purpose.
- Do not edit a threshold, policy, golden, or registry entry to make an alert stop. Changes go through the reviewed path.
- Do not record any approval or mark any packet complete because an alert cleared. Approvals are the user's.
