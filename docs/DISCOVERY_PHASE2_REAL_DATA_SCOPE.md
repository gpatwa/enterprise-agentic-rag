# Discovery Phase 2 Real Data: Scope

Status: **Scoping proposal.** Written 2026-11-02 from `origin/main` (`e83f353`). Nothing here is an approval or a recorded human gate. No data source is chosen, no license is confirmed, and no cloud resource is created or changed by this document. This narrows the "real catalog data" half of `docs/DISCOVERY_PHASE2_SCOPE.md`, whose retrieval-infrastructure half is now built and deployed (#79 to #83).

## 1. Where things stand

- OpenSearch retrieval (lexical, vector, hybrid, fallback) works against a synthetic 43-document index on the on-demand VM. Verified: bootstrap indexed 43 of 43; search returned `fallback: false` with the VM on and `fallback: true` with it off.
- The catalog is still fictional: 48 experiences generated from seed 7, loaded in memory at container start. There is no database in use, and no real item has been ingested.
- Vectors come from a local hashing embedder. It matches word overlap, not meaning, so vector and hybrid results are not yet semantic.

## 2. What "real data" has to satisfy in this codebase

| Constraint | Evidence in the repo | Consequence |
|---|---|---|
| Records are *experiences* with closed vocabularies | `ExperienceRecord` (`app/domain/models.py`): `genres`, `themes`, `mechanics` are enums; each needs at least one value; also `age_rating`, `safety_state`, `availability`, devices, locales | Any real source needs a **taxonomy mapping** into these enums, or a schema change. Items that cannot be mapped must be quarantined, not guessed. |
| Provenance is gated | `CatalogProvenance`: `FIRST_PARTY` and `LICENSED` source types exist, but the only adapter (`FixtureCatalogAdapter`) rejects anything but `FIXTURE`; `provenance` on the record already allows `licensed` and `first_party` | A new adapter is needed. It must require a license reference, retrieval time and `synthetic=false`. |
| Safety and age are fail-closed | Eligibility rules re-check every hit in Python, and search drops blocked, unapproved or unavailable records | Real items need an age rating and safety state. Default for unknown must be "not shown". Setting the policy is a human gate. |
| PostgreSQL is the intended authority | `0001_discovery_baseline.sql` (catalog, profiles, events, derived metadata), `repositories/protocols.py`; the index is derived and rebuildable | Repositories are not implemented. Ingest should write to PostgreSQL, then flow through the outbox and `IndexingWorker` to OpenSearch. |
| Behavior data is out of scope | The execution plan defers behavior data until consented interaction evidence exists | This scope is catalog metadata only: no clicks, plays or user histories. |

## 3. Candidate sources

Licenses are from a web search on 2026-11-02 or my recollection (marked). **Confirm each on the dataset's own page; licensing is the owner's decision.**

| Source | Fit to *experiences* | License | Notes |
|---|---|---|---|
| First-party catalog the owner controls | Best: schema is designed for it | Owner's | Needs an export from the owner; nothing available in this repo |
| Wayfair WANDS (about 43k products, 480 queries, labels) | Poor: products, no age or genre | MIT (GitHub) | Good as a **local relevance benchmark** because it has human labels |
| Amazon ESCI (about 130k queries, 2.6M judgments, products) | Poor: products | Apache-2.0 per mirrors; official file not seen | Same use: benchmark, not a Discovery catalog |
| Open Food Facts | Poor: food | ODbL (share-alike on the database) | Not a fit for this product |
| A licensed games, media or events catalog | Good | Per contract | Cost and agreement unknown; owner decision |
| Amazon Reviews 2023, Klarna, Salsify | Poor | Research or non-commercial or restrictive (recollection) | Do not use for a hosted demo |

**Recommendation.** Treat these as two jobs. (1) *Relevance evidence* with a labeled public set (WANDS first), run **locally only**, to prove the retrieval stack on realistic text and scale. It is never loaded into the hosted pilot and is never described as the Discovery catalog. (2) *The real Discovery catalog* comes from a first-party or licensed experiences source the owner names. I won't pick it, and the schema mapping work cannot be sized until it is named.

## 4. Work packets (each bounded; evidence is what must pass before it is called done)

| ID | Work | Needs | Evidence |
|---|---|---|---|
| R0 | **Decision record:** data source, license text, allowed uses (hosted demo, display, retention), attribution wording, takedown contact | **Owner** | A dated entry in the program manifest in the owner's own words |
| R1 | **Ingest adapter:** accept `FIRST_PARTY`/`LICENSED` only with license reference, source id, retrieval time, content version and `synthetic=false`; reject anything else | R0 | Unit tests for each rejection; fixture path still passes |
| R2 | **Taxonomy mapping:** source categories to `Genre`/`Theme`/`Mechanic`/devices/locales as a reviewed mapping file; unmapped or ambiguous records go to quarantine with a reason | R0; owner reviews the mapping | Mapping coverage report (mapped vs quarantined counts); no silent defaults |
| R3 | **Safety and age policy for real items:** unknown rating or safety means not eligible; owner sets the rules | R0; **owner (policy gate)** | Tests that unrated items never appear for a minor profile |
| R4 | **PostgreSQL repositories and ingest path:** implement the protocols over migration 0001, then source, PostgreSQL, outbox, `IndexingWorker`, OpenSearch. Run against a local PostgreSQL first | R1 to R3 | Local compose run: N in, N indexed or quarantined, reconcile reports no drift |
| R5 | **Relevance evaluation:** golden queries from the labeled set or from owner-written queries; report recall and nDCG@10 for lexical, vector and hybrid vs the in-memory baseline. Only report what was run | R4 (or WANDS alone for the benchmark) | A report file with commands, dataset version and numbers |
| R6 | **Embeddings decision:** the hashing embedder will not retrieve by meaning. Choose a real embedding model (cost and model-call approval are the owner's) or accept lexical-led ranking | **Owner** | Cost per 25k documents recorded; re-embed and rebuild path tested |
| R7 | **Hosted pilot load:** size the index against the VM disk (64 GiB; 25k documents is well under 1 GiB), show attribution, add deletion and takedown handling | R0 to R5; separate cloud authorization | Plan reviewed before apply; bootstrap result recorded |

R0 gates everything except the local WANDS benchmark. R1 to R4 are code and local verification and need no cloud authorization. R7 is a cloud change and needs its own explicit approval.

## 5. Cost and the $25 cap

- A managed PostgreSQL flexible server (B1ms, 32 GB) would add about 16 to 19 USD per month (storage 3.68 is measured from the price API; compute is unverified). With the current estimated spend near the 25 USD alert, this **breaks the cap**.
- Options: (a) raise the cap; (b) run PostgreSQL in Docker on the same on-demand VM (no extra compute, but the authority is unavailable while the VM is off and you now back up a database on a throwaway VM; unverified); (c) keep PostgreSQL local until the pilot needs it and load OpenSearch from a reviewed file at bootstrap (cheapest, but the index stops being derived from a database).
- Real embeddings cost cents for 25k documents at the small model's rate *(price from memory, unverified)* but need model-call approval.
- Actual spend has not been read from Azure Cost Management. Read it before deciding.

## 6. Risks

- **Licensing and brand.** A hosted demo of third-party data can breach terms even if the dataset is open. Share-alike (ODbL) and non-commercial terms need a lawyer's read, not mine.
- **Schema distortion.** Forcing products into experience enums produces plausible but wrong labels. Quarantine over guessing.
- **Safety on real items.** Age and safety fields are the product's core promise. Real catalogs rarely carry them.
- **Quality claims.** Relevance numbers from a product benchmark say nothing about Discovery ranking quality or engagement.
- **Secrets and state.** The OpenSearch admin password already sits in Terraform state; adding PostgreSQL credentials repeats that. Key Vault is the follow-up.

## 7. Decisions for the owner

1. Which source for the real Discovery catalog (first-party, licensed, or none yet), and who supplies it? A license must permit hosted demo use.
2. Is a local WANDS or ESCI benchmark acceptable (after you confirm its license), kept out of the hosted pilot?
3. PostgreSQL: raise the cap, run it on the VM, or defer (section 5)?
4. Embeddings: keep the hashing embedder for now, or approve a model and its cost?
5. Who sets the age and safety rules for real items (R3)?
6. Authorization for R1 to R6 (local code only) now, with R7 as a separate later approval?

## 8. Unverified

- Dataset sizes and licenses marked recollection; ESCI's official license file.
- PostgreSQL compute price, embedding price, actual Azure spend.
- Whether PostgreSQL on the VM is acceptable operationally.
- That any listed source can be mapped to the experience enums at useful coverage; only R2's report will show it.
