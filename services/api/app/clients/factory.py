# services/api/app/clients/factory.py
"""
Factory functions for creating LLM and Embedding clients.
Provider is selected via LLM_PROVIDER / EMBED_PROVIDER env vars,
but can be overridden per-tenant via TenantConfig.

Supported providers:
  LLM:   "ray" (self-hosted vLLM) | "openai" (OpenAI API / compatible) | "azure_openai" (keyless, Entra ID)
  Embed: "ray" (self-hosted BGE)  | "openai" (OpenAI API / compatible) | "gemini" | "azure_openai" (keyless)
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------
# Cache of per-tenant override clients
# (only created on first use for each distinct provider+model combo)
# ---------------------------------------------------------------
_tenant_llm_cache: dict[str, object] = {}
_tenant_embed_cache: dict[str, object] = {}


def create_llm_client(
    provider: str,
    model: Optional[str] = None,
):
    """
    Create an LLM client based on the provider name.

    Args:
        provider: "ray" or "openai"
        model: Optional model name override (used for per-tenant config).

    Returns:
        An LLM client instance with start/close/chat_completion methods.
    """
    provider = provider.lower().strip()

    if provider == "openai":
        from app.clients.openai_llm import OpenAILLMClient

        logger.info(f"Using OpenAI LLM provider (model={model})")
        return OpenAILLMClient(model=model) if model else OpenAILLMClient()

    elif provider == "azure_openai":
        from app.clients.azure_openai import AzureOpenAILLMClient

        logger.info(f"Using Azure OpenAI LLM provider (keyless, deployment={model})")
        return AzureOpenAILLMClient(model=model)

    elif provider == "ray":
        from app.clients.ray_llm import RayLLMClient

        logger.info("Using Ray/vLLM LLM provider")
        return RayLLMClient()

    else:
        raise ValueError(
            f"Unknown LLM_PROVIDER: '{provider}'. "
            f"Supported: 'ray', 'openai', 'azure_openai'"
        )


def create_embed_client(
    provider: str,
    model: Optional[str] = None,
):
    """
    Create an Embedding client based on the provider name.

    Args:
        provider: "ray" or "openai"
        model: Optional model name override (used for per-tenant config).

    Returns:
        An Embed client instance with start/close/embed_query/embed_documents methods.
    """
    provider = provider.lower().strip()

    if provider == "openai":
        from app.clients.openai_embed import OpenAIEmbedClient

        logger.info(f"Using OpenAI Embedding provider (model={model})")
        return OpenAIEmbedClient(model=model) if model else OpenAIEmbedClient()

    elif provider == "azure_openai":
        from app.clients.azure_openai import AzureOpenAIEmbedClient

        logger.info(f"Using Azure OpenAI Embedding provider (keyless, deployment={model})")
        return AzureOpenAIEmbedClient(model=model)

    elif provider == "ray":
        from app.clients.ray_embed import RayEmbedClient

        logger.info("Using Ray/BGE-M3 Embedding provider")
        return RayEmbedClient()

    elif provider == "gemini":
        try:
            from app.clients.gemini_embed import GeminiEmbedClient
        except ImportError as e:
            raise ValueError(f"GeminiEmbedClient not available: {e}")

        logger.info(f"Using Gemini Embedding provider (model={model})")
        return GeminiEmbedClient(model=model) if model else GeminiEmbedClient()

    else:
        raise ValueError(
            f"Unknown EMBED_PROVIDER: '{provider}'. "
            f"Supported: 'ray', 'openai', 'gemini', 'azure_openai'"
        )


def get_tenant_llm_client(
    tenant_llm_provider: Optional[str],
    tenant_llm_model: Optional[str],
    default_client,
):
    """
    Get an LLM client for a specific tenant.

    If the tenant has no overrides, returns the default (global) client.
    If the tenant specifies a different provider or model, returns a
    cached per-tenant client (creating it on first use).

    Args:
        tenant_llm_provider: Per-tenant LLM provider (None=use global).
        tenant_llm_model: Per-tenant LLM model name (None=use global).
        default_client: The global LLM client to fall back to.

    Returns:
        An LLM client instance.
    """
    if not tenant_llm_provider and not tenant_llm_model:
        return default_client

    cache_key = f"{tenant_llm_provider or 'default'}:{tenant_llm_model or 'default'}"
    if cache_key not in _tenant_llm_cache:
        from app.config import settings

        provider = tenant_llm_provider or settings.LLM_PROVIDER
        _tenant_llm_cache[cache_key] = create_llm_client(provider, tenant_llm_model)
    return _tenant_llm_cache[cache_key]


def get_tenant_embed_client(
    tenant_embed_provider: Optional[str],
    tenant_embed_model: Optional[str],
    default_client,
):
    """
    Get an Embedding client for a specific tenant.

    If the tenant has no overrides, returns the default (global) client.
    If the tenant specifies a different provider or model, returns a
    cached per-tenant client (creating it on first use).

    Args:
        tenant_embed_provider: Per-tenant embed provider (None=use global).
        tenant_embed_model: Per-tenant embed model name (None=use global).
        default_client: The global embed client to fall back to.

    Returns:
        An Embed client instance.
    """
    if not tenant_embed_provider and not tenant_embed_model:
        return default_client

    cache_key = f"{tenant_embed_provider or 'default'}:{tenant_embed_model or 'default'}"
    if cache_key not in _tenant_embed_cache:
        from app.config import settings

        provider = tenant_embed_provider or settings.EMBED_PROVIDER
        _tenant_embed_cache[cache_key] = create_embed_client(
            provider, tenant_embed_model
        )
    return _tenant_embed_cache[cache_key]
