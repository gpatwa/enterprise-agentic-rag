"""Read source documents from Azure Blob Storage with the worker's own identity (no storage key).

Ray Data reads ``s3://`` natively; Blob is read here instead. The driver lists the blobs under a prefix (a few names,
cheap) and a Ray callable class fetches each blob's bytes on the workers, so the downloads run in parallel. Credentials
are ``DefaultAzureCredential``: the Ray pods' workload identity (service account ``ray-worker``, role "Storage Blob Data
Contributor" from Terraform), or ``az login`` on a laptop.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Iterable, List, Optional

SCHEME = "az://"


def _service_client(account: str):
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import BlobServiceClient

    return BlobServiceClient(account_url=f"https://{account}.blob.core.windows.net", credential=DefaultAzureCredential())


def list_blob_paths(account: str, container: str, prefix: str, service: Optional[Any] = None) -> List[str]:
    """``az://container/name`` for every blob under ``prefix`` (a "directory" or a single blob name)."""
    service = service or _service_client(account)
    names = [b.name for b in service.get_container_client(container).list_blobs(name_starts_with=prefix or None)]
    return [f"{SCHEME}{container}/{name}" for name in sorted(names) if not name.endswith("/")]


def split_path(path: str) -> tuple[str, str]:
    """``az://container/some/blob.pdf`` -> ``("container", "some/blob.pdf")``."""
    if not path.startswith(SCHEME):
        raise ValueError(f"not an Azure Blob path: {path!r}")
    container, _, name = path[len(SCHEME) :].partition("/")
    if not container or not name:
        raise ValueError(f"cannot split {path!r} into container and blob name")
    return container, name


class AzureBlobFetcher:
    """Ray Data callable class: adds a ``bytes`` column with each blob's content, keeping ``path``."""

    def __init__(self, account: Optional[str] = None):
        self.account = account or os.environ["AZURE_STORAGE_ACCOUNT_NAME"]
        self._service = None

    def __call__(self, batch: Dict[str, Any]) -> Dict[str, Any]:
        if self._service is None:
            self._service = _service_client(self.account)
        contents: List[bytes] = []
        for path in batch["path"]:
            container, name = split_path(str(path))
            contents.append(self._service.get_blob_client(container, name).download_blob().readall())
        batch["bytes"] = contents
        return batch


def source_paths(paths: Iterable[str]) -> List[Dict[str, str]]:
    return [{"path": p} for p in paths]
