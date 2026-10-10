# ADS-054: Prompt and Example Candidate Registry

Status: **Review** (implemented and locally verified; independent review pending)
Milestone: M5 (wave 5B, last of ADS-052 to ADS-054)
Depends on: ADS-051

## Decisions confirmed by the user

From the wave-5B proposal ("go with your recommendations"): an immutable, versioned registry where a released
version can never be overwritten; the current runtime prompt pinned as a released baseline **without** wiring
the runtime to the registry; candidate examples hold references and fingerprints only; thresholds drafted for
the user's approval; one PR per packet.

## Deliverable

- `packages/platform_contracts/prompt_registry.py`: `PromptTemplate` and `ExampleCandidate`. **The contract
  enforces the properties itself:**
  - A *released* prompt is a system baseline with a `vN` version, no parent, created by `system:baseline`.
  - A *candidate's version is derived from its content* (`candidate-<12 hex of the text fingerprint>`), so it can
    never share a released version string and identical content always gets the same version.
  - Every prompt must keep the baseline's three defensive clauses (untrusted data; only certified IDs; never emit
    SQL or code), must use exactly its declared simple `{placeholder}` markers, and cannot weaken them.
  - An example candidate has **no field that can hold request text** (only fingerprints and IDs); `extra` fields
    are forbidden, and the only redaction mode is `references_only`.
  - `render` substitutes declared placeholders in a single pass, so user text containing `{tenant_id}` is never
    re-expanded.
- Migration `0008_prompt_registry`: one append-only table (triggers reject UPDATE/DELETE on SQLite and
  PostgreSQL) keyed by scope, tenant, kind, name, and version.
- `app/prompt_registry/store.py`: `register_baseline` (the only way to create a released version; identical content
  is a no-op, different content raises `RegistryConflictError`) and `register_candidate` (needs a released
  baseline for the name, an existing visible parent, the parent's placeholder set, and text that differs from the
  parent). A tenant's candidates are invisible to other tenants; system baselines are visible to all.
- `app/prompt_registry/baseline.py`: `intent-prompt@v1`, the text `intent_node.py` builds today, expressed as a
  template, with its fingerprint pinned. The runtime still builds its own prompt: a test renders the baseline and
  requires it to equal `_prompt(...)` exactly (including adversarial request text), so changing the runtime prompt
  forces a new released baseline version rather than a silent edit.
- `app/prompt_registry/examples.py`: `ExampleCandidateService.from_feedback` records a corrected run as a
  candidate: run, feedback, evidence fingerprint, request fingerprint, intent fingerprint, contract, and the
  correction. Only an `incorrect`/`partially_correct` verdict with a correction qualifies (never `correct` or
  `unsafe`).
- No endpoint, no automatic trigger, and no runtime module imports the registry (tested).
- `make analytics-prompts-eval` runs a 17-case corpus (`reports/ADS-054-prompt-registry-report.md`).

## Evidence

- `tests/test_ads054_prompt_registry.py` (22 tests): the baseline renders exactly the runtime prompt for four
  request texts, including braces, quotes, and newlines; it is pinned and seeded unchanged; the contract rejects
  released/candidate shape violations, each dropped defensive clause, undeclared or malformed placeholders, and
  any text field on an example; re-registering the baseline is a no-op while changing it conflicts; candidates get
  content-derived versions, are idempotent, and cannot be released under a `candidate-` name; a simulated hash
  collision still cannot overwrite; the table rejects UPDATE/DELETE; tenant privacy; an example built from a run
  asked about a canary string stores no request or note text; non-qualifying feedback is refused; the runtime never
  imports the registry, there is no registry endpoint, and the runtime prompt, contracts, goldens, thresholds, and
  manifest are byte-identical; and the corpus evaluation including detection of a wrong expectation and a changed
  corpus. Full suite: 520 passed.
- `make analytics-prompts-eval`: 17/17 hand-written cases pass and all nine proposed gates are met.

## Proposed thresholds (NOT APPROVED)

`reference_stack/prompt_registry/prompt-thresholds.proposed.json`, approval status `proposed`: outcome agreement,
overwrite rejection, tenant isolation, and determinism 100%; released-row mutations, candidate namespace
violations, example text leakage, runtime-prompt drift, and protected-file writes 0. Expectations were written by
hand and the corpus digest is pinned. **Only you can approve or change these.**

## Boundary

- Nothing releases or promotes a candidate: there is no operation that turns a candidate into a released version
  (promotion and rollback are ADS-057, review is ADS-055), and the runtime does not read the registry.
- The defensive-clause check is a text check: a candidate that keeps the three sentences but adds contradicting
  instructions would pass it. Whether a candidate is *better* or safe in behavior needs evaluation (ADS-056).
- Examples reference the run and the request by fingerprint, so using one as a few-shot example later needs a
  reviewed, redacted copy of the text, which this packet deliberately does not store.
- The registry shares one table for system and tenant entries; visibility is enforced in the store, not by the
  database. A hash-prefix collision between candidates is refused rather than resolved.
