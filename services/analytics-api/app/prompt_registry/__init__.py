"""Immutable prompt and example candidate registry (ADS-054). Nothing in the runtime reads it."""

from app.prompt_registry.baseline import BASELINES, INTENT_PLACEHOLDERS, INTENT_PROMPT_NAME, PINNED_FINGERPRINTS
from app.prompt_registry.examples import EXAMPLE_NAME, ExampleCandidateService
from app.prompt_registry.store import PromptRegistry, RegistryConflictError, RegistryError, RegistryNotFoundError

__all__ = [
    "BASELINES",
    "EXAMPLE_NAME",
    "INTENT_PLACEHOLDERS",
    "INTENT_PROMPT_NAME",
    "PINNED_FINGERPRINTS",
    "ExampleCandidateService",
    "PromptRegistry",
    "RegistryConflictError",
    "RegistryError",
    "RegistryNotFoundError",
]
