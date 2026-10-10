"""Local safety policy for optional immersive-discovery intelligence.

This module is a policy boundary, not a model client. Untrusted catalog,
user, and query text is treated as data, while the deterministic IMD-071
adapter remains the fail-closed path whenever optional intelligence is not
permitted.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.intelligence.adapter import BoundedIntentAdapter, IntentResolution

POLICY_VERSION = "imd-intelligence-safety-v1"
PROVIDER_VERSION = "provider-neutral-v1"
PROMPT_VERSION = "prompt-boundary-v1"
CACHE_VERSION = "cache-key-v1"
ROUTING_VERSION = "routing-policy-v1"
DEFAULT_INPUT_TOKEN_BUDGET = 2_048
DEFAULT_OUTPUT_TOKEN_BUDGET = 512
MAX_TEXT_CHARS = 8_000
MAX_LOG_VALUE_CHARS = 128

_INJECTION_PATTERNS = (
    re.compile(r"\b(?:ignore|disregard|override)\s+(?:all\s+)?(?:previous|prior|above)\s+instructions?\b", re.I),
    re.compile(r"\b(?:system|developer)\s+prompt\b", re.I),
    re.compile(r"\b(?:reveal|print|dump)\s+(?:the\s+)?(?:policy|secret|token|credential)s?\b", re.I),
    re.compile(r"\b(?:tool|function)\s*(?:call|execution)\b", re.I),
)
_SENSITIVE_FIELD = re.compile(r"(?:token|secret|password|credential|authorization|cookie|ssn|email|phone)", re.I)


class SafetyDisposition(StrEnum):
    ALLOW = "allow"
    QUARANTINE = "quarantine"
    MODEL_OFF = "model_off"


class SafetyMetadata(BaseModel):
    """Reproducibility metadata with no prompt or source text."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    policy_version: str = POLICY_VERSION
    provider_version: str = PROVIDER_VERSION
    prompt_version: str = PROMPT_VERSION
    cache_version: str = CACHE_VERSION
    routing_version: str = ROUTING_VERSION


class SafetyDecision(BaseModel):
    """A bounded decision that callers can use without inspecting raw text."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    disposition: SafetyDisposition
    reason: str = Field(min_length=1, max_length=64)
    redacted_text: str = Field(default="", max_length=MAX_TEXT_CHARS)
    instruction_text: str = Field(default="", max_length=1)
    estimated_input_tokens: int = Field(ge=0)
    metadata: SafetyMetadata = Field(default_factory=SafetyMetadata)


class IntelligenceSafetyPolicy:
    """Apply bounded safety rules and provide an immediate model kill switch."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        kill_switch: bool = False,
        input_token_budget: int = DEFAULT_INPUT_TOKEN_BUDGET,
        output_token_budget: int = DEFAULT_OUTPUT_TOKEN_BUDGET,
    ) -> None:
        if input_token_budget <= 0 or output_token_budget <= 0:
            raise ValueError("token budgets must be positive")
        self.enabled = enabled
        self.kill_switch = kill_switch
        self.input_token_budget = input_token_budget
        self.output_token_budget = output_token_budget

    @property
    def model_off(self) -> bool:
        return not self.enabled or self.kill_switch

    def inspect(self, text: str, *, field_name: str = "text") -> SafetyDecision:
        """Sanitize untrusted text; it is never returned as an instruction."""
        if not isinstance(text, str):
            raise TypeError(f"{field_name} must be text")
        bounded = text[:MAX_TEXT_CHARS]
        estimated = _estimate_tokens(bounded)
        if self.model_off:
            return self._decision(SafetyDisposition.MODEL_OFF, "kill_switch", bounded, estimated)
        if estimated > self.input_token_budget:
            return self._decision(SafetyDisposition.QUARANTINE, "input_budget", "", estimated)
        redacted = redact_text(bounded)
        if any(pattern.search(redacted) for pattern in _INJECTION_PATTERNS):
            return self._decision(SafetyDisposition.QUARANTINE, "prompt_injection", "", estimated)
        return self._decision(SafetyDisposition.ALLOW, "accepted", redacted, estimated)

    def inspect_fields(self, fields: Mapping[str, object]) -> SafetyDecision:
        """Inspect only text values and redact sensitive named fields."""
        parts: list[str] = []
        for name, value in fields.items():
            if _SENSITIVE_FIELD.search(name):
                parts.append("[REDACTED]")
            elif isinstance(value, str):
                parts.append(value)
        return self.inspect(" ".join(parts), field_name="payload")

    def inspect_output(self, text: str) -> SafetyDecision:
        """Apply the smaller provider-output budget before accepting a result."""
        decision = self.inspect(text, field_name="output")
        if decision.disposition is not SafetyDisposition.ALLOW:
            return decision
        if decision.estimated_input_tokens > self.output_token_budget:
            return self._decision(
                SafetyDisposition.QUARANTINE,
                "output_budget",
                "",
                decision.estimated_input_tokens,
            )
        return decision

    def resolve_intent(
        self,
        adapter: BoundedIntentAdapter,
        raw_query: str,
        *,
        explicit_catalog_ids: Sequence[str] = (),
        caller_context: Mapping[str, object] | None = None,
    ) -> IntentResolution:
        """Force IMD-071 deterministic fallback while the switch is tripped."""
        selected = BoundedIntentAdapter() if self.model_off else adapter
        return selected.resolve(
            raw_query,
            explicit_catalog_ids=explicit_catalog_ids,
            caller_context=caller_context,
        )

    def call_allowed(self) -> bool:
        """Return whether optional enrichment, judge, or refinement may run."""
        return not self.model_off

    def cache_key(self, tenant_id: str, *stable_parts: str) -> str:
        """Hash tenant/version material; raw tenant or content never appears in the key."""
        if not tenant_id or not tenant_id.strip():
            raise ValueError("tenant_id is required")
        if any(not isinstance(part, str) for part in stable_parts):
            raise TypeError("cache key parts must be text")
        material = "|".join((CACHE_VERSION, POLICY_VERSION, tenant_id, *stable_parts))
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def _decision(
        self,
        disposition: SafetyDisposition,
        reason: str,
        text: str,
        estimated: int,
    ) -> SafetyDecision:
        return SafetyDecision(
            disposition=disposition,
            reason=reason,
            redacted_text=text,
            instruction_text="",
            estimated_input_tokens=estimated,
        )


def _estimate_tokens(text: str) -> int:
    return (len(text) + 3) // 4


def redact_text(text: str) -> str:
    """Remove common secret-shaped values before optional processing or logs."""
    redacted = re.sub(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]+", "[REDACTED]", text)
    redacted = re.sub(r"(?i)(?:api[_ -]?key|token|secret|password)\s*[:=]\s*[^\s,;]+", "[REDACTED]", redacted)
    return redacted[:MAX_TEXT_CHARS]


__all__ = [
    "CACHE_VERSION",
    "DEFAULT_INPUT_TOKEN_BUDGET",
    "DEFAULT_OUTPUT_TOKEN_BUDGET",
    "IntelligenceSafetyPolicy",
    "POLICY_VERSION",
    "PROMPT_VERSION",
    "SafetyDecision",
    "SafetyDisposition",
    "redact_text",
]
