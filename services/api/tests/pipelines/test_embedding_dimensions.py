"""Every embedder the repo deploys must produce vectors the 768-dim OpenSearch index accepts.

The owner chose "keep 768 everywhere" (2026-11-12) after the plan's section 10.4 found that ``values-azure.yaml``
(OpenAI, 1536) and ``values-prod.yaml`` (BGE-M3, 1024) produced query vectors the 768 index rejects, and that the
ingestion ``BatchEmbedder`` always called the BGE-M3 Serve endpoint (1024). Gemini is the one provider that already
yields 768 on both the query and the ingestion side (``GEMINI_EMBED_DIMENSIONS``).
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

REPO = Path(__file__).resolve().parents[4]
INDEX_DIMENSIONS = 768


def _env(path: str) -> dict:
    return yaml.safe_load((REPO / path).read_text())["env"]


@pytest.mark.parametrize("values_file", ["deploy/helm/api/values-azure.yaml", "deploy/helm/api/values-prod.yaml"])
def test_deployed_values_files_embed_with_the_768_provider(values_file: str) -> None:
    env = _env(values_file)
    assert env["EMBED_PROVIDER"] == "azure_openai", f"{values_file} embeds with {env.get('EMBED_PROVIDER')!r}"
    assert int(env["AZURE_OPENAI_EMBED_DIMENSIONS"]) == INDEX_DIMENSIONS
    assert "bge-m3" not in str(env.get("EMBED_MODEL", "")).lower(), "BGE-M3 is 1024-dim; the index is 768"


def test_the_index_dimension_the_chart_passes_is_768() -> None:
    chart = yaml.safe_load((REPO / "deploy/helm/api/values.yaml").read_text())
    assert chart["enterpriseSearch"]["vectorDimensions"] == INDEX_DIMENSIONS


@pytest.mark.parametrize("path", ["pipelines/jobs/ray_job.yaml"])
def test_the_ray_job_ingests_with_azure_openai_at_768(path: str) -> None:
    env = yaml.safe_load((REPO / path).read_text())["runtime_env"]["env_vars"]
    assert env["INGEST_EMBED_PROVIDER"] == "azure_openai"
    assert int(env["AZURE_OPENAI_EMBED_DIMENSIONS"]) == INDEX_DIMENSIONS


def test_the_job_handler_ingests_with_gemini_at_768() -> None:
    text = (REPO / "pipelines/jobs/s3_event_handler.py").read_text()
    assert re.search(r'"INGEST_EMBED_PROVIDER":\s*"gemini"', text)
    assert re.search(r'"GEMINI_EMBED_DIMENSIONS":\s*"768"', text)


def test_job_images_and_pip_lists_carry_the_gemini_client() -> None:
    for path in ("requirements-ingestion.txt", "pipelines/ingestion/requirements.txt"):
        assert "google-genai" in (REPO / path).read_text(), f"{path} does not install google-genai"
    for path in ("pipelines/jobs/ray_job.yaml", "pipelines/jobs/s3_event_handler.py"):
        assert "google-genai" in (REPO / path).read_text(), f"{path}: the job's pip list does not install google-genai"


# ----- the ingestion embedder ----------------------------------------------------------------------------------------


class _FakeModels:
    def __init__(self, dims: int) -> None:
        self.dims = dims
        self.calls: list[dict] = []

    def embed_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "dims": config.output_dimensionality, "task": config.task_type})
        items = contents if isinstance(contents, list) else [contents]
        return SimpleNamespace(embeddings=[SimpleNamespace(values=[0.1] * self.dims) for _ in items])


def _embedder(monkeypatch, dims: int = INDEX_DIMENSIONS):
    from pipelines.ingestion.embedding.compute import GeminiBatchEmbedder

    monkeypatch.setenv("GEMINI_EMBED_DIMENSIONS", str(dims))
    embedder = GeminiBatchEmbedder()
    fake = SimpleNamespace(models=_FakeModels(dims))
    embedder.gemini_client = fake
    return embedder, fake.models


def test_gemini_batch_embedder_returns_one_768_vector_per_chunk(monkeypatch) -> None:
    embedder, models = _embedder(monkeypatch)
    batch = embedder({"text": ["reset your password", "update billing"], "metadata": [{}, {}]})
    assert len(batch["vector"]) == 2
    assert {len(v) for v in batch["vector"]} == {INDEX_DIMENSIONS}
    assert models.calls[0]["dims"] == INDEX_DIMENSIONS
    assert models.calls[0]["task"] == "RETRIEVAL_DOCUMENT"
    assert batch["text"] == ["reset your password", "update billing"]


def test_gemini_batch_embedder_splits_batches_at_the_api_limit(monkeypatch) -> None:
    embedder, models = _embedder(monkeypatch)
    batch = embedder({"text": [f"chunk {i}" for i in range(230)], "metadata": [{}] * 230})
    assert len(batch["vector"]) == 230
    assert [len(call["contents"]) for call in models.calls] == [100, 100, 30]


def test_gemini_batch_embedder_fails_loudly_instead_of_writing_a_wrong_vector(monkeypatch) -> None:
    embedder, _ = _embedder(monkeypatch, dims=1024)  # the service returns 1024 although 768 was asked for
    monkeypatch.setenv("GEMINI_EMBED_DIMENSIONS", "768")
    embedder.dimensions = 768
    with pytest.raises(ValueError, match="1024.*768"):
        embedder({"text": ["x"], "metadata": [{}]})


def test_gemini_batch_embedder_needs_an_api_key(monkeypatch) -> None:
    from pipelines.ingestion.embedding.compute import GeminiBatchEmbedder

    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GOOGLE_API_KEY"):
        GeminiBatchEmbedder()({"text": ["x"], "metadata": [{}]})


def test_select_text_embedder_defaults_to_the_ray_endpoint_and_honours_the_provider() -> None:
    from pipelines.ingestion.embedding.compute import BatchEmbedder, GeminiBatchEmbedder, select_text_embedder

    assert select_text_embedder({}) is BatchEmbedder
    assert select_text_embedder({"INGEST_EMBED_PROVIDER": "ray"}) is BatchEmbedder
    assert select_text_embedder({"INGEST_EMBED_PROVIDER": " Gemini "}) is GeminiBatchEmbedder
    with pytest.raises(ValueError, match="INGEST_EMBED_PROVIDER"):
        select_text_embedder({"INGEST_EMBED_PROVIDER": "openai"})


def test_main_uses_the_selected_embedder() -> None:
    source = (REPO / "pipelines/ingestion/main.py").read_text()
    assert "select_text_embedder(os.environ)" in source
