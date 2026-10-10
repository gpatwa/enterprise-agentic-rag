# EA-071 through EA-077: Pilot Readiness Pack

This pack is the local, customer-safe execution artifact for the final
enterprise analytics milestones. It contains no customer identifiers,
credentials, warehouse data, or claims of completed external validation.

## EA-071 Connector And Semantic Onboarding

1. Register tenant, identity provider, warehouse dialect, catalog, network
   boundary, retention, and residency requirements.
2. Capture sanitized metadata into the vendor-neutral snapshot contract.
3. Create a draft semantic contract, validate cross-references, and obtain a
   named data-owner approval.
4. Run the evaluation suite and certify only the agreed datasets and metrics.
5. Record rollback owner, support owner, and freshness owner.

Exit evidence: a second tenant can complete the checklist without product code
changes; no secret or raw customer data is stored in Git.

## EA-072 Security And Data Flow

The security owner must approve an inventory covering ingress, control store,
metadata providers, customer VPC execution, model provider, logs, evidence,
support access, subprocessors, deletion, and egress. Mark each edge as
customer-controlled, vendor-controlled, encrypted, and retained-for duration.

## EA-073 Through EA-076 Release Packet

- EA-073: generate SBOM, scan dependencies and images, sign release artifacts,
  and record remediation SLA for every finding.
- EA-074: run an independent penetration test; launch is blocked by unresolved
  critical or high findings.
- EA-075: run an incident tabletop covering query abuse, warehouse outage,
  policy bypass, model outage, and customer notification.
- EA-076: obtain legal approval for DPA, deletion, residency, retention, and
  subprocessors; map each promise to an implemented control and owner.

## EA-077 Pilot Scorecard And Go/No-Go

| Gate | Evidence | Owner | Status |
|---|---|---|---|
| P0 question accuracy | Pinned evaluation report at agreed threshold | Data owner | Pending customer suite |
| Clarification/refusal behavior | Adversarial and ambiguity report | Product owner | Local harness ready |
| Policy and tenant isolation | Negative authorization and compiler tests | Security owner | Local baseline ready |
| Reliability and cost | Load, timeout, cancellation, quota report | Engineering | External environment pending |
| Security review | Threat model, pen test, remediation log | Security counsel | External gate |
| Contract and privacy | DPA, deletion, residency, retention approval | Legal | External gate |
| Support readiness | Escalation matrix and incident drill | Operations | External gate |

Go requires every P0 row to have an owner, evidence link, and pass result.
Any unresolved security, privacy, tenant-isolation, or data-owner objection is
an automatic no-go. The final decision must be signed by product, engineering,
security, operations, and the customer data owner.
