"""Where built product subsets live: a local directory, or a private Azure Blob container (Entra auth only).

A subset is three files (products, quarantine, manifest). Publishing is create-only (``If-None-Match: *``) and the
manifest is written last, so a subset with a manifest is complete and a published subset can never be overwritten.
Pulling downloads to a temporary directory, verifies the manifest checksum, and only then moves it into place.
The Blob store speaks the REST API directly over httpx (no SDK, no storage key, no SAS): access comes from a bearer
token obtained from the managed identity (on Azure) or the Azure CLI (on a laptop). Tokens, blob contents and
response bodies are never logged or put in error messages.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable, Protocol
from urllib.parse import quote, urlparse

import httpx

from app.ingest.pipeline import MANIFEST_NAME, PRODUCTS_NAME, QUARANTINE_NAME, IngestError, verify_subset

FILES = (PRODUCTS_NAME, QUARANTINE_NAME, MANIFEST_NAME)  # manifest last: its presence marks a complete subset
STORAGE_RESOURCE = "https://storage.azure.com/"
BLOB_API_VERSION = "2023-11-03"


class StoreError(IngestError):
    """The store could not complete the operation; messages carry statuses and names only."""


class SubsetStore(Protocol):
    def push(self, subset_dir: Path, name: str) -> None: ...

    def pull(self, name: str, dest: Path) -> None: ...

    def list(self) -> list[str]: ...


def _valid_name(name: str) -> str:
    if not name or name.startswith(("/", ".")) or ".." in name or "\\" in name or any(c in name for c in ':*?"<>|'):
        raise StoreError(f"invalid subset name: {name!r}")
    return name.strip("/")


def _require_pushable(subset_dir: Path) -> None:
    verify_subset(subset_dir)  # refuses a drifted or incomplete subset before anything is uploaded


def _finish_pull(staging: Path, dest: Path) -> None:
    try:
        verify_subset(staging)
    except IngestError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staging, dest)


class LocalStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def push(self, subset_dir: Path, name: str) -> None:
        name = _valid_name(name)
        _require_pushable(subset_dir)
        target = self.root / name
        if (target / MANIFEST_NAME).exists():
            raise StoreError(f"subset {name} already exists")
        target.mkdir(parents=True, exist_ok=True)
        for file in FILES:
            shutil.copyfile(subset_dir / file, target / file)

    def pull(self, name: str, dest: Path) -> None:
        name = _valid_name(name)
        source = self.root / name
        if not (source / MANIFEST_NAME).exists():
            raise StoreError(f"subset {name} not found or incomplete")
        if dest.exists():
            raise StoreError(f"{dest} already exists; choose a new directory")
        dest.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(dir=dest.parent, prefix=".pull-"))
        for file in FILES:
            shutil.copyfile(source / file, staging / file)
        _finish_pull(staging, dest)

    def list(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(p.parent.relative_to(self.root).as_posix() for p in self.root.rglob(MANIFEST_NAME))


def managed_identity_token(transport: httpx.BaseTransport | None = None) -> str:
    """A storage token from the Container Apps/App Service endpoint, or the VM metadata service."""
    client_id = os.environ.get("AZURE_CLIENT_ID")
    with httpx.Client(timeout=5.0, transport=transport) as http:
        endpoint, header = os.environ.get("IDENTITY_ENDPOINT"), os.environ.get("IDENTITY_HEADER")
        if endpoint and header:
            params = {"resource": STORAGE_RESOURCE, "api-version": "2019-08-01"}
            if client_id:
                params["client_id"] = client_id
            response = http.get(endpoint, params=params, headers={"X-IDENTITY-HEADER": header})
        else:
            params = {"resource": STORAGE_RESOURCE, "api-version": "2018-02-01"}
            if client_id:
                params["client_id"] = client_id
            response = http.get(
                "http://169.254.169.254/metadata/identity/oauth2/token", params=params, headers={"Metadata": "true"}
            )
    if response.status_code != 200:
        raise StoreError(f"managed identity token request failed (HTTP {response.status_code})")
    try:
        return str(response.json()["access_token"])
    except (ValueError, KeyError) as exc:
        raise StoreError("managed identity token response was not in the expected shape") from exc


def az_cli_token() -> str:
    """A storage token for the signed-in Azure CLI user (laptop use)."""
    result = subprocess.run(
        ["az", "account", "get-access-token", "--resource", STORAGE_RESOURCE, "--query", "accessToken", "-o", "tsv"],
        capture_output=True,
        text=True,
    )
    token = result.stdout.strip()
    if result.returncode != 0 or not token:
        raise StoreError("could not get a storage token from the Azure CLI (are you signed in?)")
    return token


def default_token_provider() -> Callable[[], str]:
    return managed_identity_token if os.environ.get("IDENTITY_ENDPOINT") else az_cli_token


class AzureBlobStore:
    def __init__(
        self,
        account: str,
        container: str,
        prefix: str = "subsets",
        *,
        token_provider: Callable[[], str] | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 120.0,
    ) -> None:
        if not account.isalnum() or not account.islower() or not 3 <= len(account) <= 24:
            raise StoreError("invalid storage account name")
        self._base = f"https://{account}.blob.core.windows.net/{quote(container)}"
        self._prefix = prefix.strip("/")
        self._token = token_provider or default_token_provider()
        self._http = httpx.Client(timeout=timeout, transport=transport)

    def _headers(self, token: str, **extra: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}", "x-ms-version": BLOB_API_VERSION, **extra}

    def _blob_url(self, name: str, file: str) -> str:
        return f"{self._base}/{quote(self._prefix + '/' + name + '/' + file)}"

    @staticmethod
    def _fail(action: str, response: httpx.Response) -> StoreError:
        return StoreError(f"blob {action} failed (HTTP {response.status_code})")

    def push(self, subset_dir: Path, name: str) -> None:
        name = _valid_name(name)
        _require_pushable(subset_dir)
        token = self._token()
        if self._http.head(self._blob_url(name, MANIFEST_NAME), headers=self._headers(token)).status_code == 200:
            raise StoreError(f"subset {name} already exists")
        for file in FILES:
            response = self._http.put(
                self._blob_url(name, file),
                content=(subset_dir / file).read_bytes(),
                headers=self._headers(
                    token,
                    **{"x-ms-blob-type": "BlockBlob", "If-None-Match": "*", "Content-Type": "application/octet-stream"},
                ),
            )
            if response.status_code in (409, 412):
                raise StoreError(f"subset {name} already has {file}; nothing was overwritten")
            if response.status_code not in (200, 201):
                raise self._fail("upload", response)

    def pull(self, name: str, dest: Path) -> None:
        name = _valid_name(name)
        if dest.exists():
            raise StoreError(f"{dest} already exists; choose a new directory")
        token = self._token()
        if self._http.head(self._blob_url(name, MANIFEST_NAME), headers=self._headers(token)).status_code != 200:
            raise StoreError(f"subset {name} not found or incomplete")
        dest.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(dir=dest.parent, prefix=".pull-"))
        try:
            for file in FILES:
                with self._http.stream("GET", self._blob_url(name, file), headers=self._headers(token)) as response:
                    if response.status_code != 200:
                        raise self._fail("download", response)
                    with (staging / file).open("wb") as handle:
                        for chunk in response.iter_bytes():
                            handle.write(chunk)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        _finish_pull(staging, dest)

    def list(self) -> list[str]:
        token = self._token()
        names: list[str] = []
        marker = ""
        while True:
            params = {"restype": "container", "comp": "list", "prefix": f"{self._prefix}/"}
            if marker:
                params["marker"] = marker
            response = self._http.get(self._base, params=params, headers=self._headers(token))
            if response.status_code != 200:
                raise self._fail("list", response)
            root = ET.fromstring(response.text)
            for blob in root.iter("Name"):
                text = blob.text or ""
                if text.endswith(f"/{MANIFEST_NAME}"):
                    names.append(text[len(self._prefix) + 1 : -len(MANIFEST_NAME) - 1])
            marker = (root.findtext("NextMarker") or "").strip()
            if not marker:
                return sorted(names)


def open_store(location: str, *, token_provider: Callable[[], str] | None = None) -> SubsetStore:
    """``az://<account>/<container>[/<prefix>]`` for Azure Blob, anything else is a local directory."""
    if location.startswith("az://"):
        parsed = urlparse(location)
        parts = [p for p in parsed.path.split("/") if p]
        if not parsed.netloc or not parts:
            raise StoreError("expected az://<account>/<container>[/<prefix>]")
        return AzureBlobStore(parsed.netloc, parts[0], "/".join(parts[1:]) or "subsets", token_provider=token_provider)
    return LocalStore(Path(location))
