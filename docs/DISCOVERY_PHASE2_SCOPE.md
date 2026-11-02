# Discovery Phase 2 Scope: Real Data on OpenSearch

Status: **Scoping proposal.** Written from the repository state on `origin/main` (2026-11-02). Nothing here is an approval or a recorded human gate, and no cloud resource is created, planned or changed by this document. Each decision below is the owner's.

## Where Phase 1 stands

The Discovery pilot is deployed (Container Apps, Entra sign-in) and serves a fictional catalog: 48 experiences, 24 synthetic users, 43 searchable documents, generated from seed 7 at container start. Search is lexical only, over an in-memory list. There are no embeddings, no model calls, no database and no search cluster.

## "Real data" is two separate things

1. **Real retrieval infrastructure.** OpenSearch holds the catalog and answers lexical, vector and hybrid queries. The catalog can still be synthetic, at the plan's demo or scale size (2,500 or 25,000 experiences).
2. **Real catalog and behavior data.** Actual items from a source the owner is entitled to use. Behavioral data (impressions, clicks, plays) needs a data agreement and is deferred by the execution plan until consented interaction evidence exists.

This scope covers (1) fully and (2) only as far as a catalog of real items (metadata, no user behavior). Which source that is must be decided first.

## What already exists (and what does not)

| Piece | State |
|---|---|
| Index mapping contract | `app/search/mapping.py`: versioned mapping, compatibility check. No client import. |
| Document mapper | `app/search/mapper.py`: deterministic, provenance-carrying. |
| Retrievers | `lexical.py`, `vector.py`, `fusion.py` (RRF): provider-neutral, tested. The current lexical retriever scores an in-memory list. |
| Indexing | `indexing/worker.py` (outbox bulk upsert, retry, poison quarantine) and `maintenance.py` (tombstone, rebuild, reconcile, alias swap), against a fake provider only. |
| Persistence | `persistence/migrations/0001_discovery_baseline.sql` and models (catalog, profiles, outbox). No repository implementation and no connection settings. |
| Catalog adapters | `adapters/catalog.py`: provenance-gated, and the adapter accepts only `FIXTURE` sources. `FIRST_PARTY` and `LICENSED` are declared but not accepted. |
| OpenSearch client | **None.** Nothing in `services/discovery-api` imports an OpenSearch client, and `requirements.txt` has none. |
| Config | `settings_from_env` reads only `DISCOVERY_*` flags: no endpoint, credentials or database URL. |
| Local OpenSearch | `docker-compose.yml` has a 2.15.0 single node (512 MB heap) used by the Analytics and support stacks. |
| Terraform | `infra/terraform/opensearch` is a provider-neutral contract only; it creates nothing. |

## Proposed work

### Phase 2a: code and local verification (no cloud)
1. **OpenSearch provider.** A client adapter that implements the existing provider-neutral bulk and search contracts, plus an index bootstrap and alias-swap command built on `mapping.py`. Add the client to `requirements.txt`.
2. **Settings and secrets.** Add endpoint, credential and TLS settings, with credentials read from the environment or Key Vault, never logged. Fail closed in `staging` and `production` when real providers are selected without them.
3. **PostgreSQL repositories.** Implement the repository protocols over the existing migration, so PostgreSQL is the authority and the index is rebuildable.
4. **Ingest path.** Extend the adapter so `FIRST_PARTY` or `LICENSED` records are accepted only with complete provenance, license reference and `synthetic=false`. Outbox to the indexing worker to OpenSearch.
5. **Route wiring.** Select the in-memory or the OpenSearch retriever by settings, keeping the fake provider as the default and as the test double.
6. **Relevance evidence.** Run the existing golden corpus (48 experiences, 30 queries) against a real local OpenSearch container and compare lexical, vector and hybrid results with the in-memory baseline. Only report what was run.
7. **Local compose profile.** Discovery plus OpenSearch plus PostgreSQL, so the whole path is exercised before any cloud step.

Exit evidence: CI green with the fake provider; an opt-in local integration run against a real container; the golden-corpus comparison recorded.

### Phase 2b: cloud footprint (separate authorization)
Add OpenSearch and PostgreSQL to `infra/terraform/azure-discovery-pilot`, with private connectivity from the Container Apps environment, secrets in Key Vault, and a budget change. Index the catalog from the outbox, then run Phase 2a's relevance checks against the live index. Live OpenSearch validation needs an explicit request in that task.

### Phase 2c: embeddings (optional, separate decision)
Vectors are off today (a constant placeholder). Real vector retrieval needs an embedding model (Azure OpenAI is already in use for Analytics), a re-embed and rebuild path, and a cost estimate. Lexical on OpenSearch comes first and stands on its own.

## Public commerce catalogs (candidate real sources)

Licenses below are what a web search returned on 2026-11-02 or my recollection where marked. **Confirm each on the dataset's own page before use**; licensing is a human gate.

| Dataset | Scale (approximate) | License | Fit |
|---|---|---|---|
| Amazon Shopping Queries (ESCI) | about 130k queries, about 2.6M query-product judgments, products in English, Spanish and Japanese (recollection) | Apache-2.0 per mirrors and the project page; official LICENSE file not seen | Best for search relevance: it has human relevance labels, so it can score real retrieval |
| Wayfair WANDS | about 43k products, 480 queries, about 233k labels (recollection) | MIT per its GitHub repository | Smaller, labeled, safe to start with |
| Open Food Facts | millions of food products (recollection) | Open Database License (ODbL, share-alike on the database) | Large and genuinely open; food only; attribution and share-alike apply |
| Amazon Reviews 2023 and Amazon Berkeley Objects | tens of millions of items (reviews), about 150k items with images (ABO) (recollection) | Research and non-commercial terms (recollection; not verified in search) | Large, but likely unsuitable for a commercial demo |
| Klarna Product-Page Dataset | 51,701 product pages | CC BY-NC-SA (non-commercial) | Not suitable if the demo is commercial |
| Salsify Open Catalog | not stated | Restrictive terms of service | Read the terms before any use |

**Fit caveat.** Discovery's schema models experiences: genre, theme, modality, device support, age rating and safety state. Products have price, brand, category and attributes instead, and the age and safety filters do not apply the same way. Commerce is named in the execution plan as a later "vertical pack" (deferred). Using a commerce catalog means a new mapping, a new golden corpus, and a policy filter rewrite, not just new rows. For validating OpenSearch retrieval alone, ESCI or WANDS is the practical choice. For a Discovery product demo, a first-party or licensed experiences catalog is a better match.

## Decisions for the owner

1. **Which data?** (a) keep synthetic, scaled up; (b) a first-party experiences catalog; (c) a public commerce set such as ESCI or WANDS, accepting the schema work above. A license must permit this use, and I won't pick a source.
2. **Where does OpenSearch run?** Azure has no first-party managed OpenSearch. The usual options are a commercial managed provider, a self-hosted OpenSearch on Container Apps or AKS, or AWS OpenSearch Service (cross-cloud). `docs/ENTERPRISE_SEARCH_OPENSEARCH_EXECUTION_PLAN.md` (OS-053) already calls for an ADR on this. Cost is a major difference between them.
3. **Budget.** The $25/month cap covers Phase 1. A cluster and a database will exceed it, and I have no measured price. Set a new cap, or ask for a cost model first (OS-086).
4. **Vectors now or later?** I recommend lexical first.
5. **PostgreSQL.** Use the same flexible-server pattern as the Analytics pilot in a Discovery-owned resource group, with no sharing of Analytics resources.
6. **Authorization.** Phase 2a needs none (local only). Phase 2b is a cloud change and needs your explicit go-ahead in that task.

## Risks

- **Licensing and brand.** Real catalog data brings licensing and possible brand confusion. The existing rule stands: no third-party branding or claims without a decision.
- **Behavioral claims.** Ranking-quality claims need real, consented behavior data, which does not exist. Synthetic improvements are not evidence of real engagement, and relevance labels like ESCI's measure query-item match, not engagement.
- **Cost.** A search cluster is the largest recurring cost in this product and is unmeasured.
- **Index drift.** The index is derived from PostgreSQL. The reconcile and rollback tooling exists but has only run against a fake provider.
- **Access.** The cloud footprint is behind Entra sign-in. Keep the cluster private, with no public endpoint.

## Recommended first step

Authorize Phase 2a with option (a) or (b) for data: it is all code and local verification, produces the evidence the cloud decisions need, and commits you to no spend. If you want a large real catalog to test retrieval, add ESCI or WANDS as a local-only benchmark, after confirming the license. I would defer 2b and 2c until you have chosen hosting and a budget.
