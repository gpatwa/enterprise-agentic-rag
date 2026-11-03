"""Minimal OpenSearch REST client over httpx; no credentials in repr, logs or errors."""

from __future__ import annotations

import json
from typing import Any, Mapping

import httpx


class OpenSearchError(RuntimeError):
    """The cluster rejected a request."""


class OpenSearchUnavailable(OpenSearchError):
    """The cluster could not be reached or answered with a server error; callers may degrade."""


class OpenSearchClient:
    def __init__(
        self,
        base_url: str,
        *,
        username: str | None = None,
        password: str | None = None,
        verify_tls: bool = True,
        timeout: float = 5.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        auth = (username, password) if username and password else None
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            auth=auth,
            verify=verify_tls,
            timeout=timeout,
            transport=transport,
        )

    def __repr__(self) -> str:
        return f"OpenSearchClient(base_url={str(self._http.base_url)!r})"

    def close(self) -> None:
        self._http.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            # Only the exception type is reported: messages can echo URLs with embedded credentials.
            raise OpenSearchUnavailable(f"opensearch unreachable ({type(exc).__name__})") from None
        if response.status_code >= 500 or response.status_code == 429:
            raise OpenSearchUnavailable(f"opensearch unavailable (HTTP {response.status_code})")
        return response

    def health(self) -> str:
        response = self._request("GET", "/_cluster/health")
        if response.status_code != 200:
            raise OpenSearchError(f"cluster health failed (HTTP {response.status_code})")
        return str(response.json().get("status", "unknown"))

    def index_exists(self, name: str) -> bool:
        return self._request("HEAD", f"/{name}").status_code == 200

    def alias_exists(self, name: str) -> bool:
        return self._request("HEAD", f"/_alias/{name}").status_code == 200

    def create_index(self, name: str, body: Mapping[str, Any]) -> None:
        response = self._request("PUT", f"/{name}", json=body)
        if response.status_code not in (200, 201):
            raise OpenSearchError(f"create index failed (HTTP {response.status_code})")

    def bulk(self, index: str, documents: list[tuple[str, Mapping[str, Any]]]) -> list[int]:
        """Upsert documents by ID; returns one HTTP-style status per document, in order."""
        lines: list[str] = []
        for document_id, document in documents:
            lines.append(json.dumps({"index": {"_index": index, "_id": document_id}}))
            lines.append(json.dumps(document, separators=(",", ":")))
        response = self._request(
            "POST", "/_bulk", content="\n".join(lines) + "\n", headers={"Content-Type": "application/x-ndjson"}
        )
        if response.status_code != 200:
            raise OpenSearchError(f"bulk failed (HTTP {response.status_code})")
        items = response.json().get("items", [])
        if len(items) != len(documents):
            raise OpenSearchError("bulk response did not match the request")
        return [int(next(iter(item.values())).get("status", 500)) for item in items]

    def refresh(self, index: str) -> None:
        self._request("POST", f"/{index}/_refresh")

    def count(self, index: str) -> int:
        response = self._request("GET", f"/{index}/_count")
        if response.status_code != 200:
            raise OpenSearchError(f"count failed (HTTP {response.status_code})")
        return int(response.json().get("count", 0))

    def search(self, index: str, body: Mapping[str, Any]) -> dict[str, Any]:
        response = self._request("POST", f"/{index}/_search", json=body)
        if response.status_code != 200:
            raise OpenSearchError(f"search failed (HTTP {response.status_code})")
        return dict(response.json())
