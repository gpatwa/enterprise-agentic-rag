# ADS-070: Versioned 100-Case Reference Corpus

Status: **Review** (corpus built and pinned; **owner approval is pending and is a human gate**)
Milestone: M7 (wave 7A)
Depends on: ADS-049

## Decisions made under the user's delegation ("make the decision")

1. **Same seeded table as the M4 golden suite, a bigger and more varied question set.** The reference stack has one certified metric (revenue), two dimensions, and a scripted
   model. The corpus therefore varies the *questions* (60 answer phrasings of six intents, including case, punctuation, spacing) and the *protected paths* (16 unsupported or unsafe
   requests, 4 policy-denied, 4 cross-tenant, 8 clarify, 8 review) rather than inventing data the stack cannot answer. 100 cases: 60 answers (30 marked P0 customer-style),
   16 refusals, 4 policy-denied, 4 tenant-isolation, 8 clarify, 8 review (the composition is in the approval file).
2. **The oracle is independent of the system under test.** Expected rows come from `reference_stack/m7_corpus.py::expected`, which uses only the seed formula and imports nothing
   from `app` (a test checks this). The corpus file is generated from it; a test checks the checked-in file is exactly what the builder makes.
3. **The corpus is pinned by digest.** `m7/corpus-approval.proposed.json` holds the SHA-256, the composition, and the approval block. Any change to a question or expectation changes the digest.
4. **No approval is recorded.** The definition owner and the results owner must approve independently; both are `null`. Every later M7 report that uses this corpus says so.
5. **Questions avoid the scripted model's keyword collisions on purpose** (for example, a monthly question that mentions "statuses" would be read as a status question). That
   is a limitation of the scripted model, recorded in ADS-073's report rather than hidden by choosing questions around it silently.

## Deliverable

- `reference_stack/m7_corpus.py` (builder, oracle, `corpus_problems`), `reference_stack/m7/corpus-v1.json`, `reference_stack/m7/corpus-approval.proposed.json`
- `tests/test_ads070_corpus.py`
- `reference_stack/golden.py`: `load_suite` and `run_golden` accept a corpus and thresholds path (the M4 defaults are unchanged)

## Boundary

- These are phrasings of reference intents, not real customer questions. **The data owner must supply 25-50 real P0 questions and approve expected results before a pilot decision.**
- Approval by the definition owner and the results owner is outstanding.
