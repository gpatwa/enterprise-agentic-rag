# Infrastructure automation (no manual steps, no stored secrets)

Owner-authorised 2026-11-10 ("avoid all manual steps, it is hard to remember and scale later"). Built and verified the same day.

## The model

| Layer | Where | Who runs it | What it does |
|---|---|---|---|
| Root of trust | `infra/terraform/platform-identity` (this repository) | A person, or Claude Code in the owner's session, with the owner's own `az` and `gh` logins: `APPLY=1 scripts/platform_identity.sh` | Creates a read-only **plan** identity and an **apply** identity per product repository (GitHub OIDC, exact immutable subjects), their RBAC and Graph consent, the protected GitHub environments, and the non-secret Actions variables |
| Infra workflow | `.github/workflows/infra.yml` in `agentic-search-discovery` and `agentic-data-analytics` | GitHub Actions, automatically | Plans on every pull request; on merge to `main` applies if the plan only adds or changes |
| Approval gate | environment `infra-apply-destructive` | The owner, one click | Required only when a plan **destroys or replaces** something |

Nothing is stored as a GitHub secret. Sign-in is OIDC. The few real secrets the Analytics stack takes as variables are read from its own Key Vault at run time (masked, never rotated). Personal inputs (emails, object IDs) live in private storage (`config/<repo>.tfvars.json` in the state container), because workflow variables are not masked in public logs. Logs list resource addresses and actions only.

## Everyday use

- **Change infrastructure:** edit the stack, open a pull request, read the plan summary on the run, merge. If it only adds or changes, it applies by itself. If it destroys or replaces, the run waits: approve it in the GitHub Actions UI (environment `infra-apply-destructive`).
- **Add a product repository:** add an entry to `local.targets` in `infra/terraform/platform-identity/main.tf`, run `APPLY=1 scripts/platform_identity.sh`, copy `.github/workflows/infra.yml` and `.github/actions/terraform`, add a `ci-prepare.sh` if the stack needs run-time inputs.
- **Discovery workflow variables** follow the Discovery stack's `github_actions_variables` output; re-run `scripts/platform_identity.sh` after that output changes.

## What stays human, on purpose

- Analytics human gates (semantic certification, thresholds, the reference corpus, sign-offs, independent reviews): a gate anyone or anything can pass is not a gate.
- A stack change that needs a **new Microsoft Graph consent** (the apply identity cannot grant permissions to itself or anyone): it fails visibly and is done by the owner through the identity stack.
- Licence, brand and public wording.

## Limits to know

- **State blast radius:** state access is granted on the whole `tfstate` container, so each repository's identities can technically read the other's state blob. Add per-repository blob-path conditions (or separate containers) before any product changes hands.
- **Plan identities can read secret-bearing properties** (Cognitive Services keys, Container App and Static Web App secrets, registry credentials, Analytics Key Vault secrets) because the azurerm provider reads them while refreshing. Plans run only on pull requests from the same repository (forks get no OIDC token); logs never print them.
- **Apply identities own their resource group** (`Owner` is needed because the stacks create role assignments), never the subscription.
- **Not yet converted:** the older deploy workflows (`deploy-*.yml`) still read stored `secrets.*`. Their conversion to OIDC plus run-time reads (Static Web App token from `az staticwebapp secrets list`, API key from Key Vault) needs a dedicated deploy identity and is the next step.

## Things that went wrong and how they were found (so they are not rediscovered)

| Symptom | Cause | Fix |
|---|---|---|
| `AADSTS700213 No matching federated identity record` | GitHub issues the **immutable** subject (`repo:owner@ownerId/name@repoId:...`) for these repositories | Subjects built from the owner and repository IDs; check with `gh api repos/OWNER/NAME/actions/oidc/customization/sub` |
| `403 listKeys / listSecrets / listAppSettings` on plan | `Reader` cannot do the secret-bearing reads the provider performs when refreshing | Custom role `terraform-plan-refresh`, read-only, on the pilot resource group only |
| `state blob is already locked` on apply | A stale infinite lease left by a killed local Terraform process (plan jobs use `-lock=false`, so they never noticed) | Confirm no Terraform process is running, then `az storage blob lease break` on that blob |
| A plan wanting to **remove all owners** of an Entra app (1 to 0) | A stack that does not configure `owners` sees ownership added by the identity stack as drift | `lifecycle { ignore_changes = [owners] }`; found by running the plan before merging |
| Spurious replacements when a CI identity runs the stack | Resources that name "whoever runs Terraform" (owners, a Key Vault role assignment) | `ignore_changes` on those attributes |
