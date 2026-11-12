# pipelines/ingestion/main.py
import logging
import os
from typing import Any, Dict

import ray

from pipelines.ingestion.chunking.splitter import split_multimodal, split_text
from pipelines.ingestion.embedding.compute import MultimodalBatchEmbedder, select_text_embedder
from pipelines.ingestion.graph.extractor import GraphExtractor
from pipelines.ingestion.identity import file_identity
from pipelines.ingestion.indexing.neo4j import Neo4jIndexer
from pipelines.ingestion.indexing.ray_sink import write_rows
from pipelines.ingestion.indexing.sinks import build_vector_sinks, finalize_sinks
from pipelines.ingestion.loaders.pdf import parse_pdf_bytes

# Initialize Ray (Connect to the existing cluster)
ray.init(address="auto")

logger = logging.getLogger(__name__)

MULTIMODAL_ENABLED = os.getenv("MULTIMODAL_ENABLED", "false").lower() == "true"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


def _is_image_file(filename: str) -> bool:
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in IMAGE_EXTENSIONS


def process_batch(batch: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ray Data transformation function.
    Receives a batch of file contents (S3 bytes).
    Supports multimodal content when MULTIMODAL_ENABLED=true.
    """
    results = []

    for i, content in enumerate(batch["bytes"]):
        # Ray supplies the full path (read_binary_files(include_paths=True)), not a file name. The path is the
        # file's identity for the sinks; the base name is what a reader sees and what the parsers key on.
        source_path, filename = file_identity(batch["path"][i])

        if MULTIMODAL_ENABLED and _is_image_file(filename):
            from pipelines.ingestion.loaders.image import parse_image_bytes
            raw_text, metadata, images = parse_image_bytes(content, filename)
        else:
            # PDF (and eventually DOCX/HTML with image support)
            raw_text, metadata, images = parse_pdf_bytes(
                content, filename, extract_images=MULTIMODAL_ENABLED
            )
        metadata["source_path"] = source_path

        # Chunking — multimodal-aware when images are present
        if MULTIMODAL_ENABLED and images:
            chunks = split_multimodal(raw_text, images, chunk_size=512, overlap=50)
        else:
            chunks = split_text(raw_text, chunk_size=512, overlap=50)
            for chunk in chunks:
                chunk["content_type"] = "text"

        # Add document-level metadata to each chunk
        for chunk in chunks:
            chunk["metadata"].update(metadata)
            results.append(chunk)

    # Build output batch with all fields needed downstream
    output = {
        "text": [r["text"] for r in results],
        "metadata": [r["metadata"] for r in results],
        "content_type": [r.get("content_type", "text") for r in results],
    }

    if MULTIMODAL_ENABLED:
        output["image_bytes"] = [r.get("image_bytes", b"") for r in results]
        output["mime_type"] = [r.get("mime_type", "") for r in results]

    return output


def main(bucket_name: str, prefix: str):
    """
    Main Orchestration Flow.
    """
    # 1. Read from S3 using Ray Data (Lazy Loading)
    ds = ray.data.read_binary_files(
        paths=f"s3://{bucket_name}/{prefix}",
        include_paths=True
    )

    # 2. Parse & Chunk (Map Phase)
    chunked_ds = ds.map_batches(
        process_batch,
        batch_size=10,
        num_cpus=1
    )

    # 3. FORK: Branch A - Vector Embeddings
    # Use MultimodalBatchEmbedder when multimodal is enabled (Gemini unified space)
    # Text embedder is chosen by INGEST_EMBED_PROVIDER: ray (BGE-M3, 1024 dims) or gemini (768, matches the index).
    embedder_cls = MultimodalBatchEmbedder if MULTIMODAL_ENABLED else select_text_embedder(os.environ)
    vector_ds = chunked_ds.map_batches(
        embedder_cls,
        concurrency=5,
        num_gpus=0.2,
        batch_size=100
    )

    # 4. FORK: Branch B - Graph Extraction (LLM Intensive)
    graph_ds = chunked_ds.map_batches(
        GraphExtractor,
        concurrency=10,
        num_gpus=0.5,
        batch_size=5
    )

    # 5. Indexing (Write to DBs)
    # When multimodal, use the multimodal Qdrant collection
    if MULTIMODAL_ENABLED:
        collection = os.getenv("MULTIMODAL_COLLECTION", "rag_multimodal")
        os.environ["QDRANT_COLLECTION"] = collection

    vector_sinks = build_vector_sinks(os.environ)
    if len(vector_sinks) > 1:
        # Without this each sink would re-run parsing, chunking and embedding.
        vector_ds = vector_ds.materialize()
    for sink in vector_sinks:
        write_rows(vector_ds, sink)
    write_rows(graph_ds, Neo4jIndexer())

    # Only reached when every write above succeeded; an error here fails the job but loses nothing.
    for report in finalize_sinks(vector_sinks):
        print(f"Sweep: {report}")

    print("Ingestion Job Completed Successfully.")

if __name__ == "__main__":
    import sys
    main(sys.argv[1], sys.argv[2])
