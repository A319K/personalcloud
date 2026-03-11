"""
storage.py — Unified storage service for Cloudflare R2 and MinIO.

Both backends use the S3-compatible API via boto3. The active backend is
determined by STORAGE_BACKEND in .env ("r2" or "minio").
"""

import os
from pathlib import Path
from typing import Optional
import boto3
from botocore.client import BaseClient
from botocore.exceptions import ClientError, BotoCoreError
from rich.console import Console
from config.settings import settings

console = Console(stderr=True)


def _build_client() -> BaseClient:
    """
    Build and return a boto3 S3 client configured for the active storage backend.

    For R2, points to Cloudflare's S3-compatible endpoint.
    For MinIO, points to the local MinIO instance.
    """
    if settings.STORAGE_BACKEND == "r2":
        endpoint_url = f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
        return boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=settings.R2_ACCESS_KEY_ID,
            aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
            region_name="auto",
        )
    else:
        # MinIO uses the local endpoint
        return boto3.client(
            "s3",
            endpoint_url=settings.MINIO_ENDPOINT,
            aws_access_key_id=settings.MINIO_ACCESS_KEY,
            aws_secret_access_key=settings.MINIO_SECRET_KEY,
            region_name="us-east-1",  # MinIO requires a region, value doesn't matter
        )


class StorageService:
    """
    Abstracts file upload, deletion, listing, and URL generation over R2 or MinIO.

    All methods raise StorageError on failure instead of crashing.
    """

    def __init__(self) -> None:
        """Initialize the storage client and ensure the bucket exists."""
        self._client: BaseClient = _build_client()
        self._bucket: str = settings.bucket_name
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        """
        Create the storage bucket if it does not already exist.

        For MinIO this is required on first run. For R2, bucket must be
        pre-created in the Cloudflare dashboard (creation via API requires
        special permissions; we skip silently if it already exists).
        """
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError as e:
            error_code = int(e.response["Error"]["Code"])
            if error_code == 404:
                try:
                    self._client.create_bucket(Bucket=self._bucket)
                except ClientError as create_err:
                    # R2 may raise if bucket exists under another account — ignore
                    console.print(
                        f"[yellow]Warning:[/yellow] Could not create bucket '{self._bucket}': {create_err}"
                    )

    def upload_file(self, local_path: Path, storage_key: str) -> None:
        """
        Upload a local file to the storage bucket at the given key.

        Args:
            local_path: Absolute path to the file on disk.
            storage_key: The destination key (path) inside the bucket.

        Raises:
            StorageError: If the upload fails.
        """
        try:
            self._client.upload_file(
                Filename=str(local_path),
                Bucket=self._bucket,
                Key=storage_key,
            )
        except (ClientError, BotoCoreError, OSError) as e:
            raise StorageError(f"Failed to upload '{local_path}': {e}") from e

    def delete_file(self, storage_key: str) -> None:
        """
        Delete a file from the storage bucket by its key.

        Args:
            storage_key: The key of the file to delete.

        Raises:
            StorageError: If the deletion fails.
        """
        try:
            self._client.delete_object(Bucket=self._bucket, Key=storage_key)
        except (ClientError, BotoCoreError) as e:
            raise StorageError(f"Failed to delete '{storage_key}': {e}") from e

    def get_file_url(self, storage_key: str, expires_in: int = 3600) -> str:
        """
        Generate a pre-signed URL for temporary access to a stored file.

        Args:
            storage_key: The key of the file in the bucket.
            expires_in: URL validity in seconds (default: 1 hour).

        Returns:
            A pre-signed HTTPS URL string.

        Raises:
            StorageError: If URL generation fails.
        """
        try:
            url: str = self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": storage_key},
                ExpiresIn=expires_in,
            )
            return url
        except (ClientError, BotoCoreError) as e:
            raise StorageError(f"Failed to generate URL for '{storage_key}': {e}") from e

    def list_files(self) -> list[dict]:
        """
        List all files stored in the bucket.

        Returns:
            A list of dicts with keys: key, size, last_modified.
        """
        results: list[dict] = []
        try:
            paginator = self._client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self._bucket):
                for obj in page.get("Contents", []):
                    results.append(
                        {
                            "key": obj["Key"],
                            "size": obj["Size"],
                            "last_modified": obj["LastModified"].isoformat(),
                        }
                    )
        except (ClientError, BotoCoreError) as e:
            raise StorageError(f"Failed to list bucket contents: {e}") from e
        return results


class StorageError(Exception):
    """Raised when a storage operation fails."""
    pass
