# services/api/app/clients/storage/azure_blob.py
"""
Azure Blob Storage implementation of the StorageClient protocol.

Requires: pip install azure-storage-blob
"""
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

try:
    # Azure SDK availability probe. We import the public symbols here so a
    # missing dependency surfaces clearly via _AZURE_AVAILABLE; specific
    # call sites import what they need from azure.storage.blob directly.
    from azure.storage.blob import (  # noqa: F401
        BlobSasPermissions,
        BlobServiceClient,
        ContentSettings,
        generate_blob_sas,
    )

    _AZURE_AVAILABLE = True
except ImportError:
    _AZURE_AVAILABLE = False


class AzureBlobStorageClient:
    """
    Azure Blob Storage-backed StorageClient.

    Uses SAS (Shared Access Signature) tokens for presigned URLs,
    which is the Azure equivalent of S3 presigned URLs.
    """

    def __init__(
        self,
        account_name: str,
        account_key: str | None = None,
        connection_string: str | None = None,
        container: str = "documents",
    ):
        if not _AZURE_AVAILABLE:
            raise ImportError(
                "azure-storage-blob is required for Azure Blob Storage. "
                "Install it with: pip install azure-storage-blob"
            )

        self.container = container
        self._account_name = account_name
        self._account_key = account_key

        if connection_string:
            self._service_client = BlobServiceClient.from_connection_string(
                connection_string
            )
        else:
            account_url = f"https://{account_name}.blob.core.windows.net"
            self._service_client = BlobServiceClient(
                account_url=account_url, credential=account_key
            )

        self._container_client = self._service_client.get_container_client(
            container
        )
        logger.info(
            f"AzureBlobStorageClient initialised (container={container})"
        )

    def generate_presigned_upload_url(
        self,
        key: str,
        content_type: str,
        metadata: dict | None = None,
        expires_in: int = 3600,
    ) -> str:
        sas_token = generate_blob_sas(
            account_name=self._account_name,
            container_name=self.container,
            blob_name=key,
            account_key=self._account_key,
            permission=BlobSasPermissions(write=True, create=True),
            expiry=datetime.now(timezone.utc) + timedelta(seconds=expires_in),
            content_type=content_type,
        )
        return (
            f"https://{self._account_name}.blob.core.windows.net/"
            f"{self.container}/{key}?{sas_token}"
        )

    def generate_presigned_download_url(
        self,
        key: str,
        expires_in: int = 3600,
    ) -> str:
        sas_token = generate_blob_sas(
            account_name=self._account_name,
            container_name=self.container,
            blob_name=key,
            account_key=self._account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.now(timezone.utc) + timedelta(seconds=expires_in),
        )
        return (
            f"https://{self._account_name}.blob.core.windows.net/"
            f"{self.container}/{key}?{sas_token}"
        )

    def download_file(
        self,
        key: str,
        local_path: str,
    ) -> None:
        blob_client = self._container_client.get_blob_client(key)
        with open(local_path, "wb") as f:
            stream = blob_client.download_blob()
            f.write(stream.readall())

    def list_objects(
        self,
        prefix: str,
        max_keys: int = 1000,
    ) -> list[dict]:
        blobs = self._container_client.list_blobs(
            name_starts_with=prefix, results_per_page=max_keys
        )
        results = []
        for blob in blobs:
            results.append(
                {
                    "key": blob.name,
                    "size": blob.size,
                    "last_modified": blob.last_modified.isoformat()
                    if blob.last_modified
                    else "",
                }
            )
            if len(results) >= max_keys:
                break
        return results
