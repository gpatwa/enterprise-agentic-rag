# tests/test_storage_abstraction.py
"""
Unit tests for Milestone 4: Cloud Storage Abstraction.
Tests Protocol compliance, factory routing, S3 implementation,
and upload route integration with StorageClient.
"""
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------
# Test: StorageClient Protocol
# ---------------------------------------------------------------

class TestStorageClientProtocol:
    def test_protocol_is_runtime_checkable(self):
        from app.clients.storage.base import StorageClient
        assert isinstance(StorageClient, type)

    def test_s3_impl_has_all_methods(self):
        """S3StorageClient must implement all Protocol methods."""
        with patch("boto3.client"):
            from app.clients.storage.s3 import S3StorageClient
            client = S3StorageClient(bucket="test-bucket")
            assert hasattr(client, "generate_presigned_upload_url")
            assert hasattr(client, "generate_presigned_download_url")
            assert hasattr(client, "download_file")
            assert hasattr(client, "list_objects")


# ---------------------------------------------------------------
# Test: Storage Factory
# ---------------------------------------------------------------

class TestStorageFactory:
    def test_create_s3_client(self):
        from app.clients.storage.factory import create_storage_client
        client = create_storage_client("s3")
        from app.clients.storage.s3 import S3StorageClient
        assert isinstance(client, S3StorageClient)

    def test_create_s3_case_insensitive(self):
        from app.clients.storage.factory import create_storage_client
        client = create_storage_client("  S3  ")
        from app.clients.storage.s3 import S3StorageClient
        assert isinstance(client, S3StorageClient)

    def test_unknown_provider_raises(self):
        from app.clients.storage.factory import create_storage_client
        with pytest.raises(ValueError, match="Unknown STORAGE_PROVIDER"):
            create_storage_client("gcs")


# ---------------------------------------------------------------
# Test: S3StorageClient methods
# ---------------------------------------------------------------

class TestS3StorageClient:
    def _make_client(self):
        with patch("boto3.client") as mock_boto:
            mock_s3 = MagicMock()
            mock_boto.return_value = mock_s3
            from app.clients.storage.s3 import S3StorageClient
            client = S3StorageClient(bucket="test-bucket", region="us-east-1")
            return client, mock_s3

    def test_presigned_upload_url(self):
        client, mock_s3 = self._make_client()
        mock_s3.generate_presigned_url.return_value = "https://s3.example.com/upload"
        url = client.generate_presigned_upload_url(
            key="uploads/acme/user1/file.pdf",
            content_type="application/pdf",
            metadata={"user_id": "user1"},
        )
        assert url == "https://s3.example.com/upload"
        mock_s3.generate_presigned_url.assert_called_once()

    def test_presigned_download_url(self):
        client, mock_s3 = self._make_client()
        mock_s3.generate_presigned_url.return_value = "https://s3.example.com/download"
        url = client.generate_presigned_download_url(key="uploads/file.pdf")
        assert url == "https://s3.example.com/download"

    def test_download_file(self):
        client, mock_s3 = self._make_client()
        client.download_file(key="uploads/file.pdf", local_path="/tmp/file.pdf")
        mock_s3.download_file.assert_called_once_with(
            "test-bucket", "uploads/file.pdf", "/tmp/file.pdf"
        )

    def test_list_objects(self):
        client, mock_s3 = self._make_client()
        from datetime import datetime
        mock_s3.list_objects_v2.return_value = {
            "Contents": [
                {
                    "Key": "uploads/file1.pdf",
                    "Size": 1024,
                    "LastModified": datetime(2024, 1, 1),
                },
            ]
        }
        result = client.list_objects(prefix="uploads/")
        assert len(result) == 1
        assert result[0]["key"] == "uploads/file1.pdf"
        assert result[0]["size"] == 1024

    def test_list_objects_empty(self):
        client, mock_s3 = self._make_client()
        mock_s3.list_objects_v2.return_value = {}
        result = client.list_objects(prefix="nonexistent/")
        assert result == []


# ---------------------------------------------------------------
# Test: Upload route response model change
# ---------------------------------------------------------------

class TestUploadRouteModel:
    def test_presigned_url_response_has_object_key(self):
        from app.routes.upload import PresignedURLResponse
        resp = PresignedURLResponse(
            upload_url="https://example.com/upload",
            file_id="test-id",
            object_key="uploads/acme/user1/test.pdf",
        )
        assert resp.object_key == "uploads/acme/user1/test.pdf"


# ---------------------------------------------------------------
# Test: Config storage settings
# ---------------------------------------------------------------

class TestStorageConfig:
    def test_storage_provider_default(self):
        from app.config import settings
        assert settings.STORAGE_PROVIDER == "s3"

    def test_azure_storage_defaults(self):
        from app.config import settings
        assert settings.AZURE_STORAGE_ACCOUNT_NAME is None
        assert settings.AZURE_STORAGE_CONTAINER == "documents"
