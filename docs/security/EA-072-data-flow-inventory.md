# EA-072 Data-Flow Inventory Template

This inventory is intentionally provider-neutral. Complete one copy per pilot
using customer-approved names only; never commit credentials, raw rows, private
schema dumps, or customer identifiers.

| Flow | Source | Destination | Data class | Encryption | Region | Retention | Owner |
|---|---|---|---|---|---|---|---|
| User request | Customer UI | Control plane | query text, identity | TLS | TBD | request policy | Security |
| Semantic metadata | Customer catalog | Control plane registry | metadata | TLS/private link | TBD | contract policy | Data owner |
| Query execution | Control plane | Customer VPC gateway | typed intent, SQL | mTLS/private link | customer | transient | Engineering |
| Query result | Customer warehouse | Evidence store/UI | aggregate result | TLS/encrypted at rest | TBD | DPA | Data owner |
| Audit event | All governed stages | Control store | IDs, decisions, hashes | TLS/encrypted at rest | TBD | audit policy | Security |
| Model request | Control plane | Approved model provider | minimized context | TLS | TBD | provider policy | Security |

## Required Review

The security owner must mark each row `approved`, `rejected`, or `needs-change`,
and attach the subprocessors, residency exception, egress approval, deletion
mechanism, and incident owner. EA-072 is not complete until legal/security
review confirms that the actual deployment matches this inventory.
