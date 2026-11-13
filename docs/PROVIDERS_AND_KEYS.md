# Model providers, keys and local setup

On Azure the platform needs **no provider API key**. The pods call Azure OpenAI with Entra ID tokens from their
workload identity, the account has key authentication turned off, and there is nothing to store, rotate or expire.

## Providers

| `LLM_PROVIDER` / `EMBED_PROVIDER` | Auth | Used for |
|---|---|---|
| `azure_openai` | Entra ID token (`DefaultAzureCredential`) | Azure deployments (default in `values-azure.yaml`, `values-prod.yaml`) |
| `ray` | none | Local/offline and the self-hosted Ray Serve path (the code default) |
| `openai`, `gemini` | API key | Optional fallback when Azure OpenAI is not available |

Embeddings are 768 dimensions everywhere (`AZURE_OPENAI_EMBED_DIMENSIONS=768`, text-embedding-3-small is Matryoshka),
which is what the 768-dim indexes expect. A client or the ingestion embedder that receives another size raises instead of
writing the vector.

## Running locally

1. **Offline (default).** `LLM_PROVIDER=ray`, `EMBED_PROVIDER=ray` (what `docker-compose.yml` and `azure_dev.sh` use): no
   cloud login, no cost. Tests use fakes and never call a provider.
2. **Against the real Azure OpenAI account, no key.** `az login`, then
   ```bash
   export LLM_PROVIDER=azure_openai EMBED_PROVIDER=azure_openai
   export AZURE_OPENAI_ENDPOINT=$(terraform -chdir=infra/terraform/azure output -raw azure_openai_endpoint)
   ```
   `DefaultAzureCredential` uses your login. Your account needs the "Cognitive Services OpenAI User" role: add your
   Entra object ID to `openai_user_principal_ids` in `terraform.tfvars` and apply once.
3. **A key-based provider.** Set `OPENAI_API_KEY` / `GOOGLE_API_KEY` in the environment.

## Keys and rotation (key-based providers only)

- Keys live in Key Vault (`openai-api-key`, `gemini-api-key`, `tavily-api-key`). The API reads them at start and **re-reads
  them every `SECRET_REFRESH_SECONDS` (default 300)**, rebuilding the clients when one changed, so rotating a key is
  putting the new value in Key Vault, with no restart. `scripts/setup_provider_keys_azure.sh` does that and checks the key
  against the provider first.
- A key supplied as an environment variable is explicit and is never overridden by the vault.
- The Azure bootstrap no longer copies provider keys into `app-env-secret`; Key Vault is the only copy. (The optional
  Gemini key still reaches Ray workers through `ray-gemini-api-key`.)
- A vault outage keeps the current key in use; an empty vault value never wipes a working key.
