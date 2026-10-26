"""Effective scheduled-backup configuration.

Values saved through the admin API live in the app_settings table and
override the matching environment variables wherever scheduled backups
run. Secrets are stored Fernet-encrypted (the same key as provider
credentials) and never leave the service layer.
"""

import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.app_settings import AppSetting
from app.schemas.admin import BackupS3TestRequest, BackupSettingsUpdate

logger = logging.getLogger(__name__)

#: app_settings keys backing the admin backup form.
BACKUP_SETTING_KEYS = (
    "storage_provider",
    "backup_schedule_hour",
    "backup_retention_count",
    "backup_local_path",
    "backup_encryption_key",
    "storage_s3_bucket",
    "storage_s3_region",
    "storage_s3_endpoint_url",
    "storage_s3_access_key",
    "storage_s3_secret_key",
)

#: Keys whose stored values are encrypted and never returned to clients.
SECRET_SETTING_KEYS = frozenset(
    {
        "backup_encryption_key",
        "storage_s3_access_key",
        "storage_s3_secret_key",
    }
)

_PROVIDERS = ("local", "s3")


@dataclass(frozen=True)
class BackupConfig:
    """The backup configuration after admin overrides over env defaults."""

    storage_provider: str
    backup_schedule_hour: int
    backup_retention_count: int
    backup_local_path: str
    backup_encryption_key: str
    storage_s3_bucket: str
    storage_s3_region: str
    storage_s3_endpoint_url: str
    storage_s3_access_key: str
    storage_s3_secret_key: str


def _int_or(value: str | None, fallback: int) -> int:
    if value is None:
        return fallback
    try:
        return int(value)
    except ValueError:
        return fallback


async def _stored_values(session: AsyncSession) -> dict[str, str]:
    """Saved backup settings, with secrets decrypted."""
    from app.agents.services.crypto import decrypt

    rows = (
        await session.execute(
            select(AppSetting).where(AppSetting.key.in_(BACKUP_SETTING_KEYS))
        )
    ).scalars()
    values: dict[str, str] = {}
    for row in rows:
        if row.key in SECRET_SETTING_KEYS:
            plain = decrypt(row.value)
            if plain is not None:
                values[row.key] = plain
        else:
            values[row.key] = row.value
    return values


async def get_backup_config(session: AsyncSession) -> BackupConfig:
    """Saved admin settings merged over the env-derived defaults."""
    settings = get_settings()
    stored = await _stored_values(session)

    provider = stored.get("storage_provider") or settings.storage_provider
    if provider not in _PROVIDERS:
        provider = settings.storage_provider

    return BackupConfig(
        storage_provider=provider,
        backup_schedule_hour=_int_or(
            stored.get("backup_schedule_hour"), settings.backup_schedule_hour
        ),
        backup_retention_count=_int_or(
            stored.get("backup_retention_count"), settings.backup_retention_count
        ),
        backup_local_path=stored.get("backup_local_path") or settings.backup_local_path,
        backup_encryption_key=stored.get("backup_encryption_key")
        or settings.backup_encryption_key.get_secret_value(),
        storage_s3_bucket=stored.get("storage_s3_bucket") or settings.storage_s3_bucket,
        storage_s3_region=stored.get("storage_s3_region") or settings.storage_s3_region,
        storage_s3_endpoint_url=stored.get("storage_s3_endpoint_url")
        or settings.storage_s3_endpoint_url,
        storage_s3_access_key=stored.get("storage_s3_access_key")
        or settings.storage_s3_access_key.get_secret_value(),
        storage_s3_secret_key=stored.get("storage_s3_secret_key")
        or settings.storage_s3_secret_key.get_secret_value(),
    )


async def _upsert(session: AsyncSession, key: str, value: str) -> None:
    row = await session.get(AppSetting, key)
    if row is None:
        session.add(AppSetting(key=key, value=value))
    else:
        row.value = value


async def save_backup_settings(session: AsyncSession, data: BackupSettingsUpdate) -> None:
    """Persist the fields the update carries.

    Unset fields leave the stored row alone. An empty string deletes the
    stored override so the environment value applies again.
    """
    from app.agents.services.crypto import encrypt

    for key, value in data.model_dump(exclude_unset=True).items():
        if value is None:
            continue
        if value == "":
            row = await session.get(AppSetting, key)
            if row is not None:
                await session.delete(row)
        elif key in SECRET_SETTING_KEYS:
            await _upsert(session, key, encrypt(value) or "")
        else:
            await _upsert(session, key, str(value))
    await session.commit()


async def test_s3_connection(
    session: AsyncSession,
    overrides: BackupS3TestRequest | None = None,
) -> tuple[bool, str | None]:
    """HeadBucket against the effective (or just-submitted) S3 config.

    Returns (success, error). The error string is a boto3 exception
    message, which carries the service error, never the credentials.
    """
    from app.providers.s3_storage import build_s3_client

    config = await get_backup_config(session)
    if overrides is None:
        overrides = BackupS3TestRequest()

    bucket = overrides.storage_s3_bucket or config.storage_s3_bucket
    if not bucket:
        return False, "No S3 bucket configured"

    try:
        client = await asyncio.to_thread(
            build_s3_client,
            region=overrides.storage_s3_region or config.storage_s3_region,
            access_key=overrides.storage_s3_access_key or config.storage_s3_access_key,
            secret_key=overrides.storage_s3_secret_key or config.storage_s3_secret_key,
            endpoint_url=overrides.storage_s3_endpoint_url or config.storage_s3_endpoint_url,
        )
        await asyncio.to_thread(client.head_bucket, Bucket=bucket)
    except Exception as exc:  # noqa: BLE001 - any client or network failure is a failed test
        logger.info("S3 connection test failed: %s", type(exc).__name__)
        return False, str(exc)
    return True, None
