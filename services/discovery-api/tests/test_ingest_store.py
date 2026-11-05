"""Subset stores: local directory and Azure Blob (REST, Entra bearer auth), against an in-memory fake of the service."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

import httpx
import pytest

from app.ingest import (
    AzureBlobStore,
    IngestError,
    LocalStore,
    ProductProvenance,
    StoreError,
    ingest,
    open_store,
    write_subset,
)
from app.ingest import store as store_module
from app.ingest.__main__ import main as cli_main

NOW = datetime(2026, 11, 5, tzinfo=timezone.utc)
TOKEN = "tok-secret-abc"
ACCOUNT, CONTAINER = "discoverypildata1a2b3c", "datasets"


def _built(tmp_path: Path, name: str = "built") -> Path:
    with (tmp_path / "p.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["product_id", "product_locale", "product_title"])
        for i in range(8):
            writer.writerow([f"P{i}", "us", f"widget {i}"])
    with (tmp_path / "e.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["product_id", "product_locale", "small_version"])
        for i in range(8):
            writer.writerow([f"P{i}", "us", "1"])
    provenance = ProductProvenance(dataset="fixture", dataset_version="t", citation="synthetic", synthetic=True)
    out = tmp_path / name
    write_subset(ingest(tmp_path / "p.csv", tmp_path / "e.csv", provenance=provenance, now=NOW), out)
    return out


class FakeBlob:
    """Enough of the Blob REST API: auth, create-only PUT, HEAD, GET, and a paged container listing."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}
        self.requests: list[httpx.Request] = []
        self.page_size = 2

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.headers.get("authorization") != f"Bearer {TOKEN}" or "x-ms-version" not in request.headers:
            return httpx.Response(403, text="<Error>AuthenticationFailed secret-detail</Error>")
        path = unquote(request.url.path)
        prefix = f"/{CONTAINER}"
        if path == prefix and request.method == "GET":
            return self._list(request)
        key = path[len(prefix) + 1 :]
        if request.method == "PUT":
            if request.headers.get("if-none-match") == "*" and key in self.blobs:
                return httpx.Response(409, text="BlobAlreadyExists")
            assert request.headers["x-ms-blob-type"] == "BlockBlob"
            self.blobs[key] = request.content
            return httpx.Response(201)
        if key not in self.blobs:
            return httpx.Response(404)
        return httpx.Response(200, content=b"" if request.method == "HEAD" else self.blobs[key])

    def _list(self, request: httpx.Request) -> httpx.Response:
        wanted = request.url.params["prefix"]
        names = sorted(k for k in self.blobs if k.startswith(wanted))
        start = int(request.url.params.get("marker", "0") or 0)
        page = names[start : start + self.page_size]
        more = start + self.page_size < len(names)
        body = "".join(f"<Blob><Name>{n}</Name></Blob>" for n in page)
        marker = f"<NextMarker>{start + self.page_size}</NextMarker>" if more else "<NextMarker />"
        return httpx.Response(200, text=f"<EnumerationResults><Blobs>{body}</Blobs>{marker}</EnumerationResults>")


def _blob_store(fake: FakeBlob, token: str = TOKEN) -> AzureBlobStore:
    return AzureBlobStore(
        ACCOUNT, CONTAINER, "subsets", token_provider=lambda: token, transport=httpx.MockTransport(fake)
    )


# ---- local store ------------------------------------------------------------------------------------------


def test_local_round_trip_is_verified_and_listed(tmp_path: Path) -> None:
    built = _built(tmp_path)
    store = LocalStore(tmp_path / "store")
    store.push(built, "us-25k-seed7")
    assert store.list() == ["us-25k-seed7"]
    store.pull("us-25k-seed7", tmp_path / "back")
    assert (tmp_path / "back" / "products.jsonl").read_bytes() == (built / "products.jsonl").read_bytes()


def test_local_push_never_overwrites_and_pull_never_clobbers(tmp_path: Path) -> None:
    built = _built(tmp_path)
    store = LocalStore(tmp_path / "store")
    store.push(built, "a")
    with pytest.raises(StoreError, match="already exists"):
        store.push(built, "a")
    store.pull("a", tmp_path / "out")
    with pytest.raises(StoreError, match="already exists"):
        store.pull("a", tmp_path / "out")


def test_a_drifted_subset_is_not_pushed(tmp_path: Path) -> None:
    built = _built(tmp_path)
    path = built / "products.jsonl"
    path.write_text("\n".join(path.read_text().splitlines()[:-1]) + "\n", encoding="utf-8")
    with pytest.raises(IngestError, match="drift"):
        LocalStore(tmp_path / "store").push(built, "bad")
    assert LocalStore(tmp_path / "store").list() == []


def test_an_incomplete_subset_without_a_manifest_is_invisible_and_not_pullable(tmp_path: Path) -> None:
    store = LocalStore(tmp_path / "store")
    (tmp_path / "store" / "half").mkdir(parents=True)
    (tmp_path / "store" / "half" / "products.jsonl").write_text("{}", encoding="utf-8")
    assert store.list() == []
    with pytest.raises(StoreError, match="incomplete"):
        store.pull("half", tmp_path / "out")


def test_a_corrupted_stored_subset_fails_verification_and_leaves_nothing_behind(tmp_path: Path) -> None:
    built = _built(tmp_path)
    store = LocalStore(tmp_path / "store")
    store.push(built, "a")
    stored = tmp_path / "store" / "a" / "products.jsonl"
    stored.write_text("\n".join(stored.read_text().splitlines()[:-1]) + "\n", encoding="utf-8")
    with pytest.raises(IngestError, match="drift"):
        store.pull("a", tmp_path / "out")
    assert not (tmp_path / "out").exists() and not list(tmp_path.glob(".pull-*"))


@pytest.mark.parametrize("name", ["", "../x", "a/../b", "/abs", ".hidden", "a\\b", "a:b"])
def test_unsafe_names_are_refused(tmp_path: Path, name: str) -> None:
    with pytest.raises(StoreError, match="invalid subset name"):
        LocalStore(tmp_path / "s").pull(name, tmp_path / "o")


# ---- Azure Blob store -------------------------------------------------------------------------------------


def test_blob_push_pull_round_trip_with_bearer_auth_and_manifest_last(tmp_path: Path) -> None:
    built = _built(tmp_path)
    fake = FakeBlob()
    store = _blob_store(fake)
    store.push(built, "us-25k-seed7")
    puts = [r for r in fake.requests if r.method == "PUT"]
    assert [unquote(r.url.path).rsplit("/", 1)[1] for r in puts] == [
        "products.jsonl",
        "quarantine.jsonl",
        "manifest.json",
    ]
    assert all(r.headers["authorization"] == f"Bearer {TOKEN}" and r.headers["if-none-match"] == "*" for r in puts)
    assert puts[0].url.host == f"{ACCOUNT}.blob.core.windows.net" and puts[0].url.scheme == "https"
    store.pull("us-25k-seed7", tmp_path / "back")
    assert (tmp_path / "back" / "manifest.json").read_bytes() == (built / "manifest.json").read_bytes()


def test_blob_push_never_overwrites(tmp_path: Path) -> None:
    built = _built(tmp_path)
    fake = FakeBlob()
    store = _blob_store(fake)
    store.push(built, "a")
    before = dict(fake.blobs)
    with pytest.raises(StoreError, match="already exists"):
        store.push(built, "a")
    assert fake.blobs == before


def test_blob_create_only_conflict_midway_is_reported_and_nothing_is_replaced(tmp_path: Path) -> None:
    built = _built(tmp_path)
    fake = FakeBlob()
    fake.blobs["subsets/a/products.jsonl"] = b"existing"
    with pytest.raises(StoreError, match="nothing was overwritten"):
        _blob_store(fake).push(built, "a")
    assert fake.blobs["subsets/a/products.jsonl"] == b"existing"


def test_blob_pull_of_an_incomplete_subset_is_refused(tmp_path: Path) -> None:
    fake = FakeBlob()
    fake.blobs["subsets/half/products.jsonl"] = b"{}"
    with pytest.raises(StoreError, match="incomplete"):
        _blob_store(fake).pull("half", tmp_path / "out")


def test_blob_corruption_is_caught_and_cleaned_up(tmp_path: Path) -> None:
    built = _built(tmp_path)
    fake = FakeBlob()
    store = _blob_store(fake)
    store.push(built, "a")
    lines = fake.blobs["subsets/a/products.jsonl"].decode().splitlines()
    fake.blobs["subsets/a/products.jsonl"] = ("\n".join(lines[:-1]) + "\n").encode()
    with pytest.raises(IngestError, match="drift"):
        store.pull("a", tmp_path / "out")
    assert not (tmp_path / "out").exists() and not list(tmp_path.glob(".pull-*"))


def test_blob_list_pages_and_returns_only_complete_subsets(tmp_path: Path) -> None:
    built = _built(tmp_path)
    fake = FakeBlob()
    store = _blob_store(fake)
    for name in ("a", "b", "c"):
        store.push(built, name)
    fake.blobs["subsets/partial/products.jsonl"] = b"x"
    assert store.list() == ["a", "b", "c"]
    assert sum(1 for r in fake.requests if r.method == "GET" and r.url.params.get("comp") == "list") >= 2


def test_blob_errors_carry_the_status_only_never_the_token_or_body(tmp_path: Path) -> None:
    built = _built(tmp_path)
    with pytest.raises(StoreError) as raised:
        _blob_store(FakeBlob(), token="wrong-token-xyz").push(built, "a")
    # HEAD on a missing manifest under a bad token returns 403, which is not 200, so the upload proceeds and fails
    message = str(raised.value)
    assert "HTTP 403" in message and "wrong-token-xyz" not in message and "secret-detail" not in message


def test_invalid_account_and_locations_are_refused() -> None:
    for bad in ("Bad_Account", "ab", "UPPER", "x" * 25):
        with pytest.raises(StoreError, match="storage account"):
            AzureBlobStore(bad, CONTAINER)
    with pytest.raises(StoreError, match="expected az://"):
        open_store("az://onlyaccount")
    assert isinstance(
        open_store("az://discoverypildata1a2b3c/datasets/sub", token_provider=lambda: TOKEN), AzureBlobStore
    )
    assert isinstance(open_store("/tmp/some/dir"), LocalStore)


# ---- token providers --------------------------------------------------------------------------------------


def test_managed_identity_uses_the_container_apps_endpoint_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IDENTITY_ENDPOINT", "http://localhost:42356/msi/token")
    monkeypatch.setenv("IDENTITY_HEADER", "hdr")
    monkeypatch.setenv("AZURE_CLIENT_ID", "client-1")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"access_token": "t1"})

    assert store_module.managed_identity_token(httpx.MockTransport(handler)) == "t1"
    assert seen[0].headers["x-identity-header"] == "hdr"
    assert (
        seen[0].url.params["resource"] == "https://storage.azure.com/" and seen[0].url.params["client_id"] == "client-1"
    )


def test_managed_identity_falls_back_to_the_vm_metadata_service_and_fails_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("IDENTITY_ENDPOINT", raising=False)
    monkeypatch.delenv("IDENTITY_HEADER", raising=False)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(400, text="secret")

    with pytest.raises(StoreError, match="HTTP 400") as raised:
        store_module.managed_identity_token(httpx.MockTransport(handler))
    assert (
        seen[0].url.host == "169.254.169.254"
        and seen[0].headers["metadata"] == "true"
        and "secret" not in str(raised.value)
    )


def test_the_provider_choice_follows_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IDENTITY_ENDPOINT", "http://x")
    assert store_module.default_token_provider() is store_module.managed_identity_token
    monkeypatch.delenv("IDENTITY_ENDPOINT")
    assert store_module.default_token_provider() is store_module.az_cli_token


# ---- CLI --------------------------------------------------------------------------------------------------


def test_cli_push_list_pull_round_trip_on_a_local_store(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    built = _built(tmp_path)
    store = tmp_path / "store"
    assert cli_main(["push", "--out", str(built), "--to", str(store), "--name", "s1"]) == 0
    assert cli_main(["push", "--out", str(built), "--to", str(store), "--name", "s1"]) == 1  # create-only
    assert cli_main(["list", "--store", str(store)]) == 0 and "s1" in capsys.readouterr().out
    assert cli_main(["pull", "--from", str(store), "--name", "s1", "--out", str(tmp_path / "back")]) == 0
    assert json.loads((tmp_path / "back" / "manifest.json").read_text())["selected"] == 8
