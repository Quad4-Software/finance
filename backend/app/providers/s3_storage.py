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


def build_s3_client(
    *,
    region: str | None = None,
    access_key: str | None = None,
    secret_key: str | None = None,
    endpoint_url: str | None = None,
):
    """Create a boto3 S3 client.

    Each argument falls back to the matching STORAGE_S3_* setting, so
    callers pass admin-saved overrides or nothing at all.
    """
    import boto3

    settings = get_settings()
    region = region or settings.storage_s3_region
    access_key = access_key or settings.storage_s3_access_key.get_secret_value()
    secret_key = secret_key or settings.storage_s3_secret_key.get_secret_value()
    endpoint_url = endpoint_url or settings.storage_s3_endpoint_url
    kwargs: dict = {}
    if region:
        kwargs["region_name"] = region
    if access_key:
        kwargs["aws_access_key_id"] = access_key
        kwargs["aws_secret_access_key"] = secret_key
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    return boto3.client("s3", **kwargs)


class S3StorageProvider(StorageProvider):
    """Store files in an S3 bucket.

    The keyword arguments override the STORAGE_S3_* env settings; the admin
    backup configuration uses them while the process-wide provider keeps
    the defaults.
    """

    def __init__(
        self,
        *,
        bucket: str | None = None,
        region: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        endpoint_url: str | None = None,
    ) -> None:
        self._client = None
        self._bucket_name = bucket
        self._region = region
        self._access_key = access_key
        self._secret_key = secret_key
        self._endpoint_url = endpoint_url

    @property
    def name(self) -> str:
        return "s3"

    def _client_or_raise(self):
        if self._client is None:
            if not self._bucket:
                raise RuntimeError("STORAGE_PROVIDER=s3 requires STORAGE_S3_BUCKET to be set")
            self._client = build_s3_client(
                region=self._region,
                access_key=self._access_key,
                secret_key=self._secret_key,
                endpoint_url=self._endpoint_url,
            )
        return self._client

    @property
    def _bucket(self) -> str:
        bucket = self._bucket_name or get_settings().storage_s3_bucket
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
