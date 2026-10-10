# infra/terraform/azure/envs/staging.tfvars
# Staging environment — lightweight, cost-optimized for pre-prod validation.
#
# Usage:
#   terraform init -backend-config="key=staging/terraform.tfstate"
#   terraform apply -var-file=envs/staging.tfvars

environment         = "staging"
resource_group_name = "rag-platform-staging-rg"
cluster_name        = "rag-platform-staging"
acr_name            = "ragplatformacr" # Shared ACR across environments
vnet_cidr           = "10.1.0.0/16"    # Non-overlapping with prod

# Secrets — set via TF_VAR_* or prompt at apply time
# db_password     = ""
# jwt_secret_key  = ""
# neo4j_password  = ""
# openai_api_key  = ""
# gemini_api_key  = ""   # For multimodal RAG (Gemini embeddings)
# tavily_api_key  = ""   # For web search tool
