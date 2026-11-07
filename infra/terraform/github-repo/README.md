# GitHub repository settings as code

Declares the repository settings that used to be clicked in the GitHub UI:

| Setting | Value | Why |
|---|---|---|
| Allow auto-merge | on | PRs can merge themselves once the required check passes |
| Delete branch on merge | on | no stale branches |
| Ruleset `main requires CI gate` | active on the default branch | the "CI gate" check must pass; deleting or force-pushing `main` is blocked |
| Environment `discovery-pilot` | deployments only from `main` | the Entra federated credential trusts repo + environment, so this stops other branches from using the VM identity |
| Ruleset bypass | repository **admin** role, always | a wrong rule can never lock the owner out |

Everything else about the repository is imported and **ignored**, so applying cannot reset other settings. `terraform plan` must show changes only to the two settings and the ruleset.

## Use
```bash
make bootstrap-github-repo            # init, import what exists, plan (changes nothing on GitHub)
APPLY=1 make bootstrap-github-repo    # apply the plan it just printed
```
Needs only your own `gh` and `az` sessions (the GitHub token comes from `gh auth token` for that process only; state lives in the same Azure storage as the other stacks under its own key, `github-repo/terraform.tfstate`). It is safe to re-run.

## Verify after applying
1. `gh api repos/gpatwa/enterprise-agentic-rag --jq '{allow_auto_merge,delete_branch_on_merge}'` prints both `true`.
2. Open any PR. It must show the "CI gate" check as **required**. `gh pr merge <n> --auto --merge` must be accepted and the PR must merge itself when the gate passes.
3. A docs-only PR must still pass at once (the gate passes when no workflow applies).

## Roll back
Remove only the rule, keep the settings: `terraform destroy -target=github_repository_ruleset.default_branch`. Turn auto-merge off: set `allow_auto_merge = false` and apply. If anything blocks merging, an admin can merge regardless (bypass) or delete the ruleset in one command: `gh api -X DELETE repos/gpatwa/enterprise-agentic-rag/rulesets/<id>` (the id is the `ruleset_id` output).

## Not covered
Branch protection on other branches, required reviews (single-owner repo), merge queue, environments and secrets. The ruleset requires the check by name only (any source); pin it to the GitHub Actions app if a different app ever reports a check named "CI gate".
