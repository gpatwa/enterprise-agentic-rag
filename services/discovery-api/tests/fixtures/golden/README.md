# Golden Immersive Discovery Corpus

This fixture corpus is fictional, deterministic, and synthetic. It exists for
search, recommendation, ranking, cold-start, diversity, and policy tests. It
does not contain Roblox data, copied titles, real people, or production events.

All records use stable ASCII identifiers and include `synthetic: true`. Tenant,
age, safety, locale, device, availability, and creator-diversity expectations
are part of the fixture truth. A judgment with grade `0` is irrelevant or
ineligible for its scoped user; a positive judgment must resolve to an eligible
experience in that user's tenant.

Files are intentionally independent of production schemas. Later contracts
may map these neutral fields without changing the golden truth.
