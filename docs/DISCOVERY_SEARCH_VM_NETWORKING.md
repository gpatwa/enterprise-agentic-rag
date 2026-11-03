# Discovery search VM: networking and operations design

Status: **Design proposal.** Written 2026-11-02 from the repository state at `origin/main` (`e73ccd8`) and public documentation. No Terraform was written or run and no Azure resource was changed. Applying any of this is a separate, explicit owner decision.

## 1. Goal and constraints

- OpenSearch (single node, with vectors) runs on an **Azure VM that is started only for demos**, per the owner's decision of 2026-11-02, within the **25 USD monthly alert**.
- The Discovery API (a Container App) must reach it privately. The cluster must never be reachable from the internet.
- The pilot keeps working while the VM is off: the API already falls back to the in-memory catalog (`fallback: true`).
- Data is synthetic and the index is derived, so losing the VM disk costs a rebuild, not data.

## 2. The problem to solve

The current Container Apps environment is the default **non-VNet** kind. A VM cannot be reached privately from it: there is no shared network. Options are to put the environment in a VNet (which replaces it) or to give the VM a public endpoint and restrict it.

## 3. Options

| | A. VNet-integrated environment, private VM (**recommended**) | B. Keep the environment, VM with a public endpoint limited by NSG | C. OpenSearch inside Container Apps | D. Azure AI Search |
|---|---|---|---|---|
| Cluster reachable from internet | No (NSG denies all inbound from the internet) | Yes, to an allowlist; relies on outbound IPs that are not guaranteed stable for a consumption environment *(unverified)* | No | n/a |
| Replaces the environment | **Yes** (new URL, short outage) | No | No | No |
| Fits the decision "Azure VM on demand" | Yes | Yes | No | No |
| Why not | Environment replacement | Public attack surface; fragile allowlist | Needs `vm.max_map_count`, which Container Apps cannot set | Not OpenSearch |

**Recommendation: A.** It is the only option where OpenSearch has no internet exposure at all.

## 4. Recommended design

```
Internet --> Container App "web" (public, Entra sign-in) --> "api" (internal ingress)
                                                              |  https :9200, VNet only
                                                              v
   VNet 10.40.0.0/16
     subnet cae    10.40.0.0/23  Container Apps environment (consumption-only)
     subnet search 10.40.2.0/27  VM  10.40.2.4  (OpenSearch in Docker)
   NSG on subnet search: allow 9200 from 10.40.0.0/23; deny all other inbound
   VM public IP: outbound only (package and image pulls); no inbound is allowed to it
```

### 4.1 Network
- One VNet in `discovery-pilot-rg`. Subnet `cae` is a **/23** (the documented minimum for a consumption-only environment, and its size cannot change later). Consumption-only environments need no subnet delegation.
- Subnet `search` is a /27 with an NSG: allow TCP 9200 from the `cae` subnet; allow nothing else inbound; the default deny rules cover the internet.
- The environment gets `infrastructure_subnet_id`. Its ingress stays external, so the `web` app keeps its public URL and Entra sign-in. `api` keeps internal ingress.

### 4.2 VM
- `Standard_B2s` (2 vCPU, 4 GiB), Ubuntu LTS, **64 GiB Standard SSD (E6)**, static private IP `10.40.2.4`.
- **Public IP is outbound-only.** New VNets default to private subnets with no implicit internet access, and a NAT gateway is not supported with a consumption-only Container Apps environment (and would cost far more than the IP). A Standard static public IP on the VM gives it the internet access that first boot needs (apt, Docker, the OpenSearch image). The NSG blocks all inbound to it.
- **No SSH.** Inbound 22 is denied. Administration uses `az vm run-command`. An optional `admin_ssh_public_key` variable can be set if the owner wants SSH later (it would still need an explicit NSG rule).
- Boot configuration (cloud-init): install Docker, set `vm.max_map_count=262144`, and run `opensearchproject/opensearch:2.15.0` with `--restart unless-stopped`, single-node discovery, a 1 GiB heap, data on the OS disk, bound to `10.40.2.4:9200`. The index therefore survives stop and start.

### 4.3 Transport security and credentials
- The OpenSearch security plugin stays on: HTTPS plus basic authentication (admin user). Version 2.15 requires an initial admin password at first start.
- The image's bundled demo certificates are self-signed and publicly known. That is acceptable **only because the port is reachable from the cae subnet alone**; the API therefore connects with `DISCOVERY_OPENSEARCH_VERIFY_TLS=false`. The settings already allow this in `staging` and reject it in `production`. Replacing the demo certificate with a private CA the API trusts is the follow-up.
- The password is a Terraform `random_password`. It lands in Terraform state, in the VM's `custom_data`, and in a Container App secret (the same exposure as the Entra sign-in secret). Key Vault would be the next step. State access therefore needs to stay restricted.

### 4.4 API configuration (Container App `api`)
`DISCOVERY_SEARCH_BACKEND=opensearch`, `DISCOVERY_OPENSEARCH_URL=https://10.40.2.4:9200`, `DISCOVERY_OPENSEARCH_USERNAME=admin`, `DISCOVERY_OPENSEARCH_PASSWORD` (secret reference), `DISCOVERY_OPENSEARCH_VERIFY_TLS=false`, `DISCOVERY_FEATURE_VECTOR=true`, `DISCOVERY_FEATURE_HYBRID=true`, and a short `DISCOVERY_REQUEST_TIMEOUT_SECONDS` (2) so a stopped VM falls back quickly.

### 4.5 Operating it
| Action | How |
|---|---|
| Start for a demo | `az vm start` (or a manual `discovery-search-vm` workflow with a start/stop input, using the same secrets pattern as the deploy workflow). Allow a few minutes for the JVM; until then responses show `fallback: true`. |
| Stop | `az vm deallocate` (compute billing stops; the disk and public IP still bill). |
| Cost guard | A daily Azure auto-shutdown at a chosen time (free). There is no auto-start. |
| Load or rebuild the index | `az containerapp exec` into the API app and run `python -m app.opensearch.bootstrap`. It runs inside the environment, so it reaches the private IP with the app's own settings. It is idempotent. |
| Rebuild after losing the disk | Same bootstrap. |

## 5. Cost (list prices, eastus; a month is 730 h)

| Item | Price | Monthly |
|---|---|---|
| VM `Standard_B2s` | 0.0416 per hour (Azure Retail Prices API) | 1.66 at 40 h; 30.4 always on |
| Standard SSD E6 (64 GiB) | 4.80 per month (same API) | 4.80 |
| Standard static public IP | 0.005 per hour (same API) | 3.65 (assumed to bill while the VM is deallocated, which I believe but did not verify) |
| VNet, NSG, subnets | no charge | 0 |
| **Search subtotal** | | **about 10.1 at 40 h; about 38.9 always on** |

Adding the Phase 1 baseline (registry about 5.07 per month, plus logs and idle apps, not measured), the on-demand case lands near the 25 USD alert and **has little margin**; an always-on VM does not fit. The alert is a notification, not a hard stop. Demo hours are the dial: 100 h of VM time adds about 2.5 more. Reading Azure Cost Management for `discovery-pilot-rg` after a week would replace these estimates with a measurement.

## 6. Terraform change list (not written)

New: virtual network and two subnets, NSG with its association, public IP, NIC, `azurerm_linux_virtual_machine` with a cloud-init template, `random_password`, an auto-shutdown schedule.
Changed: the Container Apps environment (adds the subnet; **forces replacement**), the `api` app (environment variables and one secret), variables (`search_vm_enabled`, `search_vm_size`, optional `admin_ssh_public_key`, shutdown time), outputs (VM name for the operating commands).

**What replacement means:** the environment, both apps and the auth config are destroyed and recreated. The default domain changes, so **the web URL changes**; the Entra redirect URI is derived from the domain in the stack and updates in place, but any bookmark breaks. Expect a few minutes of downtime and a fresh plan review before applying.

## 7. Verification plan (after an authorized apply)
1. From outside the VNet, `curl` to the VM's public IP on 9200 must time out.
2. Start the VM, run the bootstrap through `az containerapp exec`, and confirm 43 of 43 documents indexed.
3. A search through the web URL returns results with `fallback: false` and hybrid retrieval.
4. Deallocate the VM and confirm the same search returns results with `fallback: true`.

## 8. Unverified
- azurerm 3.117 arguments: `infrastructure_subnet_id` on a consumption-only environment and the shutdown-schedule resource. They need a `terraform validate` and plan.
- Whether `az containerapp exec` can run the bootstrap in this environment (the alternative is a manually triggered Container Apps Job).
- That the environment's apps reach a VM private IP in the same VNet (documented behavior, not tested here).
- VM boot-to-ready time and the `Standard_B2s` quota and availability in this subscription (the Analytics pilot hit a regional restriction for PostgreSQL once).
- That a static public IP bills while the VM is deallocated, and the exact dates of the private-subnet default for new VNets (sources conflict on timing).
- OpenSearch 2.15 first-start behavior with the security plugin and `OPENSEARCH_INITIAL_ADMIN_PASSWORD` in this exact setup (password strength rules apply).

## 9. Decisions for the owner
1. Accept the **environment replacement** (new web URL, short outage)?
2. Accept an **outbound-only public IP** (about 3.65 per month) on the VM?
3. SSH: none (recommended, run-command only) or an SSH key with an explicit rule?
4. Auto-shutdown time, and do you want a start/stop workflow in addition to `az vm`?
5. Authorization to run `terraform plan` (read-only) and then apply, in a separate step.
