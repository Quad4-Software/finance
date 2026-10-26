"""S3-compatible object storage backend.

Selected by STORAGE_PROVIDER=s3. Works against AWS S3 and any S3-compatible
service (MinIO, Cloudflare R2, Backblaze B2) via STORAGE_S3_ENDPOINT_URL.
boto3 is synchronous, so every call is wrapped in asyncio.to_thread to keep
the event loop responsive. The client is created lazily on first use so a
misconfigured deployment only fails when storage is actually touched.
"""

import asyncio
import logging

from app.core.config import get_settings
from app.providers.storage import StorageProvider, StoredFile

logger = logging.getLogger(__name__)


class S3StorageProvider(StorageProvider):
    """Store files in an S3 bucket."""

    def __init__(self) -> None:
        self._client = None

    @property
    def name(self) -> str:
        return "s3"

    def _client_or_raise(self):
        if self._client is None:
            import boto3

            settings = get_settings()
            if not settings.storage_s3_bucket:
                raise RuntimeError("STORAGE_PROVIDER=s3 requires STORAGE_S3_BUCKET to be set")
            kwargs: dict = {}
            if settings.storage_s3_region:
                kwargs["region_name"] = settings.storage_s3_region
            if settings.storage_s3_access_key.get_secret_value():
                kwargs["aws_access_key_id"] = settings.storage_s3_access_key.get_secret_value()
                kwargs["aws_secret_access_key"] = settings.storage_s3_secret_key.get_secret_value()
            if settings.storage_s3_endpoint_url:
                kwargs["endpoint_url"] = settings.storage_s3_endpoint_url
            self._client = boto3.client("s3", **kwargs)
        return self._client

    @property
    def _bucket(self) -> str:
        bucket = get_settings().storage_s3_bucket
        if not bucket:
            raise RuntimeError("STORAGE_PROVIDER=s3 requires STORAGE_S3_BUCKET to be set")
        return bucket

    async def upload(self, storage_key: str, data: bytes, content_type: str) -> StoredFile:
        client = self._client_or_raise()
        await asyncio.to_thread(
            client.put_object,
            Bucket=self._bucket,
            Key=storage_key,
            Body=data,
            ContentType=content_type,
        )
        return StoredFile(storage_key=storage_key, size=len(data), content_type=content_type)

    async def download(self, storage_key: str) -> bytes:
        client = self._client_or_raise()
        response = await asyncio.to_thread(client.get_object, Bucket=self._bucket, Key=storage_key)
        return await asyncio.to_thread(response["Body"].read)

    async def delete(self, storage_key: str) -> None:
        client = self._client_or_raise()
        await asyncio.to_thread(client.delete_object, Bucket=self._bucket, Key=storage_key)

    async def list_keys(self, prefix: str = "") -> list[str]:
        """Return all object keys under prefix. Used by backup retention."""
        client = self._client_or_raise()
        keys: list[str] = []
        paginator = client.get_paginator("list_objects_v2")
        for page in await asyncio.to_thread(
            lambda: list(paginator.paginate(Bucket=self._bucket, Prefix=prefix))
        ):
            keys.extend(obj["Key"] for obj in page.get("Contents", []))
        return keys

    def get_url(self, storage_key: str) -> str | None:
        client = self._client_or_raise()
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": storage_key},
            ExpiresIn=3600,
        )
