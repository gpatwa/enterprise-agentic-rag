# Repository separation: extraction plan (three repositories)

Status: **Proposal. Nothing here is approved and nothing has been executed.** Written 2026-11-10 from `main` at `31c8ef4`. It supersedes the "one repository" outcome of `docs/PRODUCT_SEPARATION_PROPOSAL.md` only if the owner approves it. No repository is created, no history is rewritten and no Azure or GitHub setting changes until the owner says so for that step.

## 1. Why this is back on the table

`docs/PRODUCT_SEPARATION_PROPOSAL.md` chose one repository with per-product CI. On 2026-11-10 the owner said, in their words: "all of them are open source" and "I could not sell all code in same repo". The second statement is the deciding one: a buyer of one product must be able to receive that product without the others, and one repository cannot do that. The owner also said no history scan is required; this plan therefore does not include one (see section 7).

## 2. What the code says (measured on `main`, 2026-11-10)

| Question | Result | How it was checked |
|---|---|---|
| Do the products import each other? | No. analytics to support, discovery to analytics, support to discovery: 0 files each | `git grep` of cross-product imports |
| Who imports `packages/platform_contracts`? | `services/analytics-api` (181 files), `services/discovery-api` (36 files). **Nothing else**: not `services/api`, `pipelines`, `libs`, `models`, `eval` or the platform services | `git grep -l platform_contracts` by directory |
| Which contract modules does each use? | Discovery imports exactly one, `discovery.py` (stdlib and pydantic only). Analytics imports about 38 and does **not** import `discovery.py` | `git grep` of module names |
| Is anything in that package really shared? | No. It is two private module sets in one folder, plus an `__init__.py` that references `discovery` | the two results above |
| What does the landing site cover? | Mostly Analytics (17 mentions, against 2 for Discovery and 2 for Resolution Intelligence) | `git grep` in `apps/landing/src` |

Consequence: **there is no shared library to publish.** The contracts split cleanly by owner and no fourth repository or package is needed.

Sizes (tracked files): `services/api` 323, `services/analytics-api` 383, `services/discovery-api` 184, `apps/support-web` 87, `apps/discovery-web` 40, `apps/analytics-web` 24, `apps/landing` 26, `pipelines` 32, `packages` 47, `services/control-plane` 35, `services/data-plane` 17, `services/sandbox` 5, `services/gateway` 2.

## 3. Target and ownership map

| New repository (names are the owner's to choose) | Owns |
|---|---|
| **Resolution Intelligence** (recommended: keep the current repository, `gpatwa/enterprise-agentic-rag`, and remove the other two from it, so existing URLs, stars and PR history stay) | `services/api`, `apps/support-web`, `pipelines/`, `Dockerfile.ingestion`, `requirements-ingestion.txt`, `libs/`, `models/`, `eval/`, `deploy/` (helm, karpenter, ray), the platform services (`control-plane`, `data-plane`, `gateway`, `sandbox`; Option A in the product-separation doc), the AWS Terraform at `infra/terraform/*.tf`, `infra/terraform/azure`, `infra/terraform/azure-dev`, `infra/terraform/opensearch`, `infra/observability`, `docker-compose.yml`, the support Makefile targets and the RAG docs |
| **Analytics** | `services/analytics-api`, `apps/analytics-web`, `packages/platform_contracts` minus `discovery.py`, `infra/terraform/azure-analytics-pilot`, `scripts/analytics`, the Analytics Makefile targets (25), `docs/execution/enterprise-analytics`, the Analytics docs, `ci-analytics*.yml`, `deploy-analytics*.yml` |
| **Discovery** | `services/discovery-api`, `apps/discovery-web`, `packages/platform_contracts/discovery.py` (moved to the service, for example `services/discovery-api/contracts/`), `infra/terraform/azure-discovery-pilot`, the Discovery docs, `ci-discovery.yml`, `deploy-discovery-pilot-azure.yml`, `discovery-search-vm.yml` |
| **Landing (decision needed)** | `apps/landing`, `ci-landing.yml`, `deploy-landing-azure.yml`. Recommended: with Analytics, since the copy is mostly about Analytics. It could instead be its own repository or live with whichever product is sold last |

Open placement questions for the owner: the landing site; `DESIGN.md`, `design-explorations/`, `CONTRIBUTING.md` and `LICENSE` (each new repository needs its own copies); and who keeps `docs/architecture.md` and the roadmap (recommended: a short pointer in each repository, with the full text where it belongs).

## 4. Constraints that must not be broken

1. **Analytics layout and digests.** The Analytics release manifest and corpus digests are computed from file paths relative to the repository root (`reference_stack/release_manifest.py` uses `SERVICE_ROOT.parent.parent` and `docs/execution/enterprise-analytics`). Recorded approvals refer to those digests. The Analytics repository must keep the identical relative layout (`services/analytics-api`, `docs/execution/enterprise-analytics`, `packages/platform_contracts`). `git filter-repo --path` keeps paths unchanged. Acceptance: `make analytics-m7-manifest` produces the same digests before and after, and the Analytics suite results are unchanged.
2. **Human gates stay with the user.** The recorded gates (M0, M1, M5, M6, M7) and the unapproved thresholds, corpus, sign-offs and reviews move with the Analytics manifest unchanged. Moving code is not approval and must not be described as one.
3. **Terraform state keys do not move.** State stays in `ragterraformstategp` under `discovery-pilot/terraform.tfstate`, `analytics-pilot/terraform.tfstate` and `github-repo/terraform.tfstate`. Each new repository gets its own `backend.hcl` pointing at the same keys. Acceptance: `terraform plan` shows **No changes** for both pilot stacks from the new repositories.
4. **Repository-bound identity.** The Discovery GitHub OIDC credential's subject is `repo:<owner/repo>:environment:<name>` (`github-oidc.tf`, variable `github_repository`). A new Discovery repository needs a new federated credential, and the old one is removed after the cutover. The Analytics deploy workflow uses repository secrets that the owner sets; they must be set again in the new repository by the owner.
5. **GitHub settings are code.** `infra/terraform/github-repo` manages one repository (auto-merge, the "CI gate" ruleset on `main`, the `discovery-pilot` environment). Each new repository needs the same, with its own state key. The "CI gate" job name must exist in each repository's workflows.
6. **No secrets or generated files travel.** Ignored files (`backend.hcl`, `terraform.tfvars`, `secrets.auto.tfvars`, `tfplan`, `.terraform/`) are never copied by history tools; they are recreated per repository by the owner. `.claude/worktrees/azure-deploy` holds the ignored Compass files and stays until they are recreated.
7. **Azure resources do not move.** Resource groups, registries, apps and URLs stay as they are. Only the code and CI that manage them move.

## 5. Method

Use `git filter-repo` on fresh clones, one per product, keeping only the owned paths. This keeps authorship and commit messages and keeps paths unchanged. Rejected alternatives: `git subtree split` (poor handling of several path roots); a fresh repository without history (loses the authorship trail, and the owner has already said history is not a concern, so there is nothing to protect by dropping it); copying files (loses everything). The current repository is **not** rewritten: it only has the other two products removed in ordinary commits, so nobody's clones break.

## 6. Packets (each local until its gate)

| Packet | Work | Evidence required | Gate |
|---|---|---|---|
| X0 | Owner decisions: the three repository names and the owner or organisation, the landing placement, the monorepo's fate (recommended: it becomes Resolution Intelligence), and a go-ahead to create repositories | The owner's words recorded here | **Owner** |
| X1 | Move `platform_contracts/discovery.py` into the Discovery service in this repository: update the 36 imports and `__init__.py`, keep tests. Remove the cross-reference so the package has no Discovery code | Discovery suite unchanged (376 passed, 5 skipped at PR #89's changes; re-run to get the current number); Analytics suite unchanged; `ci-discovery` and `ci-analytics` green | None (local, reversible) |
| X2 | Add a CI check that the three products import nothing from each other, and that `services/api` imports nothing from `packages/` | The check fails when a cross-import is added (tested) | None |
| X3 | Rehearse the extraction locally with `filter-repo` into three scratch clones. For each, list what is missing at build time and fix the layout (Dockerfile contexts, `pyproject.toml`, root `.dockerignore`, Makefile targets, workflow path filters, `CLAUDE.md`, the handoff, `.gitignore`) | Per clone: unit tests pass; Analytics `make analytics-m7-manifest` digests identical to `main`; Docker images build; `terraform validate` and `terraform plan` clean for the pilot stacks (read-only) | None (scratch only, nothing pushed) |
| X4 | Write the per-repository docs: README, `CLAUDE.md`, a fresh handoff, a pointer table between repositories, `CONTRIBUTING.md`, and the licence decision | Reviewed by the owner | **Owner** (licence, naming, claims) |
| X5 | Create the repositories, push the rehearsed result, apply the GitHub settings stack for each (ruleset, auto-merge, environments), the owner sets secrets and the OIDC federated credential is added | CI green in each new repository; `discovery-search-vm.yml` `status` run green from the new Discovery repository; Terraform plans clean | **Owner** (publishing; cloud and identity changes) |
| X6 | Remove the moved products from this repository in ordinary commits, repoint docs, archive or keep the old workflows, and update the roadmap | CI green here; no dangling references (`git grep`) | After X5 |

Nothing in X0 to X6 changes the products' behaviour, the deployed pilots or the data. X1 and X2 can land first, independently, and are useful even if the split is later declined because they make the boundary mechanical.

### What each product must prove after extraction

- **Analytics:** the full suite, including the PostgreSQL-backed tests against a password-enforcing local server (1198 passed, 1 skipped on 2026-11-10 before the skip fix in #131), the golden and evaluation reports regenerate with the same digests, and the web app tests pass.
- **Discovery:** its suite, the web build, and an `az acr build` of the image from the new repository followed by a `terraform plan` with no changes.
- **Resolution Intelligence:** `services/api` and pipeline tests, `tests/test_tenant_data_isolation.py` and the ingestion tests (91 passed, 17 skipped at #126), and the support web build.

## 7. Risks and open items

- **History was not scanned**, at the owner's instruction. The repository is already public, so this plan does not change exposure; the extracted repositories carry the same history. The personal address in `infra/terraform/budgets.tf` and the pilot names in docs and Terraform are in that history. Replacing them in the working tree is separate work and is optional.
- **Not verified:** that `libs/`, `models/`, `eval/` and `deploy/` are used only by Resolution Intelligence (a search for `libs` imports returned nothing, which may mean a different import style, not no use); that the support Makefile targets and `docker-compose.yml` have no Analytics or Discovery dependencies; the exact set of files each workflow file or script references. X3 exists to find these.
- **Mixed files.** `Makefile` (about 25 Analytics, 8 dev, 8 azure, 7 deploy, 6 verify, 5 test targets), `README.md`, `pyproject.toml`, `docker-compose.yml`, `CLAUDE.md` and `docs/` need per-repository versions, not copies.
- **Cross-repository work gets costlier only if a shared package is wanted later.** Today the contracts are not shared, so a contract change is already local to one product.
- **Open pull requests and issues** do not move. Close or finish them first; the repository currently has none open.
- **Licence.** The repository is MIT today. Choosing a licence per product, and any brand or third-party data terms (the ESCI data licence is unconfirmed, Amazon's own terms for product text were not read), are the owner's decisions and are not made here.
- **Effort.** Not estimated. The measured sizes in section 2 and the rehearsal in X3 are the basis for an honest estimate; X3 should produce one.

## 8. Recommended order

X1 and X2 first (local, reversible, useful regardless), then X0 (owner decisions), then X3 (rehearsal), then X4, and only then X5 with the owner present for the publishing and identity steps.
