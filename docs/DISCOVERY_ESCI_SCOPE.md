# Discovery on ESCI (a Walmart-like product catalog): Scope

Status: **Scoping proposal.** Written 2026-11-03 from `origin/main` (`09df817`). Nothing here is an approval or a recorded human gate. **No data has been downloaded or loaded, no license is confirmed, and no cloud resource is created or changed by this document.** The owner said they will check ESCI's data terms first (2026-11-03); every packet that touches the data waits on that. This narrows `docs/DISCOVERY_PHASE2_REAL_DATA_SCOPE.md` for the owner's stated direction: "something like a Walmart catalog."

## 1. Why ESCI, and why not Walmart

Walmart's catalog is proprietary. Scraping it would breach its terms, and its affiliate and marketplace APIs restrict storing and reusing the data, so it is not a source. Amazon's Shopping Queries Dataset (ESCI) is the closest public stand-in: real shopping queries over real product listings, with human relevance labels. Whether the data (not just the code repository) may be used in a hosted demo is the owner's check (section 7, decision 1).

What the dataset contains, **from recollection and unverified**: queries in three locales (US, ES, JP); judged query-product pairs labeled Exact, Substitute, Complement or Irrelevant; a reduced "small" version for the ranking task and a "large" one (about 130k queries and 2.6M judgments); and a products table with title, description, bullet points, brand and color. **It has no price, category, rating, image (images are a separate dataset), age rating or safety field.** Confirm all of this against the real files before sizing anything.

## 2. The design problem: Discovery models experiences, not products

| Constraint | Evidence in the repo | Consequence for products |
|---|---|---|
| `ExperienceRecord` needs `genres`, `themes`, `mechanics` from closed enums, at least one each, plus age rating, safety state, devices and locales | `app/domain/models.py` | A product has none of these. Forcing a product into game genres produces plausible but wrong labels. |
| Eligibility is fail-closed on age and safety | search drops blocked, unapproved or unavailable records | ESCI carries no age or safety data, so every item would be "unknown" and hidden, or the policy must change. That policy is a human gate. |
| The document, the OpenSearch mapping and the ranker features assume the experience shape | `app/search/mapper.py` (`CatalogDocumentInput`), `app/opensearch`, `app/ranking` | A second record type touches all three. |

### Options

- **A. Map products into experiences.** Smallest code change, worst fidelity: invented genre and age values, or most items quarantined. Not recommended.
- **B. Add a product mode (recommended for a demo).** A separate `ProductRecord` and document type with the fields ESCI actually has (title, description, bullets, brand, color, locale), its own OpenSearch mapping, its own eligibility rule (no age or safety gate unless the owner wants one), and the existing lexical, vector, hybrid and fallback retrieval reused. The experiences path stays unchanged.
- **C. Benchmark only.** Load ESCI locally to measure retrieval quality and keep it out of the hosted pilot. Cheapest and lowest licensing risk. It does not give a catalog to demo.

Recommendation: **C first (it is also the evidence for B), then B** if the terms allow a hosted demo.

## 3. What it would take

| ID | Work | Needs | Evidence |
|---|---|---|---|
| E0 | **Decision record:** ESCI data terms as read by the owner, allowed uses (local benchmark, hosted demo, display, retention), attribution wording | **Owner** | Dated entry in the program manifest in the owner's own words |
| E1 | **Loader:** read the parquet files from a local, untracked path; filter to one locale; select a bounded subset (for example products that appear in the small version for the US locale); record dataset version and file digests; never commit the data | E0 | Unit tests on a tiny synthetic fixture shaped like ESCI; a run log with counts |
| E2 | **`ProductRecord` and mapper:** typed model, rejection of empty titles, provenance (`LICENSED` or a new source type, with license reference), `synthetic=false`; quarantine with a reason, never default values | E0; owner review of the model | Tests for each rejection; fixture path unchanged |
| E3 | **Index mapping and retrieval for products:** a product index (lexical on title, brand, bullets, description; vector on title plus bullets), reusing the adapter, hybrid fusion and fallback | E2 | Local OpenSearch container: N in, N indexed or quarantined, reconcile shows no drift |
| E4 | **Relevance evaluation:** hold out queries by `query_id` (no query in both tuning and report), score lexical, vector and hybrid with nDCG@10 and recall using graded gains for E, S, C, I (gain values are my recollection of the task's convention; the owner confirms), repeat runs for variance, and a regression list of queries that failed | E3 | A report file with commands, dataset version, subset size, numbers. Only what was run is reported. |
| E5 | **Embeddings decision:** the hashing embedder matches word overlap only. A real model is the owner's cost and model-call approval | **Owner** | Cost per 25k to 100k documents recorded; re-embed and rebuild path tested |
| E6 | **Product eligibility and UI policy:** what "eligible" means without age or safety data; how results are shown (no Amazon or Walmart branding or claims; attribution as the terms require) | **Owner (policy gate)** | Tests that the chosen rule is applied; screenshot of the UI copy |
| E7 | **Hosted load:** size the subset against the on-demand VM (`Standard_B2s`, 4 GiB RAM), load via the existing bootstrap path, show attribution, deletion and takedown handling | E0 to E6; **separate cloud authorization** | Plan reviewed before apply; bootstrap result recorded |

E0 gates everything. E1 to E6 are local code and verification and need no cloud authorization. E7 is a cloud change.

## 4. Sizing (estimates, unverified)

- The full dataset is far larger than the pilot VM should hold. A US-only subset of 25k to 100k products is the working assumption.
- A 384-dimension float vector is about 1.5 KB per document, so 100k vectors is on the order of 150 MB before text and index overhead. Whether a 4 GiB VM serves that with acceptable latency is **not measured**; E3 on a local container gives a first reading, and the VM needs its own.
- No PostgreSQL is needed for a benchmark or for a loaded-from-file demo; the cost trade-off for a database is in section 5 of the real-data scope.

## 5. Risks

- **Data terms.** An open code license does not guarantee the product text may be redistributed or shown in a hosted demo. The owner (and counsel if needed) decides.
- **Brand and claims.** The demo must not imply Walmart or Amazon involvement or that results reflect their ranking.
- **Quality claims.** nDCG on ESCI says nothing about Discovery's experience ranking or about engagement.
- **Scope drift.** A product mode is a second domain model, not a data swap. It should be an explicit owner decision, not a side effect of loading data.
- **Hidden-item behavior.** If the experience eligibility rule is reused, every item is dropped. E6 must be decided first.

## 6. What stays out

User or behavior data, click or purchase logs, images, prices, live Walmart or Amazon calls, and any cloud change.

## 7. Decisions for the owner

1. After reading the data terms: may ESCI be used for (a) a local benchmark, (b) a hosted, access-limited demo, (c) storage in our own index? Record it in your own words (E0).
2. Product mode (option B) after the benchmark, or benchmark only (option C)?
3. Which locale and subset size (suggest US, 25k to 100k products)?
4. Embeddings: keep the hashing embedder for the benchmark, or approve a model and its cost?
5. Eligibility and display policy for products without age or safety data (E6).
6. Authorization for E1 to E6 (local code only) once E0 is recorded, with E7 as a separate later approval.

## 8. Unverified

- Everything in section 1 about the dataset's files, fields, sizes and labels.
- ESCI's data license and terms (the repository's Apache-2.0 notice may not cover the data).
- The gain values for graded labels.
- Index size and latency on the pilot VM.
- That the loader's subset selection yields useful coverage of queries.
