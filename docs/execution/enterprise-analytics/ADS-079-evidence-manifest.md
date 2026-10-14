# ADS-079: Final Evidence Manifest and Human Go/No-Go Review

Status: **Review** (the manifest generator is built; **the go/no-go and every sign-off are human and not recorded**)
Milestone: M7 (wave 7C)
Depends on: ADS-071 to ADS-078

## Decisions made under the user's delegation ("make the decision")

1. **The generator links, summarises, and lists blockers; it never decides or signs.** `decision` is always `pending_human_review`; the five signature slots (product, engineering, data owner, security, operations)
   start `null`. `verify_manifest` accepts a signature only as a named person's statement over the manifest's own digest, and even five valid signatures leave the decision to people.
2. **Linked by digest:** code (`app/`, `reference_stack/`), contracts, the semantic registry, prompt baselines, every threshold and policy file with its approval status, corpora, every evaluation report, runbooks, and
   Dockerfiles. No model is selected (the evaluations used a scripted model) and no container image was built.
3. **Blockers are computed, not written by hand**: failing or missing evaluations, threshold/policy files not approved by a person, the unapproved corpus, human gates not recorded as approved (M0, M1, M5, M6, M7), packets in
   `review` with no independent review, unresolved security findings, and missing sign-offs.
4. **Tamper detection:** a changed file, a forged decision, a signature without a named signer, or a signature over another digest is reported by `verify_manifest`. Regenerate with `make analytics-m7-manifest` after any change;
   the checked-in manifest records the commit it was generated at, and its test skips when that differs.

## State at generation

Blocking: ADS-076 `answers_per_tenant_day` not met; the proposed thresholds/policies (20 files) and the corpus are unapproved; five human gates are not recorded as approved; 41 packets are `review` without independent review;
security findings F-02, F-03, F-05 are open; no sign-offs. **The release candidate does not meet the plan's exit gate, and this packet does not change that.**

## Deliverable

- `reference_stack/release_manifest.py`, `make analytics-m7-manifest`, `reports/ADS-079-evidence-manifest.{md,json}`, `tests/test_ads079_manifest.py`
