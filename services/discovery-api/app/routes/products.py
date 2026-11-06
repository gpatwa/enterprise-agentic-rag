"""Product search over the ESCI-style subset (docs/DISCOVERY_ESCI_SCOPE.md).

Products are catalog items, not user-generated experiences, so this route applies no age or safety eligibility
gate and carries no user profile: the owner can overrule that in the scope doc. It is lexical (BM25) only; a multi-word query must match every word, and widens to any word only when nothing does and
available only with ``DISCOVERY_SEARCH_BACKEND=opensearch``; there is no in-memory fallback, so a cluster failure
returns a typed error with no results rather than silently serving something else. When auth is on, a valid bearer
token is required like every other route; the request body carries no identity.
"""

from __future__ import annotations

import logging
from typing import Protocol

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.opensearch.client import OpenSearchClient, OpenSearchError
from app.opensearch.products import DEFAULT_PRODUCT_INDEX, MAX_WINDOW, ProductPage, search_page
from app.security import Identity, require_identity

logger = logging.getLogger(__name__)

_VERSION = "product-search-v1"
_MAX_QUERY = 256
_MAX_PAGE_SIZE = 50


class ProductSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    query: str = Field(min_length=1, max_length=_MAX_QUERY)
    locale: str | None = Field(default=None, min_length=2, max_length=16, pattern=r"^[A-Za-z0-9_-]+$")
    page: int = Field(default=1, ge=1, le=MAX_WINDOW)
    page_size: int = Field(default=10, ge=1, le=_MAX_PAGE_SIZE)


class ProductResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    product_id: str
    title: str
    brand: str
    color: str
    snippet: str
    rank: int = Field(ge=1)
    score: float


class ProductSearchError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    code: str
    message: str


class ProductSearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: str = _VERSION
    results: tuple[ProductResult, ...] = ()
    total_matches: int = Field(default=0, ge=0)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=10, ge=1)
    match: str = "all"
    error: ProductSearchError | None = None


class ProductSearchProvider(Protocol):
    def search(self, request: ProductSearchRequest) -> ProductSearchResponse: ...


class OpenSearchProductService:
    def __init__(self, client: OpenSearchClient, index: str = DEFAULT_PRODUCT_INDEX) -> None:
        self._client = client
        self._index = index

    def search(self, request: ProductSearchRequest) -> ProductSearchResponse:
        if not request.query.strip():
            return _error(request, "invalid_query", "Enter something to search for.")
        try:
            found: ProductPage = search_page(
                self._client,
                request.query,
                page=request.page,
                page_size=request.page_size,
                locale=request.locale,
                index=self._index,
            )
        except OpenSearchError as exc:
            logger.warning("product search failed: %s", exc)
            return _error(request, "search_unavailable", "Product search is unavailable right now.")
        start = (request.page - 1) * request.page_size
        return ProductSearchResponse(
            results=tuple(
                ProductResult(
                    product_id=hit.product_id,
                    title=hit.title,
                    brand=hit.brand,
                    color=hit.color,
                    snippet=hit.snippet,
                    rank=start + i,
                    score=round(hit.score, 4),
                )
                for i, hit in enumerate(found.hits, start=1)
            ),
            total_matches=found.total,
            page=request.page,
            page_size=request.page_size,
            match=found.match,
        )


class UnconfiguredProductService:
    def search(self, request: ProductSearchRequest) -> ProductSearchResponse:
        return _error(request, "not_configured", "Product search needs the OpenSearch backend.")


def _error(request: ProductSearchRequest, code: str, message: str) -> ProductSearchResponse:
    return ProductSearchResponse(
        page=request.page, page_size=request.page_size, error=ProductSearchError(code=code, message=message)
    )


service: ProductSearchProvider = UnconfiguredProductService()
router = APIRouter(tags=["discovery"])


@router.post("/v1/products/search", response_model=ProductSearchResponse)
def search_products(
    request: ProductSearchRequest, identity: Identity | None = Depends(require_identity)
) -> ProductSearchResponse:
    """Search the product index. ``identity`` only gates access; it never changes the results."""
    return service.search(request)


__all__ = ["ProductSearchRequest", "ProductSearchResponse", "router", "search_products"]
