# Discovery dataset storage on Azure Blob

Status: **code and Terraform written; nothing applied, nothing uploaded.** Owner decision (2026-11-05, in the owner's words): "use cloud object storage Azure Blob" in place of PostgreSQL. Creating the storage account is a cloud change that still needs an explicit request in its own task.

## What goes in it
Built product subsets (`products.jsonl`, `quarantine.jsonl`, `manifest.json`) under `subsets/<name>/`, and evaluation reports. It is the durable source the OpenSearch index is rebuilt from. The index itself stays derived and disposable. There is no database: nothing here needs an authoritative relational store, and the experiences catalog stays synthetic.

## Security design (`infra/terraform/azure-discovery-pilot/blob.tf`)
- Microsoft Entra access only: shared keys disabled, anonymous access off, TLS 1.2 minimum. There is no key or SAS token to leak.
- Container `datasets` is private. Blob versioning and 7-day soft delete (blobs and containers) are on.
- The apps' managed identity gets Storage Blob Data Contributor. People who push subsets from a laptop are listed in `data_writer_object_ids` (empty by default, so only the apps have access).
- The container is created through the management plane (azapi), so the stack never needs a storage key. The azurerm provider is set to `storage_use_azuread = true` for its data-plane reads.
- Not done: a private endpoint (about 7 USD a month, unverified) and a network allow-list. The public endpoint remains, protected by Entra only. The account name is `<prefix>data<random>`.

## Commands (run from `services/discovery-api` with `PYTHONPATH=.:../..`)
```bash
python -m app.ingest push --out data/subsets/us-25k-seed7 --to az://<account>/datasets --name us-25k-seed7
python -m app.ingest list --store az://<account>/datasets
python -m app.ingest pull --from az://<account>/datasets --name us-25k-seed7 --out data/subsets/restored
python -m app.opensearch.products load --subset data/subsets/restored
```
A plain directory path works as the store too (`--to /some/dir`), for offline use and tests. On a laptop the token comes from the Azure CLI (`az login` first); on Azure it comes from the managed identity.

## Guarantees
- Publishing is create-only (`If-None-Match: *`) and the manifest is written last. A subset with a manifest is complete; a published subset is never overwritten, and a half-uploaded one is invisible and refuses to pull.
- Pushing verifies the subset against its manifest first. Pulling downloads to a temporary directory, verifies the checksum, and only then moves it into place; a corrupted download leaves nothing behind.
- Tokens, blob contents and response bodies never appear in logs or errors, only HTTP statuses and names.

## Data terms
ESCI subsets may be stored here only under the owner's decision of 2026-11-05 (local use plus an access-limited hosted demo). Amazon's own terms for the product text were not read by the agent, and manifests keep `license_status: unconfirmed` until the owner attaches their wording. To remove data, delete the `subsets/<name>/` blobs and let soft delete lapse (7 days) or purge the versions; deletion of a subset does not remove copies already pulled to other machines.

## Cost
Not measured. Standard LRS storage for tens of megabytes is expected to cost cents a month (unverified). The pilot's real month-to-date spend is in `docs/DISCOVERY_STATUS.md`.

## Not verified
- Never run against a real storage account or Entra: the REST calls are tested against an in-memory fake of the Blob API, including create-only writes, paging and bearer auth.
- `terraform validate` passes offline; no `plan` or `apply` has been run, so provider behaviour with shared keys disabled (the `storage_use_azuread` setting, role propagation delay) is untested.
- The VM's identity does not yet have access; only the apps' identity does.
- Large files: uploads are a single request per file (fine for tens of megabytes; not tested at scale).
