# pipelines/ingestion/indexing/qdrant.py
import hashlib
import logging
import os
import uuid
from typing import Any, Dict, List

from qdrant_client import QdrantClient
from qdrant_client.http import models

logger = logging.getLogger(__name__)

DEFAULT_TENANT_ID = "default"

# Fixed namespace for deterministic point IDs: the same chunk of the same file for the same tenant always maps to the
# same point, so re-running an ingestion upserts in place instead of adding a second copy.
_POINT_NAMESPACE = uuid.UUID("5d0b6b52-3c3e-4a0c-9d7e-0a6f3f1d2b11")

_MIME_TO_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/bmp": "bmp",
}


class QdrantIndexer:
    """
    Writes vectors to Qdrant.
    All vectors are tagged with tenant_id in their payload for isolation.
    Supports multimodal content: text chunks and image references.
    """
    def __init__(self, tenant_id: str = DEFAULT_TENANT_ID):
        host = os.getenv("QDRANT_HOST", "qdrant-service")
        port = int(os.getenv("QDRANT_PORT", 6333))
        self.collection_name = os.getenv("QDRANT_COLLECTION", "rag_collection")
        self.tenant_id = tenant_id
        self._host = host
        self._port = port
        # Live clients hold locks and sockets, so they are created on first use inside the process that writes
        # (Ray pickles this object into workers) and are never part of the pickled state.
        self._client = None

        # S3 client for image storage (lazy-init)
        self._s3_client = None
        self._s3_bucket = os.getenv("S3_BUCKET_NAME")

    @property
    def client(self) -> QdrantClient:
        if self._client is None:
            self._client = QdrantClient(host=self._host, port=self._port)
        return self._client

    @client.setter
    def client(self, value: Any) -> None:
        self._client = value

    def __getstate__(self) -> Dict[str, Any]:
        state = self.__dict__.copy()
        state["_client"] = None
        state["_s3_client"] = None
        return state

    def _get_s3_client(self):
        """Lazy-init S3 client for image uploads."""
        if self._s3_client is None:
            import boto3
            kwargs = {"region_name": os.getenv("AWS_REGION", "us-east-1")}
            endpoint_url = os.getenv("S3_ENDPOINT_URL")
            if endpoint_url:
                kwargs["endpoint_url"] = endpoint_url
                kwargs["aws_access_key_id"] = os.getenv("AWS_ACCESS_KEY_ID")
                kwargs["aws_secret_access_key"] = os.getenv("AWS_SECRET_ACCESS_KEY")
            self._s3_client = boto3.client("s3", **kwargs)
        return self._s3_client

    def _upload_image_to_storage(self, image_bytes: bytes, key: str, mime_type: str):
        """Upload image bytes to S3/MinIO."""
        client = self._get_s3_client()
        client.put_object(
            Bucket=self._s3_bucket,
            Key=key,
            Body=image_bytes,
            ContentType=mime_type,
        )

    def _point_id(self, row: Dict[str, Any], payload: Dict[str, Any]) -> str:
        image = row.get("image_bytes") if payload["content_type"] == "image" else None
        digest = hashlib.sha256(image or str(payload["text"]).encode("utf-8")).hexdigest()
        # The file's full path identifies it; two files in different folders may share a base name.
        identity = payload.get("source_path") or payload["filename"]
        key = "|".join([self.tenant_id, str(identity), str(payload["page"]), payload["content_type"], digest])
        return str(uuid.uuid5(_POINT_NAMESPACE, key))

    def write(self, batch: List[Dict[str, Any]]):
        """
        Uploads points in batch, each tagged with tenant_id.
        Handles both text and image content types.
        """
        points = []
        image_prefix = os.getenv("IMAGE_STORAGE_PREFIX", "images")

        for row in batch:
            # Skip if embedding failed
            vector = row.get("vector")
            if vector is None or len(vector) == 0:
                continue

            content_type = row.get("content_type", "text")

            # Construct Payload (Metadata) — includes tenant_id
            payload = {
                "text": row["text"],
                "content_type": content_type,
                "filename": row["metadata"]["filename"],
                "source_path": row["metadata"].get("source_path"),
                "page": row["metadata"].get("page_number", 0),
                "tenant_id": self.tenant_id,
            }

            point_id = self._point_id(row, payload)

            # For images: upload to S3 and store reference
            if content_type == "image" and row.get("image_bytes"):
                mime_type = row.get("mime_type", "image/png")
                ext = _MIME_TO_EXT.get(mime_type, "png")
                object_key = f"{image_prefix}/{self.tenant_id}/{point_id}.{ext}"

                try:
                    self._upload_image_to_storage(
                        row["image_bytes"], object_key, mime_type
                    )
                    payload["image_key"] = object_key
                    payload["image_mime_type"] = mime_type
                except Exception as e:
                    logger.error(f"Failed to upload image to S3: {e}")
                    continue

            # Create Point
            points.append(models.PointStruct(
                id=point_id,
                vector=[float(x) for x in vector],
                payload=payload,
            ))

        if points:
            # Upsert is atomic
            self.client.upsert(
                collection_name=self.collection_name,
                points=points,
            )
