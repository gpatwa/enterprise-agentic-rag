# Repository separation: extraction plan (three repositories)

Status: **Executed 2026-11-10 (sections 9 and 10).** Approved for execution by the owner (section 0). Written 2026-11-10 from `main` at `31c8ef4`. The approval covers the packets and limits in section 0 and nothing else: it is not approval of any Analytics human gate, threshold, sign-off, licence choice or secret.

## 0. Final goals and approval record (2026-11-10)

### Final goals

1. **Three independently ownable repositories**, each buildable, testable and deployable on its own, so one product can be handed over or sold without the others: `agentic-resolution-intelligence`, `agentic-data-analytics`, `agentic-search-discovery`.
2. **No product behaviour change.** The deployed pilots keep running, Azure resources do not move, and `terraform plan` for both pilot stacks shows no changes from the new repositories.
3. **Analytics digests unchanged.** The Analytics layout is preserved, and `make analytics-m7-manifest` gives the same digests before and after.
4. **Boundaries enforced by CI**: no product imports another, and no shared library remains (`discovery.py` lives in the Discovery service).
5. **Honest claims.** Each repository's README says what the code does (section 3.2). "Agentic" in `agentic-search-discovery` is stated as roadmap.
6. **Everything that is the owner's alone stays theirs** (list below), and is handed over as a checklist, not asked about.

### Owner's words, recorded verbatim

- "all of them are open source" (all three products)
- "I could not sell all code in same repo"
- "no history scan required"
- "name the repo based on product name", "add agentic prefix to all, later we will add those capability", and the final names: "agentic-resolution-intelligence", "agentic-data-analytics", "agentic-search-discovery"
- "I want to finalize all plan and approval, defined final goals first then finish it without asking me question"
- Earlier standing instruction (2026-11-06): "I want to complete all task, not sure we keep asking for approval."

### Decisions taken on the owner's behalf under that instruction (changeable at any time)

| Decision | Choice | Reason |
|---|---|---|
| Landing site | goes with `agentic-data-analytics` | About 17 of its 21 product mentions are Analytics |
| Where the repositories live | the owner's account, `gpatwa` | No organisation exists; transfer to an organisation later is possible (OIDC subjects and secrets must then be redone) |
| The current repository | becomes `agentic-resolution-intelligence`, renamed last | Keeps URLs, stars and PR history |
| Licence | unchanged: each new repository carries the existing MIT `LICENSE` | Status quo, not a new licensing decision; the owner may change it per product |
| History | extracted with `git filter-repo`, no scan (the owner's instruction) | Preserves authorship and paths |
| Discovery "agentic" capability | a later packet, after the split | Avoids churn during extraction |

### What this approval authorises

Packets X1 to X6 as written in section 6: moving `discovery.py`, adding the independence CI check, local rehearsal, per-repository docs, creating the two new repositories under `gpatwa` and pushing the extracted history, applying the repository-settings Terraform for them, removing the moved products from this repository, and renaming it last.

### What it does not cover (the owner's, listed as a checklist at the end)

GitHub secrets and the Static Web Apps deploy token; the Entra federated credential for the new Discovery repository (a repository-bound identity: it is prepared as code, not applied without the owner's own run); every Analytics human gate (thresholds, reference corpus, the five ADS-079 sign-offs, independent reviews); a licence other than MIT; the ESCI data terms; the Snowflake and Databricks live validation (W8) and draft-contract generator (W9); the Luna price; the leadership messaging review.

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

| New repository | Owns |
|---|---|
| **`agentic-resolution-intelligence`** (recommended: keep the current repository, `gpatwa/enterprise-agentic-rag`, and remove the other two from it, so existing URLs, stars and PR history stay; rename it at the end, see 3.1) | `services/api`, `apps/support-web`, `pipelines/`, `Dockerfile.ingestion`, `requirements-ingestion.txt`, `libs/`, `models/`, `eval/`, `deploy/` (helm, karpenter, ray), the platform services (`control-plane`, `data-plane`, `gateway`, `sandbox`; Option A in the product-separation doc), the AWS Terraform at `infra/terraform/*.tf`, `infra/terraform/azure`, `infra/terraform/azure-dev`, `infra/terraform/opensearch`, `infra/observability`, `docker-compose.yml`, the support Makefile targets and the RAG docs |
| **`agentic-data-analytics`** | `services/analytics-api`, `apps/analytics-web`, `packages/platform_contracts` minus `discovery.py`, `infra/terraform/azure-analytics-pilot`, `scripts/analytics`, the Analytics Makefile targets (25), `docs/execution/enterprise-analytics`, the Analytics docs, `ci-analytics*.yml`, `deploy-analytics*.yml` |
| **`agentic-search-discovery`** | `services/discovery-api`, `apps/discovery-web`, `packages/platform_contracts/discovery.py` (moved to the service, for example `services/discovery-api/contracts/`), `infra/terraform/azure-discovery-pilot`, the Discovery docs, `ci-discovery.yml`, `deploy-discovery-pilot-azure.yml`, `discovery-search-vm.yml` |
| **Landing (decision needed)** | `apps/landing`, `ci-landing.yml`, `deploy-landing-azure.yml`. Recommended: with Analytics, since the copy is mostly about Analytics. It could instead be its own repository or live with whichever product is sold last |

### 3.1 Naming

The owner named the repositories on 2026-11-10, in their words: "agentic-resolution-intelligence", "agentic-data-analytics" and "agentic-search-discovery". They follow the product names, with an "agentic" prefix chosen because those capabilities are to be added later (see the name-versus-claim note in 3.2). The shared "Compass" brand is deliberately not in the repository names, which also makes each product easier to hand over on its own. The code still uses "Compass" internally (`compass-*-web` package names, Azure resource names, `compass-pilot-rg`); renaming those is separate work and not part of the split. All three names were free under `gpatwa` on 2026-11-10 (checked with `gh repo view`).

- **Renaming the current repository is the last step.** GitHub redirects the old URL, but the Discovery GitHub OIDC subject (`repo:gpatwa/enterprise-agentic-rag:...`) and the `github-repo` Terraform stack are bound to the current name, so rename only after those are updated (X5/X6).
- **Trademark:** no trademark or name search has been done for these names. Changing a repository name later costs a rename and a redirect, not a rebuild.

### 3.2 What each repository can honestly say about AI

On 2026-11-10 the owner asked that the repositories be able to say whether they are agentic and LLM-based. The README and repository description should say only what the code supports. Findings from reading the code (not from running a real model unless stated):

| Repository | Agentic? | LLM role | Evidence | What must not be claimed |
|---|---|---|---|---|
| `agentic-resolution-intelligence` | **Yes.** A LangGraph agent graph (`services/api/app/agents/graph.py`) with clarify, context-enricher, planner, retriever, tool, evaluator and responder nodes, and reviewed agent commands for support teams | Plans, answers and evaluates over retrieved support knowledge; model clients exist for several backends (`services/api/app/clients`) | Code and tests; the product is not deployed | Production use; answer quality (no live evaluation is recorded here) |
| `agentic-data-analytics` | **Yes, governed.** A typed, durable graph runner (not LangGraph) with explicit node and edge allowlists, human review gates, and an agent tool surface plus an MCP adapter so external agents can call it | The model does **one bounded job**: turn a question into a typed `AnalyticalIntent` (JSON, validated, `extra="forbid"`) and, separately, draft grounded explanations. Queries are compiled deterministically; the model never writes SQL | `app/llm_structured.py`, `app/runtime`, `app/agent_tools`, `app/mcp`; live pilot uses Azure OpenAI (`gpt-6-luna` declared) | Real-model accuracy: every evaluation and golden suite used a scripted model and emulated PostgreSQL. Certified semantics: the human gate is the owner's |
| `agentic-search-discovery` | **No.** There is no agent loop | **Optional and off by default** (`no_model: True`). Today the only model call is Azure OpenAI **embeddings** for vector and hybrid retrieval (verified live: 384 dimensions, 2026-11-10). The intent adapter has only a scripted provider; the relevance judge and safety policy are contracts with no model SDK | `app/config.py`, `app/embedding/azure_openai.py`, `app/intelligence/*` | "LLM-powered" or "agentic" search; learned personalization or engagement gains (no consented behavioural data exists; the pilot runs a fictional catalog with the hashing embedder) |

**Name versus claim.** "Agentic" in a repository name is a statement about direction. Today only Resolution Intelligence and Analytics are agentic; Search and Discovery is not (see the table). Its README should therefore describe what exists now and list the agentic capability as the roadmap, so the name is not read as a present-tense claim.

Suggested one-line descriptions (the owner edits and approves; these claim only the table above):

- **Resolution Intelligence:** a LangGraph agent system that turns support tickets and knowledge into searchable resolution memory and evidence-backed answers, with reviewed agent commands.
- **Analytics:** governed natural-language analytics: an LLM interprets the question into a typed, validated intent, and a deterministic compiler, policy checks and human review do the rest; callable by agents through tools and MCP.
- **Search and Discovery:** hybrid (lexical and vector) search and personalised discovery over OpenSearch, with model use optional and off by default and an LLM-ready safety boundary.

If the owner wants "agentic" or "LLM" to appear on the Discovery repository, the work is to build it (a real intent provider behind the existing `IntentProvider` protocol, evaluated against the golden corpus), not to word it. That would be a separate packet.

Open placement questions for the owner: the landing site; `DESIGN.md`, `design-explorations/`, `CONTRIBUTING.md` and `LICENSE` (each new repository needs its own copies); and who keeps `docs/architecture.md` and the roadmap (recommended: a short pointer in each repository, with the full text where it belongs).

## 4. Constraints that must not be broken

1. **Analytics layout and digests.** The Analytics release manifest and corpus digests are computed from file paths relative to the repository root (`reference_stack/release_manifest.py` uses `SERVICE_ROOT.parent.parent` and `docs/execution/enterprise-analytics`). Recorded approvals refer to those digests. The Analytics repository must keep the identical relative layout (`services/analytics-api`, `docs/execution/enterprise-analytics`, `packages/platform_contracts`). `git filter-repo --path` keeps paths unchanged. Acceptance: `make analytics-m7-manifest` produces the same digests on the extracted repository as on `main` immediately before the extraction (X1 intentionally changed the digest of `packages/platform_contracts` by moving `discovery.py` out; the five ADS-079 sign-off slots were empty, so no recorded signature refers to the older value), and the Analytics suite results are unchanged.
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
| X0 | Owner decisions: the owner or organisation (names proposed in 3.1), the landing placement, the monorepo's fate (recommended: it becomes Resolution Intelligence), and a go-ahead to create repositories | The owner's words recorded here | **Owner** |
| X1 | Move `platform_contracts/discovery.py` into the Discovery service in this repository: update the 36 imports and `__init__.py`, keep tests. Remove the cross-reference so the package has no Discovery code | Discovery suite unchanged (376 passed, 5 skipped at PR #89's changes; re-run to get the current number); Analytics suite unchanged; `ci-discovery` and `ci-analytics` green | None (local, reversible) |
| X2 | Add a CI check that the three products import nothing from each other, and that `services/api` imports nothing from `packages/` | The check fails when a cross-import is added (tested) | None |
| X3 | Rehearse the extraction locally with `filter-repo` into three scratch clones. For each, list what is missing at build time and fix the layout (Dockerfile contexts, `pyproject.toml`, root `.dockerignore`, Makefile targets, workflow path filters, `CLAUDE.md`, the handoff, `.gitignore`) | Per clone: unit tests pass; Analytics `make analytics-m7-manifest` digests identical to `main`; Docker images build; `terraform validate` and `terraform plan` clean for the pilot stacks (read-only) | None (scratch only, nothing pushed) |
| X4 | Write the per-repository docs: README, `CLAUDE.md`, a fresh handoff, a pointer table between repositories, `CONTRIBUTING.md`, and the licence decision | Reviewed by the owner | **Owner** (licence, naming, claims) |
| X5 | Create the repositories, push the rehearsed result, apply the GitHub settings stack for each (ruleset, auto-merge, environments), the owner sets secrets and the OIDC federated credential is added | CI green in each new repository; `discovery-search-vm.yml` `status` run green from the new Discovery repository; Terraform plans clean | **Owner** (publishing; cloud and identity changes) |
| X6 | **Done** (2026-11-10, PR #142) | The moved products are removed from this repository (1035 files) and the Resolution Intelligence README, `CLAUDE.md`, handoff, Makefile, compose file and CI-gate tests are applied. Tests as before the split (91 passed, 17 skipped). The repository is renamed to `gpatwa/agentic-resolution-intelligence` (the old URL redirects), and its settings stack is reconciled to the new name (auto-merge, branch cleanup, the "CI gate" ruleset) |

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

## 9. Progress (updated as packets land)

| Packet | State | Evidence |
|---|---|---|
| X1 | **Done** (2026-11-10) | `discovery.py` now lives at `services/discovery-api/app/contracts/discovery.py`; 36 imports rewritten; the Discovery Dockerfile and CI no longer touch `packages/`. Discovery suite 511 passed, 9 skipped; the app imports from a copy that has no `packages` folder at all; Analytics plus `packages` tests 1189 passed, 62 skipped (the skips need PostgreSQL) |
| X2 | **Done** (2026-11-10) | `.github/scripts/check_product_boundaries.py` runs in the CI gate on every pull request; 7 tests prove it fails on a cross-product import, a Dockerfile copy of another product and a web-app cross-import, and ignores prose and look-alike names. The gate's own test now says a contract change no longer runs Discovery CI |
| X3 | **Done** (2026-11-10) | `scripts/separation/extract.sh` and `scripts/separation/adapt_clone.py` extract and adapt each product into a scratch clone (nothing pushed). No file is orphaned (1781 files, all in at least one repository); exactly 14 common files appear in all three (licence, README, `CLAUDE.md`, `Makefile`, the CI gate). Per clone: **Discovery** 268 commits, 353 files, suite 511 passed and 9 skipped, lint clean; **Analytics** 250 commits, 693 files, suite and `packages` tests 1189 passed and 62 skipped (identical to `main`); **Resolution Intelligence** 357 commits, 763 files, 91 passed and 17 skipped (identical to before the split). `terraform validate` and `fmt` pass for both pilot stacks from their clones. CI-gate tests pass in each clone (34, 33, 33). The rehearsal found and fixed one mis-assignment (`ci-agentic-eval.yml` is Analytics) |
| X3 finding | Manifest | Generated from the source and from the Analytics clone: every per-file digest is identical. Only `base_commit` and `manifest_digest` differ, because `manifest_digest` includes the git commit hash, which any history rewrite changes. A sign-off must therefore be made on the final repository's manifest; all five slots are empty today |
| X4 | **Done** (2026-11-10), wording is the owner's to edit | `scripts/separation/adapt_clone.py` gives each repository its own README, `CLAUDE.md`, handoff, CI-gate tests, pruned Makefile and compose file, and retargeted repo-settings tooling. READMEs claim only what section 3.2 supports |
| X5 | **Done** (2026-11-10) | Created and pushed [`gpatwa/agentic-data-analytics`](https://github.com/gpatwa/agentic-data-analytics) (257 commits) and [`gpatwa/agentic-search-discovery`](https://github.com/gpatwa/agentic-search-discovery) (275 commits), both public, history preserved. Repository settings applied from Terraform (state keys `github-repo/agentic-data-analytics.tfstate` and `github-repo/agentic-search-discovery.tfstate`): auto-merge, branch cleanup, and a "main requires CI gate" ruleset; Discovery also has its main-only `discovery-pilot` environment |
| X5 finding | Audits | The rehearsal tested code, not workflows, and missed four things that real CI then showed: an Analytics script (`run_agentic_eval.py`), the diagram tooling (`scripts/architecture`), the Analytics Helm and secrets assets under `deploy/`, and the repo-settings tooling that every repository needs. `scripts/separation/extract.sh` now carries them, and the audit that found them (every path and every `make` target a workflow references must exist in that repository) is part of the checklist for any future extraction |
| X6 | **In this pull request** | Removes the moved products from this repository (1035 files) and applies the Resolution Intelligence README, `CLAUDE.md`, handoff, Makefile, compose file and CI-gate tests. Tests as before the split (91 passed, 17 skipped). Rename to `agentic-resolution-intelligence` follows the merge |

## 10. Owner checklist

Updated 2026-11-10 after the autonomous-infrastructure work (`docs/INFRA_AUTOMATION.md`). Most of the original list is now done by code.

**Done by code, no longer manual**
- Deploy workflows: no stored secrets; the API key and Static Web App tokens are read at run time.
- The Entra federated credential for the new Discovery repository: changed by the Discovery infra workflow's first automatic apply. The VM workflow's `status` action was then run from the new repository and signed in.
- GitHub Actions variables for both repositories: written by `infra/terraform/platform-identity` (identity IDs, state settings, resource groups, and the Discovery workflow variables from the stack's own output).
- Ignored Terraform files: replaced by committed non-secret config (`state.hcl`, `pilot.auto.tfvars`), private storage for personal inputs, live values read at run time, and Entra auth for state (no `ARM_ACCESS_KEY`).
- The obsolete `discovery-pilot` environment in this repository: removed.

**Still yours**
1. **Analytics human gates**: thresholds, reference corpus, the five ADS-079 sign-offs, independent reviews. Sign off on the final repository's manifest (its `manifest_digest` includes the git commit).
2. **Approving a destructive infrastructure plan**, when one comes: one click on the `infra-apply-destructive` environment.
3. **Licence** (MIT in all three), README wording and descriptions: drafts.
4. ~~Deploy workflows still read stored secrets~~ **Done**: converted to OIDC with a narrow deploy identity and verified (see `docs/INFRA_AUTOMATION.md`). Only the legacy AWS/AKS workflows still use stored secrets.
5. **State isolation** between repositories (per-repository blob conditions) before any product changes hands.
