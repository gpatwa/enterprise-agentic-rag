"""Filesystem registry for reviewed semantic-contract documents.

The directory is intended to be committed to Git. This module performs no Git
write operations: normal pull-request review, history, and rollback remain the
source of truth for registry changes.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from packages.platform_contracts.semantic import SemanticRegistryDocument

RegistryState = Literal["draft", "certified", "deprecated", "invalid"]


class SemanticContractNotFoundError(LookupError):
    """Raised when an exact semantic contract version cannot be resolved."""


@dataclass(frozen=True)
class SemanticRegistryEntry:
    path: Path
    state: RegistryState
    contract_id: str | None = None
    contract_version: str | None = None
    document: SemanticRegistryDocument | None = None
    error: str | None = None


class SemanticRegistry:
    """Load semantic documents from a Git-managed directory without mutation."""

    def __init__(self, root: Path | str):
        self.root = Path(root)

    def list_entries(self) -> list[SemanticRegistryEntry]:
        if not self.root.exists():
            return []
        return [self._load_entry(path) for path in sorted(self.root.rglob("*.json"))]

    def get(self, contract_id: str, version: str) -> SemanticRegistryDocument:
        matches = [
            entry
            for entry in self.list_entries()
            if entry.contract_id == contract_id and entry.contract_version == version
        ]
        if not matches:
            raise SemanticContractNotFoundError(f"Semantic contract {contract_id}@{version} was not found")
        if len(matches) > 1:
            raise SemanticContractNotFoundError(
                f"Semantic contract {contract_id}@{version} is ambiguous"
            )
        entry = matches[0]
        if entry.document is None:
            raise SemanticContractNotFoundError(
                f"Semantic contract {contract_id}@{version} is invalid"
            )
        return entry.document

    def get_certified(self, contract_id: str, version: str) -> SemanticRegistryDocument:
        document = self.get(contract_id, version)
        if document.lifecycle != "certified":
            raise SemanticContractNotFoundError(
                f"Semantic contract {contract_id}@{version} is not certified"
            )
        return document

    def _load_entry(self, path: Path) -> SemanticRegistryEntry:
        raw_document: object = None
        try:
            raw_document = json.loads(path.read_text())
            document = SemanticRegistryDocument.model_validate(raw_document)
        except (OSError, json.JSONDecodeError, ValidationError):
            return SemanticRegistryEntry(
                path=path,
                state="invalid",
                contract_id=_contract_id(raw_document),
                contract_version=_contract_version(raw_document),
                error="invalid semantic contract document",
            )
        return SemanticRegistryEntry(
            path=path,
            state=document.lifecycle,
            contract_id=document.contract.id,
            contract_version=document.contract.version,
            document=document,
        )


def _contract_id(raw_document: object) -> str | None:
    if isinstance(raw_document, dict):
        contract = raw_document.get("contract")
        if isinstance(contract, dict) and isinstance(contract.get("id"), str):
            return contract["id"]
    return None


def _contract_version(raw_document: object) -> str | None:
    if isinstance(raw_document, dict):
        contract = raw_document.get("contract")
        if isinstance(contract, dict) and isinstance(contract.get("version"), str):
            return contract["version"]
    return None
