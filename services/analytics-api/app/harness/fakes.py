"""Small provider fakes with deterministic, contract-shaped behavior."""
from __future__ import annotations

import copy
from typing import Any

from packages.platform_contracts.metadata import MetadataSnapshot
from packages.platform_contracts.security import AnalyticsIdentity, AuthorizationDecision
from packages.platform_contracts.semantic import SemanticContract, SemanticRegistryDocument


class FakeIdentityProvider:
    def __init__(self, identities: dict[tuple[str, str], AnalyticsIdentity]):
        self.identities = identities

    def resolve(self, tenant_id: str, user_id: str) -> AnalyticsIdentity:
        try:
            identity = self.identities[(tenant_id, user_id)]
        except KeyError as exc:
            raise LookupError("fake identity was not registered") from exc
        return identity.model_copy(deep=True)


class FakeCatalogProvider:
    def __init__(self, snapshots: dict[str, MetadataSnapshot]):
        self.snapshots = snapshots

    def get_snapshot(self, asset_name: str) -> MetadataSnapshot:
        try:
            return self.snapshots[asset_name].model_copy(deep=True)
        except KeyError as exc:
            raise LookupError(f"fake catalog asset not found: {asset_name}") from exc


class FakeSemanticRegistryProvider:
    def __init__(self, documents: dict[tuple[str, str], SemanticRegistryDocument]):
        self.documents = documents

    def get_contract(self, contract_id: str, version: str) -> SemanticContract:
        document = self.documents.get((contract_id, version))
        if document is None or document.lifecycle != "certified":
            raise LookupError("fake semantic contract is not certified")
        return document.contract.model_copy(deep=True)


class FakeModelProvider:
    def __init__(self, responses: dict[str, dict[str, Any]]):
        self.responses = copy.deepcopy(responses)
        self.calls: list[str] = []

    def complete(self, prompt: str) -> dict[str, Any]:
        self.calls.append(prompt)
        try:
            return copy.deepcopy(self.responses[prompt])
        except KeyError as exc:
            raise LookupError("fake model response not registered") from exc


class FakePolicyProvider:
    def __init__(self, decisions: dict[tuple[str, str], AuthorizationDecision]):
        self.decisions = decisions

    def decide(self, tenant_id: str, purpose: str) -> AuthorizationDecision:
        try:
            return self.decisions[(tenant_id, purpose)].model_copy(deep=True)
        except KeyError as exc:
            raise LookupError("fake policy decision not registered") from exc


class FakeWarehouseProvider:
    def __init__(self, results: dict[str, list[dict[str, Any]]]):
        self.results = copy.deepcopy(results)
        self.queries: list[str] = []

    def execute(self, sql: str) -> list[dict[str, Any]]:
        self.queries.append(sql)
        try:
            return copy.deepcopy(self.results[sql])
        except KeyError as exc:
            raise LookupError("fake warehouse result not registered") from exc
