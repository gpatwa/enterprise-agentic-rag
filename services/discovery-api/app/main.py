"""Minimal local entry point for the immersive discovery API."""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(
    title="Compass Discovery API",
    version="0.1.0",
)


@app.get("/health")
async def health() -> dict[str, str]:
    """Return a stable, dependency-free service health response."""

    return {"service": "discovery-api", "status": "ok"}
