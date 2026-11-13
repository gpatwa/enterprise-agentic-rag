# infra/terraform/azure/envs/prod.tfvars
# Production environment — the one live environment for now (no staging until there are more users).
# Sized small on purpose (burstable AKS/Postgres, Basic Redis/ACR, defaults in the .tf files); scale up when load needs it.
#
# Usage:
#   terraform init -backend-config="key=prod/terraform.tfstate"
#   terraform apply -var-file=envs/prod.tfvars

environment         = "prod"
resource_group_name = "rag-platform-rg"
cluster_name        = "rag-platform-aks"
acr_name            = "ragplatformacr"
vnet_cidr           = "10.0.0.0/16"

# Postgres and Redis stay on public endpoints (Postgres firewall: Azure services only; Redis: TLS 1.2 + access key).
# Move to private networking and set this to false in one change; see postgres.tf and redis.tf.
allow_public_data_services = true

# Secrets — set via TF_VAR_* or prompt at apply time
# db_password     = ""
# jwt_secret_key  = ""
# neo4j_password  = ""
# openai_api_key  = ""
