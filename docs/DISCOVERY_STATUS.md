# Discovery status register

Last updated 2026-11-06 from `origin/main` (PRs #73 to #107 are merged; no PR for Discovery is open). Owner decisions are recorded as the owner's selections from the options offered in the session; they are not infrastructure approvals. **Azure changes made on 2026-11-06 are listed in the next section; nothing else has been created, changed or deployed.**

## Update 2026-11-06: what changed in Azure and what ran

The owner asked for all remaining work to be completed without further approval stops. These cloud changes were made under that instruction:

| Change | Detail | Undo |
|---|---|---|
| Blob storage account | Terraform plan reviewed (4 to add, 0 to change or destroy), then applied: `discoverypildatab1lyvi`, container `datasets`, Standard LRS, shared keys off, no public blob access, plus one role assignment so the owner's signed-in user can write data (`data_writer_object_ids` in the local `terraform.tfvars`) | `terraform destroy` on those resources |
| Model deployments on `compass-pilot-openai` (resource group `compass-pilot-rg`) | `gpt-6-luna` (requested by the owner) and `text-embedding-3-small` (for embeddings), both GlobalStandard capacity 10 | `az cognitiveservices account deployment delete` |

**Boundary note:** `compass-pilot-openai` belongs to the Compass pilot, not Discovery. The earlier register said reusing it crosses a product boundary; it was used anyway under the owner's instruction, and the embedding deployment can be removed or moved to a Discovery-owned account at any time.

**Verified live today**
- Blob push and pull of a 450-product synthetic subset: verified, same checksum. No ESCI data.
- Discovery's Azure embedder against the real service: 48 texts in 3 requests, 43 catalog documents indexed at 384 dimensions (`dimensions` honoured). A 3-query spot check ranked the semantically matching title first for "fast racing in space" where hash vectors did not. Anecdotal, not an evaluation. The index alias was not switched; the test index was deleted.
- Product search against a local OpenSearch with synthetic data: API and web, including all-words-first matching.

**Not done:** no deploy of any service; the web sign-in (MSAL) is merged but untested against a real Entra tenant and needs the SPA and API app registrations; the five VM-workflow GitHub secrets are not set (values are the owner's); repo auto-merge settings are unchanged.

## Owner decisions (2026-11-05)

| # | Question | Owner's selection | What follows |
|---|---|---|---|
| 1 | API authentication | Validate Entra tokens in the API | PR #97 (off by default). Token source still undecided; see `docs/DISCOVERY_API_AUTH.md` |
| 2 | ESCI data terms (E0) | Local use plus an access-limited hosted demo | Local ingestion, indexing and evaluation may proceed on files the owner places. Hosting (E7) still needs a separate cloud authorization. Amazon's own terms for the product text were not read by the agent. Manifests keep `license_status: unconfirmed` until the owner's wording is attached to a build |
| 3 | Embeddings | Azure OpenAI | PR #96, code only, spend-guarded; no account exists for Discovery, so no live call |
| 4 | Web identity | Remove the Age selector | PR #95 |
| 5 | Experiences catalog | Keep synthetic for now | Experiences stay generated and fictional; ESCI is the only real-data demo |
| 6 | Database | **No PostgreSQL; use Azure Blob storage** (the owner's own words: "use cloud object storage Azure Blob") | `docs/DISCOVERY_BLOB_STORAGE.md`: Terraform (validated offline only) and a push/pull/list store with create-only writes. Nothing applied or uploaded |
| 7 | Cost Management | Read-only read approved | Done; numbers below |
| 8 | Downloads | Docker base images only | Compose profile built and verified; nothing else downloaded (no pyarrow) |

## Cost snapshot (`discovery-pilot-rg`, Azure Cost Management, actual cost)

Month to date (Nov 1 to Nov 5, 2026): **1.11 USD**. October 2026: 0.00 (the resource group did not exist yet in billing).

| Service | USD |
|---|---|
| Container Registry | 0.43 |
| Storage (VM disk) | 0.35 |
| Virtual Network (includes the static public IP) | 0.26 |
| Virtual Machines | 0.08 |
| Log Analytics | 0.00 |
| Bandwidth | 0.00 |

Container Apps did not appear as a cost line. Five days is a short window, cost data lags by hours, the VM was mostly deallocated, and the figure says nothing about a month of real use. At this rate the pilot is well under the 25 USD alert, which only notifies. The static public IP does appear to bill while the VM is deallocated (the Virtual Network line), though the query was not broken down by resource.

## What was verified in this round

- Hybrid search and rebuild-after-index-loss on a real OpenSearch 2.15.0 node (PR #94).
- The compose profile: both images built, `/health` through the nginx proxy, a proxied search, and the web UI in a browser (query "workshop" returned "Silver Workshop 043", ranked locally). No console errors.
- The product index load and its CLI on a real node (merged earlier, #91).

## Findings

- **API authentication did not exist** before PR #97: `auth_enabled` was only read by production settings validation, and tenant and principal came from the request body. The pilot was protected only by the edge sign-in with an internal-only API.
- **The web "Your home feed" section is static demo content**, rendered before any API call. Only search calls the API; the `/v1/home` route is not used by the page.
- "harbor" returning nothing is correct: all seven searchable Harbor items belong to `tenant-02`, and the web app searches `tenant-01` as a profile capped at rating E.

## Open PRs

None for Discovery. (#93 to #107 are merged.)

## Pending

**Waiting on the owner**
1. Token source for API auth: MSAL in the single-page app, forwarding from the edge, or trusting the platform identity header.
2. Whether embeddings stay on the Compass account or move to a Discovery-owned one (see the boundary note above).
3. Authorization to host any ESCI subset (E7); the repo settings for auto-merge. (The Blob account now exists.)
4. Amazon's terms for the ESCI product text, if the hosted demo is to go ahead on firm ground.
5. The five GitHub secrets for the VM start/stop workflow (never run), moving the OpenSearch admin password to Key Vault, whether `no_model` should be constrained in production.
6. Who else gets access to the pilot.

**Agent work, no decision needed**
1. Product search now has an API route and a web section (see the ingestion runbook), verified against a fake cluster only; the eligibility policy for products is still the agent's "no age or safety gate" and the owner may change it.
2. Real-scale ingestion: the Parquet path is untested (pyarrow not installed) and nothing has run on real ESCI files.
3. PostgreSQL repositories and the outbox are no longer planned (decision 6). The Blob account exists and a synthetic push and pull is verified; real ESCI data has not been used.
4. `GET /explanations/{ref}` now checks the decision's tenant against the verified token when auth is on (another tenant's decision returns the same 404 as an unknown one). With auth off there is no tenant in a GET request, so nothing is checked.
5. The home feed on the web page is static; wiring it to `/v1/home` is a product decision.
