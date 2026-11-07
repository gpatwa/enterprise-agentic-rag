# Repository settings as code: auto-merge, branch cleanup, and a ruleset that requires the "CI gate" check on main.
# Scope is deliberately narrow. The github_repository resource is imported, and every attribute this stack does not
# own is ignored, so `terraform plan` must show changes only to the two settings below (and the new ruleset).
#
# Apply (needs the operator's own `gh` session; no token is stored anywhere):
#   make bootstrap-github-repo
terraform {
  required_version = ">= 1.6.0"
  required_providers {
    github = {
      source  = "integrations/github"
      version = "~> 6.4"
    }
  }
  backend "azurerm" {}
}

# Auth comes from the GITHUB_TOKEN environment variable, which the make target fills from `gh auth token`.
provider "github" {
  owner = var.owner
}

variable "owner" {
  type    = string
  default = "gpatwa"
}

variable "repository" {
  type    = string
  default = "enterprise-agentic-rag"
}

variable "required_check" {
  description = "Exact name of the check run that must pass before merging to the default branch."
  type        = string
  default     = "CI gate"
}

resource "github_repository" "this" {
  name = var.repository

  allow_auto_merge       = true
  delete_branch_on_merge = true

  lifecycle {
    prevent_destroy = true
    # Everything else about the repository is managed by hand today and must not be reset by this stack.
    ignore_changes = [
      description, homepage_url, visibility, topics, has_issues, has_projects, has_wiki, has_downloads,
      has_discussions, allow_merge_commit, allow_squash_merge, allow_rebase_merge, allow_update_branch,
      merge_commit_title, merge_commit_message, squash_merge_commit_title, squash_merge_commit_message,
      archived, auto_init, gitignore_template, license_template, vulnerability_alerts, web_commit_signoff_required,
      pages, security_and_analysis, template, archive_on_destroy, is_template, ignore_vulnerability_alerts_during_read,
    ]
  }
}

resource "github_repository_ruleset" "default_branch" {
  name        = "main requires CI gate"
  repository  = github_repository.this.name
  target      = "branch"
  enforcement = "active"

  conditions {
    ref_name {
      include = ["~DEFAULT_BRANCH"]
      exclude = []
    }
  }

  # The repository admin role can always bypass, so a wrong rule can never lock the owner out.
  bypass_actors {
    actor_id    = 5 # repository role: admin
    actor_type  = "RepositoryRole"
    bypass_mode = "always"
  }

  rules {
    deletion         = true
    non_fast_forward = true

    required_status_checks {
      # Not "strict": branches need not be up to date, so concurrent PRs do not force rebase churn.
      strict_required_status_checks_policy = false
      required_check {
        context = var.required_check
      }
    }
  }
}

# Environments that hold cloud identities. The Entra federated credential trusts repo + environment, so restricting which
# branches may deploy to the environment is what stops an arbitrary branch's workflow from using that identity.
variable "protected_environments" {
  type    = set(string)
  default = ["discovery-pilot"]
}

resource "github_repository_environment" "protected" {
  for_each    = var.protected_environments
  repository  = github_repository.this.name
  environment = each.value

  deployment_branch_policy {
    protected_branches     = false
    custom_branch_policies = true
  }
}

resource "github_repository_deployment_branch_policy" "main_only" {
  for_each         = var.protected_environments
  repository       = github_repository.this.name
  environment_name = github_repository_environment.protected[each.value].environment
  name             = "main"
}

output "ruleset_id" {
  value = github_repository_ruleset.default_branch.ruleset_id
}
