"""Ingestion on Azure: Blob source, no GPUs, keyless graph extraction, the Ray cluster and the files that drive it."""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

REPO = Path(__file__).resolve().parents[4]


# ----- options ---------------------------------------------------------------------------------------------------------


def test_only_the_self_hosted_embedder_and_graph_llm_ask_for_gpus() -> None:
    from pipelines.ingestion.options import embed_num_gpus, graph_num_gpus

    assert embed_num_gpus({}) == 0.2 and graph_num_gpus({}) == 0.5, "the existing GPU defaults must not change"
    assert embed_num_gpus({"INGEST_EMBED_PROVIDER": "azure_openai"}) == 0.0
    assert embed_num_gpus({"INGEST_EMBED_PROVIDER": "gemini"}) == 0.0
    assert graph_num_gpus({"INGEST_GRAPH_PROVIDER": "azure_openai"}) == 0.0
    assert graph_num_gpus({"INGEST_GRAPH_PROVIDER": "none"}) == 0.0
    assert embed_num_gpus({"INGEST_EMBED_PROVIDER": "azure_openai", "INGEST_EMBED_NUM_GPUS": "0.5"}) == 0.5


def test_the_azure_job_requests_no_gpu_anywhere() -> None:
    from pipelines.ingestion.options import embed_num_gpus, graph_num_gpus

    env = yaml.safe_load((REPO / "pipelines" / "jobs" / "ray_job.yaml").read_text())["runtime_env"]["env_vars"]
    assert embed_num_gpus(env) == 0.0 and graph_num_gpus(env) == 0.0
    assert env["INGEST_SOURCE"] == "azure_blob" and env["INGEST_GRAPH_PROVIDER"] == "azure_openai"


# ----- the Blob source ---------------------------------------------------------------------------------------------------


class _FakeContainer:
    def __init__(self, names):
        self.names = names

    def list_blobs(self, name_starts_with=None):
        return [SimpleNamespace(name=n) for n in self.names if not name_starts_with or n.startswith(name_starts_with)]


class _FakeService:
    def __init__(self, blobs: dict[str, bytes]):
        self.blobs = blobs

    def get_container_client(self, container):
        return _FakeContainer(list(self.blobs))

    def get_blob_client(self, container, name):
        data = self.blobs[name]
        return SimpleNamespace(download_blob=lambda: SimpleNamespace(readall=lambda: data))


def test_blob_paths_are_listed_under_the_prefix_and_skip_directory_markers() -> None:
    from pipelines.ingestion.loaders.azure_blob import list_blob_paths

    service = _FakeService({"uploads/t/run/a.pdf": b"a", "uploads/t/run/dir/": b"", "other/b.pdf": b"b"})
    assert list_blob_paths("acct", "documents", "uploads/t/run", service=service) == ["az://documents/uploads/t/run/a.pdf"]


def test_the_fetcher_adds_bytes_and_keeps_the_path(monkeypatch) -> None:
    from pipelines.ingestion.loaders import azure_blob

    fetcher = azure_blob.AzureBlobFetcher(account="acct")
    fetcher._service = _FakeService({"uploads/t/run/a.pdf": b"%PDF-1"})
    batch = fetcher({"path": ["az://documents/uploads/t/run/a.pdf"]})
    assert batch["bytes"] == [b"%PDF-1"] and batch["path"] == ["az://documents/uploads/t/run/a.pdf"]


@pytest.mark.parametrize("bad", ["s3://bucket/key", "az://onlycontainer", "az:///x"])
def test_split_path_rejects_what_it_cannot_split(bad: str) -> None:
    from pipelines.ingestion.loaders.azure_blob import split_path

    with pytest.raises(ValueError):
        split_path(bad)


def test_a_blob_path_gives_a_file_identity_without_the_scheme() -> None:
    from pipelines.ingestion.identity import file_identity

    assert file_identity("az://documents/uploads/t/run/Guide.pdf") == ("documents/uploads/t/run/Guide.pdf", "Guide.pdf")


def test_read_source_defaults_to_s3_and_reads_blob_on_request(monkeypatch) -> None:
    from pipelines.ingestion.loaders import azure_blob
    from pipelines.ingestion.loaders.source import read_source

    seen = {}

    class _Data:
        def read_binary_files(self, **kwargs):
            seen["s3"] = kwargs
            return "s3-dataset"

        def from_items(self, items):
            seen["items"] = items
            return SimpleNamespace(map_batches=lambda cls, **kw: ("blob-dataset", cls.__name__, kw["concurrency"]))

    assert read_source(_Data(), {}, "bucket", "prefix") == "s3-dataset"
    assert seen["s3"] == {"paths": "s3://bucket/prefix", "include_paths": True}

    monkeypatch.setattr(azure_blob, "list_blob_paths", lambda account, container, prefix: ["az://c/x.pdf"])
    env = {"INGEST_SOURCE": "azure_blob", "AZURE_STORAGE_ACCOUNT_NAME": "acct", "INGEST_FETCH_CONCURRENCY": "3"}
    assert read_source(_Data(), env, "c", "p") == ("blob-dataset", "AzureBlobFetcher", 3)
    assert seen["items"] == [{"path": "az://c/x.pdf"}]

    with pytest.raises(ValueError, match="INGEST_SOURCE"):
        read_source(_Data(), {"INGEST_SOURCE": "gcs"}, "b", "p")


def test_an_empty_blob_prefix_stops_the_job_instead_of_ingesting_nothing(monkeypatch) -> None:
    from pipelines.ingestion.loaders import azure_blob
    from pipelines.ingestion.loaders.source import read_source

    monkeypatch.setattr(azure_blob, "list_blob_paths", lambda *a: [])
    with pytest.raises(SystemExit, match="No blobs"):
        read_source(SimpleNamespace(), {"INGEST_SOURCE": "azure_blob", "AZURE_STORAGE_ACCOUNT_NAME": "a"}, "c", "p")


# ----- graph extraction --------------------------------------------------------------------------------------------------


def _extractor(content_by_text: dict[str, str]):
    from pipelines.ingestion.graph.extractor import AzureOpenAIGraphExtractor

    seen = []

    class _Completions:
        def create(self, **kwargs):
            seen.append(kwargs)
            text = kwargs["messages"][0]["content"].rsplit("Input Text:", 1)[1].strip()
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content_by_text[text]))])

    extractor = AzureOpenAIGraphExtractor()
    extractor.client = SimpleNamespace(chat=SimpleNamespace(completions=_Completions()))
    return extractor, seen


def test_the_graph_extractor_returns_nodes_and_edges_without_unsupported_parameters() -> None:
    extractor, seen = _extractor({"chunk": '{"nodes": [{"name": "Acme"}], "edges": []}'})
    out = extractor({"text": ["chunk"]})
    assert out["graph_nodes"] == [[{"name": "Acme"}]] and out["graph_edges"] == [[]]
    call = seen[0]
    assert call["model"] == "gpt-6-luna" and call["response_format"] == {"type": "json_object"}
    assert "max_tokens" not in call and "temperature" not in call and call["max_completion_tokens"] >= 4096


def test_a_bad_chunk_yields_an_empty_graph_not_a_failed_batch() -> None:
    extractor, _ = _extractor({"good": '{"nodes": [1], "edges": []}', "bad": "not json"})
    out = extractor({"text": ["good", "bad"]})
    assert out["graph_nodes"] == [[1], []] and out["graph_edges"] == [[], []]


def test_the_graph_extractor_needs_an_endpoint_not_a_key(monkeypatch) -> None:
    from pipelines.ingestion.graph.extractor import AzureOpenAIGraphExtractor

    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    with pytest.raises(RuntimeError, match="AZURE_OPENAI_ENDPOINT"):
        AzureOpenAIGraphExtractor()({"text": ["x"]})


def test_the_graph_provider_selector() -> None:
    from pipelines.ingestion.graph.extractor import AzureOpenAIGraphExtractor, GraphExtractor, select_graph_extractor

    assert select_graph_extractor({}) is GraphExtractor
    assert select_graph_extractor({"INGEST_GRAPH_PROVIDER": "azure_openai"}) is AzureOpenAIGraphExtractor
    assert select_graph_extractor({"INGEST_GRAPH_PROVIDER": "none"}) is None
    with pytest.raises(ValueError, match="INGEST_GRAPH_PROVIDER"):
        select_graph_extractor({"INGEST_GRAPH_PROVIDER": "x"})


def test_main_skips_the_graph_branch_when_there_is_no_extractor() -> None:
    source = (REPO / "pipelines" / "ingestion" / "main.py").read_text()
    assert "select_graph_extractor(os.environ)" in source and "if graph_ds is not None:" in source
    assert "read_source(ray.data, os.environ, bucket_name, prefix)" in source


# ----- the PDF strategy --------------------------------------------------------------------------------------------------


def test_the_pdf_strategy_is_configurable_and_validated(monkeypatch) -> None:
    pytest.importorskip("unstructured.partition.pdf")
    from pipelines.ingestion.loaders.pdf import parse_pdf_bytes

    monkeypatch.setenv("INGEST_PDF_STRATEGY", "ocr_everything")
    with pytest.raises(ValueError, match="INGEST_PDF_STRATEGY"):
        parse_pdf_bytes(b"%PDF-1.4", "x.pdf")


def test_the_pdf_loader_keeps_hi_res_as_the_default() -> None:
    text = (REPO / "pipelines" / "ingestion" / "loaders" / "pdf.py").read_text()
    assert 'os.getenv("INGEST_PDF_STRATEGY", "hi_res")' in text


# ----- the Ray cluster ---------------------------------------------------------------------------------------------------


def _cluster(name: str) -> dict:
    return yaml.safe_load((REPO / "deploy" / "ray" / name).read_text())["spec"]


def test_the_azure_cluster_is_cpu_only_and_runs_the_ingestion_image() -> None:
    spec = _cluster("ray-cluster-azure.yaml")
    groups = spec["workerGroupSpecs"]
    assert [g["groupName"] for g in groups] == ["cpu-workers"] and groups[0]["replicas"] == 0
    for template in [spec["headGroupSpec"]["template"]] + [g["template"] for g in groups]:
        container = template["spec"]["containers"][0]
        assert container["image"] == "__INGESTION_IMAGE__"
        assert "nvidia.com/gpu" not in str(container["resources"]) and "karpenter" not in str(template["spec"])
        assert template["spec"]["serviceAccountName"] == "ray-worker"
        assert template["metadata"]["labels"]["azure.workload.identity/use"] == "true"
        assert int(container["resources"]["limits"]["cpu"]) <= 1, "must fit a B2s_v2 node next to the platform pods"


def test_the_azure_cluster_has_the_same_sink_settings_as_the_shared_one() -> None:
    shared, azure = _cluster("ray-cluster.yaml"), _cluster("ray-cluster-azure.yaml")

    def env(spec, kind):
        template = spec["headGroupSpec"]["template"] if kind == "head" else spec["workerGroupSpecs"][0]["template"]
        return {e["name"]: e for e in template["spec"]["containers"][0]["env"]}

    for kind in ("head", "worker"):
        assert env(shared, kind) == env(azure, kind), f"{kind} environment drifted between the two manifests"


def test_the_bootstrap_builds_the_ingestion_image_and_fills_the_placeholder() -> None:
    text = (REPO / "scripts" / "bootstrap_cluster_azure.sh").read_text()
    build = text.index("rag-ingestion:${INGEST_TAG}")
    assert 'az acr repository show --name "$ACR_NAME" --image "rag-ingestion' in text[:build + 200]
    assert "--file Dockerfile.ingestion" in text
    assert "__INGESTION_IMAGE__" in text and "ray-cluster-azure.yaml" in text
    assert text.index("create serviceaccount ray-worker") < text.index("ray-cluster-azure.yaml"), "the SA must exist first"


def test_the_ingestion_image_has_what_kuberay_and_the_pdf_stack_need() -> None:
    dockerfile = (REPO / "Dockerfile.ingestion").read_text()
    for needed in ("wget", "libgl1", "poppler-utils", "tesseract-ocr", "ray==2.60.0"):
        assert needed in dockerfile, needed
    assert "ray==2.60.0" in (REPO / "requirements-ingestion.txt").read_text()
    assert "adlfs" in (REPO / "requirements-ingestion.txt").read_text() and "azure-storage-blob" in (
        REPO / "requirements-ingestion.txt"
    ).read_text()


def test_the_build_context_leaves_out_the_sample_data() -> None:
    ignore = (REPO / ".dockerignore").read_text().splitlines()
    for path in ("data/", "apps/", "eval/", "artifacts/"):
        assert path in ignore


# ----- the ingest script -------------------------------------------------------------------------------------------------


def test_the_ingest_script_always_scales_the_workers_back_down_and_takes_its_env_from_the_job_file() -> None:
    text = (REPO / "scripts" / "ingest_azure.sh").read_text()
    assert re.search(r"trap cleanup EXIT", text) and "scale_workers 0" in text
    assert "ray_job.yaml" in text and 'env["TENANT_ID"]' in text
    assert "--auth-mode login" in text
    # the storage key, when needed, travels in this process's environment, never on a command line
    assert "AZURE_STORAGE_KEY" in text and "--account-key" not in text
