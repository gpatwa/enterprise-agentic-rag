# LLM Resolution Golden Corpus

This directory contains a small, deterministic corpus for offline support-resolution tests. It is fictional fixture data and must not contain customer records or live model output.

Each case keeps ticket text, authorized evidence, and expected outcomes together. Evidence is referenced by stable search-corpus IDs and includes only a minimal snippet. The `expected` vocabulary is deliberately neutral until the resolution contracts are defined.

`unsafe_fixture_text` marks prompt-injection strings as quoted data to ensure later consumers never treat them as instructions. Cross-tenant or unknown evidence is represented only in `forbidden_claims` or `unauthorized_evidence_ids`; it is never authorized evidence.
