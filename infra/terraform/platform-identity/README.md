# Platform identity

The one stack that creates the CI identities for the pilot infrastructure. It is the **root of trust**: it is applied by a person
(or Claude Code in the owner's session) with the owner's own `az` and `gh` logins, never from CI.

```bash
scripts/platform_identity.sh              # plan
APPLY=1 scripts/platform_identity.sh      # apply
```

Add a repository by adding an entry to `local.targets` in `main.tf` and running it again.

## What it creates, per repository

| Thing | Purpose |
|---|---|
| Entra app `<name>-infra-plan` | Read-only plan on pull requests and `main`. OIDC subjects: `pull_request`, `ref:refs/heads/main` |
| Entra app `<name>-infra-apply` | Apply from protected environments only. Subjects: `environment:infra-apply`, `environment:infra-apply-destructive` |
| Azure RBAC | plan: `Reader` on its resource group, `Storage Blob Data Reader` on the state container (and `Key Vault Secrets User` on the vault, Analytics). apply: `Owner` on its resource group only, `Storage Blob Data Contributor` on the state container (and `Key Vault Secrets Officer`) |
| Subscription role | one custom role, `terraform-provider-reader`, just enough for the azurerm provider to start |
| Microsoft Graph consent | plan: `Directory.Read.All`. apply: that plus `Application.ReadWrite.OwnedBy` (it can change only app registrations it owns) |
| GitHub environments | `infra-apply` (main only) and `infra-apply-destructive` (main only, **the owner must approve**) |
| GitHub Actions variables | `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `INFRA_PLAN_CLIENT_ID`, `INFRA_APPLY_CLIENT_ID`, `TF_STATE_*`, `PILOT_RESOURCE_GROUP` (and `PILOT_KEY_VAULT`). All non-secret |

No secret is stored anywhere: GitHub signs in with OIDC, and the few real secrets the Analytics stack needs are read from its Key Vault at run time.

## Limits to know

- **State blast radius.** State access is granted on the whole `tfstate` container, so each repository's identities can technically read the other's state blob (the Analytics state holds database passwords). Both belong to one owner today. Before any product changes hands, add per-repository blob-path conditions to the assignments in `rbac.tf` or move each state to its own container.
- **Consent is deliberate.** The apply identity cannot grant Graph permissions to itself or anyone else (no `AppRoleAssignment.ReadWrite.All`). A stack change that needs a new consent shows up as a failed apply and is done here, by the owner.
- **Apply identities own their resource group.** `Owner` is needed because the stacks create role assignments. It is scoped to the pilot resource group, never the subscription.
