"""Discovery API entry point: health plus the local search, home and interaction routes.

The routes run over a fictional, seeded demo catalog with fake providers. Nothing here reads a
database, a search cluster or a model.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.demo_data import load_demo_catalog
from app.routes import home, interactions, search

API_PREFIX = "/api/discovery"


def create_app() -> FastAPI:
    experiences, documents, users = load_demo_catalog()
    search.service = search.LocalSearchService(documents, users)
    home.service = home.LocalHomeService(experiences, users)

    application = FastAPI(title="Compass Discovery API", version="0.1.0")

    @application.get("/health")
    async def health() -> dict[str, str]:
        """Return a stable, dependency-free service health response."""

        return {"service": "discovery-api", "status": "ok"}

    for router in (search.router, home.router, interactions.router):
        application.include_router(router, prefix=API_PREFIX)
    return application


app = create_app()
