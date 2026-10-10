# EA-076 Data Lifecycle And Compliance Map

| Control | Local implementation/evidence | Contractual or external approval |
|---|---|---|
| Collection minimization | Typed intent, metadata normalization, evidence contracts | Security review of actual fields |
| Purpose limitation | Identity purposes and semantic policy evaluation | Customer purpose mapping |
| Tenant isolation | Tenant-bound contracts, authorization, gateway routing tests | Customer-VPC integration test |
| Retention | `RetentionPolicy`, audit/evidence separation | DPA retention schedule |
| Deletion | Control-store ownership and runbook checkpoints | Customer deletion/residency drill |
| Residency | Flow inventory region column | Legal residency approval |
| Subprocessors | Data-flow inventory and model boundary | Procurement/legal approval |
| Auditability | Hash-chained audit events and evidence IDs | Export/retention acceptance |

The DPA must define controller/processor roles, subprocessors, deletion
timelines, breach notification, residency, support access, and approved model
providers. Do not mark EA-076 complete from this template alone.
