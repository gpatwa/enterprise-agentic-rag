# ADS-008: Apache Ossie Compatibility ADR and Mapping

Status: Review
Milestone: M0, program and graph foundations
Owner: Architecture and semantic platform
Dependencies: ADS-001

## Objective

Define a safe, versioned Apache Ossie interchange boundary for Compass
Analytics before implementing import/export. The work must make supported,
Compass-extended, lossy, and unsupported semantics explicit, including
versioning, provenance, tenant and policy scope, import/export behavior, and
round-trip guarantees.

## Scope

This is documentation-only. It covers:

- the authority boundary established by ADS-001;
- the current Compass semantic contract and Git-backed registry;
- Apache Ossie core `0.2.0.dev0` as the pinned draft baseline;
- the normative field mapping and compatibility outcomes;
- the future implementation and review gate for ADS-011.

It does not implement an Ossie parser, converter, registry change, API route,
database migration, runtime code, or shared program-manifest update.

## Inputs inspected

- [ADR-ADS-001](../../adr/ADR-ADS-001-agentic-data-stack-boundary.md)
- [Agentic Data Stack Execution Plan](../../AGENTIC_DATA_STACK_EXECUTION_PLAN.md)
- [Compass semantic contract](../../../packages/platform_contracts/semantic.py)
- [Compass analytical intent](../../../packages/platform_contracts/analytics_intent.py)
- [Compass semantic registry](../../../services/analytics-api/semantic_registry/README.md)
- [Sales semantic fixture](../../../services/analytics-api/semantic_registry/contracts/sales-core-v1.json)
- [Olist semantic fixture](../../../services/analytics-api/semantic_registry/contracts/olist-commerce-v1.json)
- [Apache Ossie core specification](https://apache.googlesource.com/ossie/+/HEAD/core-spec/spec.md)
- [Apache Ossie JSON Schema](https://apache.googlesource.com/ossie-temp/+/HEAD/core-spec/osi-schema.json)
- [Apache Ossie converter guidance](https://apache.googlesource.com/ossie-temp/+/HEAD/converters/index.md)
- [Apache Ossie roadmap](https://github.com/apache/ossie/blob/main/ROADMAP.md)

The upstream core specification identifies `0.2.0.dev0` as draft and mutable.
The roadmap also identifies evolving work around grain, relationship
semantics, filters, derived metrics, catalog integration, and AI context. The
packet therefore treats the upstream version as an explicit compatibility
input, not an invisible dependency.

## Deliverables

1. [ADR-ADS-008](../../adr/ADR-ADS-008-apache-ossie-compatibility.md)
2. [ADS-008 mapping table](../../adr/ADS-008-ossie-compass-mapping.md)
3. This execution packet and its review status.

## Acceptance criteria

- The ADR explicitly preserves ADS-001 authority boundaries.
- The mapping names supported core objects: datasets, simple fields, primary
  key grain, many-to-one relationships, time dimensions, and simple
  single-dataset aggregates.
- Compass-only extensions are identified for stable IDs, tenant, lifecycle,
  owner, provenance, policy, quality, and operational evidence.
- Lossy constructs are explicitly listed, including computed/dialect SQL
  expressions, alternate unique keys, cross-dataset and advanced metrics,
  labels/descriptions not represented by Compass `v1`, and untrusted AI
  context.
- Unsupported constructs are explicitly listed, including reusable filters,
  row-level policy, credentials/rows, unknown Ossie versions, and deferred
  ontology objects.
- Import defaults to `draft`; missing tenant or provenance blocks certified
  execution.
- Export behavior does not leak customer data or grant access and reports
  omitted Compass controls.
- Round-trip behavior distinguishes exact subset, extension-preserved, lossy,
  and rejected outcomes.
- The future implementation gate for ADS-011 includes schema validation,
  cross-reference validation, provenance, tenant isolation, and round-trip
  fixtures.
- No runtime code, public API, migration, provider dependency, shared manifest,
  or generated diagram is changed.
- Packet status remains `Review`; no approval is implied by author completion.

## Future ADS-011 implementation gate

ADS-011 may begin only after this packet is independently reviewed. Its
implementation must:

1. Pin the Ossie schema and mapping version.
2. Validate input before conversion and reject unknown versions.
3. Produce the required compatibility report for every operation.
4. Create draft Compass contracts only after cross-reference validation.
5. Preserve stable source identity and opaque extensions without executing them.
6. Require tenant and complete provenance before certification eligibility.
7. Test exact-subset import/export round trips using the current semantic
   fixtures and adversarial lossy/unsupported cases.
8. Prove that no imported field, AI context, extension, or Ossie expression can
   broaden policy, inject raw SQL into typed intent, or bypass the registry
   lifecycle.

## Validation performed for this documentation packet

The implementation session must run:

```bash
git diff --check
```

The independent reviewer should also confirm the three changed files are the
only files in the ADS-008 worktree and that the repository's existing
architecture references remain intact. Runtime test suites are not required
for this documentation-only packet; the future converter tests belong to
ADS-011.

## Review questions and residual risks

Reviewers should specifically assess:

- whether the supported metric subset is narrow enough to avoid treating
  arbitrary Ossie SQL as certified semantics;
- whether generated stable IDs and extension preservation are sufficient for
  round-trip identity;
- whether the lack of an Ossie core tenant/policy model is handled fail-closed;
- whether the draft-spec version pin and schema fingerprint stop silent drift;
- whether ontology and future Ossie features are correctly deferred rather
  than accidentally implied to be supported.

Residual risks remain in the evolving Ossie draft, especially grain, derived
metric, relationship, filter, and AI-context semantics. Those risks are
contained by the version pin, mapping report, draft-only import default, and
independent review gate. They must be re-evaluated before ADS-011 is approved.

## Commit requirement

Commit this packet independently from the ADS-001 worktree. Do not modify the
shared program manifest. The commit message should be:

```text
docs(ads): define Apache Ossie compatibility boundary
```
