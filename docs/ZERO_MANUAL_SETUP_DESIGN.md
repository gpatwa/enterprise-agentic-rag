# Zero-manual setup: design brief

**Goal (owner, 2026-11-07):** no manual portal or settings changes. Every environment, identity, permission and repo setting is code or config in this repository, applied by one idempotent command. **Non-goals:** automating human governance (gates, approvals, legal terms), or deploying the support product.

## Engineering principles
1. **Single source of truth.** Anything that exists in Azure or GitHub is declared in Terraform in the repo. Hand-made resources get imported or removed.
2. **Plan before apply, always.** Agents produce a PR and a saved plan; a person or the coordinator applies after reading it. Applies are idempotent and re-runnable.
3. **Least privilege and small blast radius.** Scoped role assignments, one VM not the resource group, no wildcard redirect URIs, no secrets in outputs, state or the repo.
4. **Every change has a rollback** written in the PR (`terraform destroy -target=...`, a flag, or a revert) and a test or check that proves the seam works. Prefer verifying against the real service over fakes.
5. **Fail closed, name the failure.** Mismatched token version, audience or redirect must produce a clear, logged, non-secret reason, never a silent fallback.
6. **Bootstrap once.** The only credentials needed are the operator's own signed-in `az` and `gh` sessions. No long-lived tokens are added to the repo or to GitHub secrets.

## Product and UX principles
- **No double sign-in.** The web container is already behind Entra sign-in (easy-auth). The SPA must pick up the existing session invisibly (silent acquisition, login hint from the existing session). A visible second login is a defect.
- **Every auth state is a designed screen, not "Search is unavailable".** Loading ("Signing you in..."), expired ("Your session ended. Sign in again."), no access ("You don't have access to this demo. Ask the owner to add you."), and API down (the existing retry message) are distinct, keyboard reachable, announced to screen readers, and never loop. At most one automatic redirect per page load.
- **Operator journey is one command and a readable result.** `make` target, prints what will change, what changed, and the next step. Access is granted by a pull request to a committed access list, not a portal.
- **Copy is plain.** No error codes shown to end users; codes go to logs.

## Contract shared by the streams (do not diverge)
- One Entra app registration (the existing `azuread_application.web` in `infra/terraform/azure-discovery-pilot`) is both the web sign-in app and the API. Add: SPA platform redirect URI = the web app's origin (root, no wildcard); an exposed delegated scope `access_as_user` with identifier URI `api://<client_id>`; `requested_access_token_version = 2`.
- API validation: audience, issuer and tenant must match what a **v2** access token for that app actually carries. The stream must check this against `services/discovery-api/app/security/auth.py` and a token from the real tenant if obtainable, and fix whichever side is wrong.
- Web build env: `VITE_ENTRA_CLIENT_ID`, `VITE_ENTRA_TENANT_ID`, `VITE_ENTRA_API_SCOPE` (`api://<client_id>/access_as_user`). API env: the existing `DISCOVERY_AUTH_ENABLED`, `DISCOVERY_ENTRA_*`, `DISCOVERY_ENTRA_TENANT_MAP`, `DISCOVERY_ENTRA_PRINCIPAL_MAP`, all derived from Terraform, none typed by hand.
- Access list: a committed, non-secret `access.auto.tfvars` of user principal names with a demo profile each. Terraform resolves object IDs, assigns the app role, and generates the principal map.

## Work items
| Id | Item | Acceptance |
|---|---|---|
| A | Discovery Terraform: SPA redirect, API scope, v2 tokens, env wiring, access list, GitHub OIDC federated credential plus scoped VM role and repo variables for the VM workflow, Discovery-owned Azure OpenAI account plus deployment with managed-identity access | `terraform validate` and a saved plan with only intended changes; no secrets in plan or state outputs; embedder supports managed-identity tokens with tests; workflow no longer needs hand-set secrets |
| B | Web auth UX | All auth states above implemented and tested (jsdom); no redirect loop; focus and live-region behaviour tested; 401 triggers one silent retry, then the expired state; 403 shows the no-access state |
| C | `infra/terraform/github-repo`: auto-merge, delete branch on merge, a ruleset requiring the "CI gate" check on `main` | plan reviewed; admin bypass kept so a bad rule cannot lock the owner out; verified with a real throwaway PR before relying on it; documented rollback |
| D | Import the hand-made Compass model deployments into the Compass Terraform | plan shows import only, no unrelated changes; embedding deployment on the Compass account scheduled for removal once A's account exists |

## Risks and mitigations
| Risk | Mitigation |
|---|---|
| Token version, audience or issuer mismatch makes every request 401 | Contract above, plus a test that decodes a real v2 token's claims and runs it through the verifier |
| Ruleset requires a check name that never reports and blocks all merges | Admin bypass, exact check context verified against recent PRs, test PR before relying on it, rollback documented |
| SPA redirect URI collides with the easy-auth callback or loops | Separate platforms on the app; one automatic redirect per load; loop test |
| Terraform in the Compass stack shows unrelated drift | D applies nothing unless the plan is import-only |
| Managed identity role propagation delay makes first embedding call 403 | Documented wait and retry; embedder reports a clear non-secret error |
| Access list in the repo leaks UPNs | Names only, no secrets; owner decides whether the repo may hold them |

## What stays human by design
Governance gates and approvals, legal terms for third-party data (ESCI), choosing who gets access (now a PR), and any real-tenant content for evaluation sets.
