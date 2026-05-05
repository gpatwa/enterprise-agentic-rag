# services/api/app/clients/storage/s3.py
"""
AWS S3 / MinIO implementation of the StorageClient protocol.
"""
import logging

import boto3

logger = logging.getLogger(__name__)


class S3StorageClient:
    """
    S3-backed StorageClient.

    Works with both AWS S3 and MinIO (local dev) via optional
    endpoint_url override.
    """

    def __init__(
        self,
        bucket: str,
        region: str = "us-east-1",
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
    ):
        self.bucket = bucket
        kwargs: dict = {"region_name": region}
        if endpoint_url:
            kwargs["endpoint_url"] = endpoint_url
            kwargs["aws_access_key_id"] = access_key_id
            kwargs["aws_secret_access_key"] = secret_access_key
        self._client = boto3.client("s3", **kwargs)
        logger.info(f"S3StorageClient initialised (bucket={bucket})")

    def generate_presigned_upload_url(
        self,
        key: str,
        content_type: str,
        metadata: dict | None = None,
        expires_in: int = 3600,
    ) -> str:
        params: dict = {
            "Bucket": self.bucket,
            "Key": key,
            "ContentType": content_type,
        }
        if metadata:
            params["Metadata"] = metadata
        return self._client.generate_presigned_url(
            ClientMethod="put_object",
            Params=params,
            ExpiresIn=expires_in,
        )

    def generate_presigned_download_url(
        self,
        key: str,
        expires_in: int = 3600,
    ) -> str:
        return self._client.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in,
        )

    def download_file(
        self,
        key: str,
        local_path: str,
    ) -> None:
        self._client.download_file(self.bucket, key, local_path)

    def list_objects(
        self,
        prefix: str,
        max_keys: int = 1000,
    ) -> list[dict]:
        resp = self._client.list_objects_v2(
            Bucket=self.bucket, Prefix=prefix, MaxKeys=max_keys
        )
        return [
            {
                "key": obj["Key"],
                "size": obj["Size"],
                "last_modified": obj["LastModified"].isoformat(),
            }
            for obj in resp.get("Contents", [])
        ]
