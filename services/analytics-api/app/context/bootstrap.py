"""Product startup bootstrap for the local analytics context plane."""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import httpx

from app.context.index import OpenSearchContextIndex
from app.context.quality import evaluate_context_quality
from app.semantic_registry import SemanticRegistry
from packages.platform_contracts.context_snapshot import ContextSnapshot
from packages.platform_contracts.metadata import MetadataAsset, MetadataColumn

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContextBootstrapState:
    configured: bool = False
    ready: bool = False
    dashboard_configured: bool = False
    dashboard_ready: bool = False
    indexed_documents: int = 0
    snapshot_id: str | None = None
    error: str | None = None


class ContextBootstrap:
    """Provision the context index and local dashboard objects at service boot."""

    def __init__(self, config, client: httpx.Client | None = None):
        self.config = config
        self.client = client
        self.state = ContextBootstrapState(
            configured=bool(config.context_bootstrap_enabled and config.opensearch_url),
            dashboard_configured=bool(config.dashboards_url),
        )
        self.index: OpenSearchContextIndex | None = None

    def start(self) -> ContextBootstrapState:
        if not self.state.configured:
            return self.state
        if self.client is None:
            self.client = httpx.Client(timeout=10.0)
        try:
            self._wait_for_opensearch()
            self.index = OpenSearchContextIndex(
                self.config.opensearch_url, self.config.context_index, self.client
            )
            self.index.ensure_index()
            snapshot = build_registry_snapshot(self.config.semantic_registry_path)
            indexed_documents = 0
            snapshot_id = None
            if snapshot:
                report = evaluate_context_quality(snapshot, minimum_provenance=1.0)
                if not report.actionable:
                    raise RuntimeError(
                        "context bootstrap blocked: " + ", ".join(report.blocking_reasons)
                    )
                indexed_documents = self.index.index_snapshot(snapshot)
                snapshot_id = snapshot.snapshot_id
            dashboard_ready = self._ensure_dashboard_index_pattern()
            self.state = ContextBootstrapState(
                configured=True, ready=True,
                dashboard_configured=bool(self.config.dashboards_url),
                dashboard_ready=dashboard_ready, indexed_documents=indexed_documents,
                snapshot_id=snapshot_id,
            )
        except Exception as exc:  # startup health reports the failure; API can still expose diagnostics
            logger.exception("analytics context bootstrap failed")
            self.state = ContextBootstrapState(
                configured=True, ready=False,
                dashboard_configured=bool(self.config.dashboards_url),
                error=str(exc),
            )
        return self.state

    def close(self) -> None:
        if self.client:
            self.client.close()

    def _wait_for_opensearch(self) -> None:
        for _ in range(30):
            try:
                response = self.client.get(f"{self.config.opensearch_url.rstrip('/')}/_cluster/health")
                if response.is_success:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        raise RuntimeError("OpenSearch did not become healthy within 15 seconds")

    def _ensure_dashboard_index_pattern(self) -> bool:
        if not self.config.dashboards_url:
            return False
        pattern_id = quote(self.config.context_index, safe="")
        endpoint = f"{self.config.dashboards_url.rstrip('/')}/api/saved_objects/index-pattern/{pattern_id}"
        for _ in range(30):
            response = self.client.get(endpoint)
            if response.status_code == 200:
                return True
            if response.status_code == 404:
                response = self.client.post(
                    endpoint, headers={"osd-xsrf": "true"},
                    json={"attributes": {"title": self.config.context_index}},
                )
                if response.status_code in {200, 201, 409}:
                    return True
                if response.status_code >= 500:
                    time.sleep(0.5)
                    continue
            elif response.status_code >= 400:
                if response.status_code < 500:
                    response.raise_for_status()
            time.sleep(0.5)
        return False


def build_registry_snapshot(root: Path | str) -> ContextSnapshot | None:
    """Create a local certified snapshot from the first certified Git contract."""
    entries = [entry for entry in SemanticRegistry(root).list_entries() if entry.state == "certified" and entry.document]
    if not entries:
        return None
    document = sorted(entries, key=lambda entry: (entry.contract_id or "", entry.contract_version or ""))[0].document
    contract = document.contract
    fields_by_dataset: dict[str, list[MetadataColumn]] = {dataset.id: [] for dataset in contract.datasets}
    for field in contract.fields:
        fields_by_dataset.setdefault(field.dataset_id, []).append(
            MetadataColumn(
                name=field.physical_name, data_type=field.data_type,
                classification=field.classification,
            )
        )
    observed_at = datetime.now(timezone.utc)
    assets = tuple(
        MetadataAsset(
            id=dataset.id, display_name=dataset.display_name, physical_name=dataset.physical_name,
            provider="semantic-registry", description=dataset.description,
            owner_ids=list(dataset.owner_ids), tags=[contract.domain], certified=True,
            columns=fields_by_dataset.get(dataset.id, []),
            source_version=f"{contract.id}@{contract.version}", observed_at=observed_at,
        )
        for dataset in sorted(contract.datasets, key=lambda item: item.id)
    )
    source_fingerprint = hashlib.sha256(
        json.dumps(document.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return ContextSnapshot.build(
        snapshot_id=f"semantic:{contract.id}:{contract.version}", tenant_id=contract.tenant_id,
        source_fingerprints=(source_fingerprint,), metadata_assets=assets,
        semantic_contract_ids=(f"{contract.id}@{contract.version}",),
        created_at=observed_at,
    )
