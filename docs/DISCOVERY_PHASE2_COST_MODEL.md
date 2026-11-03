# Discovery Phase 2 Cost Model (OpenSearch with vectors, synthetic data)

Status: **Estimate, not a measurement.** Prepared 2026-11-02 for the owner's budget decision. Azure prices are list prices for `eastus` read from the public Azure Retail Prices API on that date. AWS and Aiven prices come from third-party web pages and **must be confirmed against the vendors' own pages**. Items marked *(memory)* are my recollection and were not verified. No cloud resource was created or changed. Currency is USD; a month is 730 hours.

## 1. Workload size (from the repository)

| Quantity | Value | Basis |
|---|---|---|
| Documents today | 48 experiences (43 searchable) | `app/demo_data.py` |
| Documents in scope | 2,500 (demo) to 25,000 (scale) | `docs/IMMERSIVE_DISCOVERY_EXECUTION_PLAN.md` section 4 |
| Vector dimensions | 384, cosine, HNSW (m=16) | `app/search/mapping.py` |
| Raw vector bytes at 25,000 docs | 25,000 x 384 x 4 B = 38.4 MB | arithmetic |
| Estimated index size at 25,000 docs | about 0.2 to 0.3 GB with text, HNSW graph and one replica-free shard | my estimate, not measured |

**The data is tiny for OpenSearch.** The cluster size is set by the minimum useful node (about 2 vCPU and 2 to 4 GiB so the JVM has about 1 GiB of heap), not by the data. A million documents would need about 1.5 GiB of raw vector memory and a larger node; that is out of scope here.

## 2. Unit prices used

| Item | Price | Source |
|---|---|---|
| Container Apps vCPU, active | 0.000024 per second (0.0864 per hour) | Azure Retail Prices API |
| Container Apps vCPU, idle | 0.000003 per second (0.0108 per hour) | same |
| Container Apps memory, active or idle | 0.000003 per GiB-second (0.0108 per GiB-hour) | same |
| Azure VM B2s (2 vCPU, 4 GiB), Linux | 0.0416 per hour | same |
| Azure VM B2ms (2 vCPU, 8 GiB), Linux | 0.0832 per hour | same |
| Premium SSD P6 (64 GiB) | 10.207 per month | same |
| PostgreSQL flexible server storage | 0.115 per GB-month | same |
| PostgreSQL B1ms compute | about 12 to 15 per month *(memory; the API query returned nothing)* | unverified |
| Container Registry Basic | 0.1666 per day (about 5.07 per month) | same |
| Azure AI Search Basic (one unit) | 0.101 per hour | same |
| Amazon OpenSearch `t3.small.search`, us-east-1 | 0.036 per hour | [third-party pricing pages](https://cloudprice.net/aws/opensearch/instances/t3.small.search) |
| Amazon OpenSearch gp3 storage | 0.122 per GB-month | [AWS pricing examples as quoted by third parties](https://aws.amazon.com/opensearch-service/pricing/) |
| Amazon OpenSearch Serverless | 0.24 per OCU-hour, minimum 2 OCU | third-party pages |
| Aiven for OpenSearch | free tier (capped, single node); Startup plan about 90 to 130 per month, sources disagree | [Aiven docs](https://aiven.io/docs/products/opensearch/reference/plans-pricing) and third parties |

Not applied: any free grants or reservations (Container Apps has a monthly free grant *(memory)*; AWS has a 12-month free tier for a small instance per third-party pages).

## 3. OpenSearch hosting options (monthly)

| Option | Always on (730 h) | Demo hours only (about 40 h) | Notes |
|---|---|---|---|
| **A. Self-hosted on Container Apps**, 1 vCPU and 2 GiB | 24 (idle rate) to 79 (active rate) | about 4 | Billing falls between the idle and active rates; a JVM is rarely fully idle, so plan for the upper end. Index is ephemeral and rebuilt from the seed at start. Cold start about a minute *(estimate)*. |
| A2. Same, 2 vCPU and 4 GiB | 47 to 158 | about 9 | More headroom than this data needs. |
| **B. Azure VM B2s** running OpenSearch in Docker, 64 GiB Premium SSD | 30.4 + 10.2 = **40.6** | 1.7 + 10.2 = **11.9** (VM deallocated when idle; the disk still bills) | You patch, secure and back it up. Needs private connectivity from the Container Apps environment, which is not VNet-integrated today. |
| B2. Azure VM B2ms (8 GiB) | 60.7 + 10.2 = 70.9 | 3.3 + 10.2 = 13.5 | Only if heap needs grow. |
| **C. Amazon OpenSearch Service**, `t3.small.search`, 10 GB gp3 | 26.3 + 1.2 = **27.5** | not applicable (billed while it exists) | Cross-cloud: public endpoint with access control, internet egress between clouds, an AWS account to run. No high availability. |
| D. Amazon OpenSearch Serverless | about 350 (2 OCU x 0.24 x 730) | not applicable | Ruled out: the minimum alone is about 14 times the current cap. |
| E. Aiven free tier | 0 | 0 | Capped and single node; limits not verified for this workload. |
| E2. Aiven Startup | about 90 to 130 | not applicable | Sources disagree; confirm on Aiven's page. |
| F. Azure AI Search Basic (for comparison) | 73.7 | not applicable | Native vector and BM25 search, but it is not OpenSearch and the architecture names OpenSearch as the search plane. Not recommended. |

## 4. Other Phase 2 costs

| Item | Monthly | Notes |
|---|---|---|
| **Vectors (local embedder)** | **0** | A deterministic hashing embedder runs inside the API: no model calls. It matches on word overlap, not meaning, so results show the retrieval path works but are not semantic. |
| Vectors (Azure OpenAI embeddings, optional) | cents | A one-time embed of 25,000 documents at about 100 tokens each is about 2.5 million tokens; the rate is *(memory)* about 0.02 per million tokens for the small embedding model, unverified. Needs the owner's go-ahead for model calls. |
| PostgreSQL flexible server (B1ms, 32 GB) | about 16 to 19 | 3.68 storage plus the unverified compute figure. **Not needed for synthetic data**: the catalog is regenerated from the seed, so PostgreSQL only becomes necessary when real catalog data needs an authoritative store. |
| Log Analytics | capped | The Phase 1 workspace caps ingestion at 0.5 GB per day (at most about 15 GB per month). The per-GB price was not retrieved; a cluster adds log volume. |
| Container Registry | about 5 | Already in Phase 1. |
| Phase 1 apps (web and API, scale to zero) | not measured | Idle cost is near zero. Read Azure Cost Management for `discovery-pilot-rg` after a few days of use. |

## 5. Scenarios

| Scenario | Estimated monthly total on top of Phase 1 | Fits the 25 USD cap? |
|---|---|---|
| **Lean, on demand:** OpenSearch on a B2s VM, started only for demos (about 40 h), synthetic data, local vectors, no PostgreSQL | about 12 | Yes, with the Phase 1 baseline of about 5 to 10 |
| **Lean, scale to zero:** OpenSearch on Container Apps, scale to zero, rebuilt from the seed on each start | about 4 to 9 (per demo hours) | Yes |
| **Always on, Azure:** B2s VM, synthetic data, local vectors | about 41 | No |
| **Always on, AWS:** `t3.small.search` | about 28 | Borderline, and cross-cloud |
| **Real data later:** add PostgreSQL | add about 16 to 19 | No |

## 6. Recommendation

1. Treat the index as **disposable**: PostgreSQL is the authority when it exists, and for synthetic data the seed is. A disposable index can run only when someone is demoing, which is what drops the cost from about 41 to about 12.
2. Prefer **option B on demand** (an Azure VM, start and stop) over Container Apps for a first cluster: OpenSearch needs kernel settings (`vm.max_map_count`) that Container Apps does not let you set, so it would run with memory-mapping disabled (`node.store.allow_mmap=false`), which is unverified here. Scale to zero on Container Apps is the cheapest option if that setting works; test it locally first.
3. **Skip PostgreSQL** until real catalog data exists.
4. **Vectors cost nothing extra** with the local embedder. Decide separately whether Azure OpenAI embeddings are worth the call.
5. **Budget.** Keep the 25 USD alert for the lean scenarios. For an always-on Azure cluster, set about 60 to 75 per month. Either way, keep the 80 and 100 percent notifications.

## 7. What is unverified

- PostgreSQL B1ms and Log Analytics prices (API queries returned nothing) and the embedding price.
- Real OpenSearch memory and disk use at 25,000 documents with vectors: run it locally and record the actual index size and heap before sizing.
- That OpenSearch runs on Container Apps with `allow_mmap=false`, and its cold-start time.
- AWS and Aiven figures (third-party sources).
- Phase 1 actual spend: not read from Azure Cost Management.
- Whether the Container Apps environment can reach a VM privately: it is not VNet-integrated today, so option B needs either a VNet-integrated environment (a rebuild of the environment) or a public endpoint with IP and credential controls.

## 8. Decisions for the owner

1. Which hosting option to build against first (B on demand, A scale to zero, C AWS, or other).
2. The monthly cap for Phase 2.
3. Whether PostgreSQL waits for real data (recommended).
4. Whether embeddings use the free local embedder only, or also Azure OpenAI.
