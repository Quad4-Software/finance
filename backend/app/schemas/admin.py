import uuid
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class AdminUserRead(BaseModel):
    id: uuid.UUID
    email: str
    is_active: bool
    is_superuser: bool
    is_verified: bool
    preferences: Optional[dict] = None

    model_config = ConfigDict(from_attributes=True)


class AdminUserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    is_superuser: bool = False
    preferences: Optional[dict] = None


class AdminUserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    password: Optional[str] = Field(None, min_length=8, max_length=72)
    is_active: Optional[bool] = None
    is_superuser: Optional[bool] = None
    preferences: Optional[dict] = None


class AdminUserList(BaseModel):
    items: list[AdminUserRead]
    total: int


class AppSettingRead(BaseModel):
    key: str
    value: str

    model_config = ConfigDict(from_attributes=True)


class AppSettingUpdate(BaseModel):
    value: str


class TimezoneSettingRead(BaseModel):
    #: The timezone in use, after fallbacks.
    timezone: str
    #: What an administrator saved, valid or not; None when nothing is saved.
    saved: Optional[str] = None
    #: Where the application lands without a saved value (TZ, host, UTC).
    fallback: str
    available: list[str]


class BackupSettingsRead(BaseModel):
    """The effective scheduled-backup configuration.

    Secrets are never returned: each carries a *_set flag instead, true
    when a value is configured (saved by an admin or coming from the
    environment).
    """

    storage_provider: str
    backup_schedule_hour: int
    backup_retention_count: int
    backup_local_path: str
    backup_encryption_key_set: bool
    storage_s3_bucket: str
    storage_s3_region: str
    storage_s3_endpoint_url: str
    storage_s3_access_key_set: bool
    storage_s3_secret_key_set: bool


class BackupSettingsUpdate(BaseModel):
    """Admin-editable backup fields.

    An unset field keeps the stored override as it is. An empty string on a
    text field clears the stored override so the environment value applies
    again; for secrets an empty string removes the saved secret entirely.
    """

    storage_provider: Optional[Literal["local", "s3"]] = None
    backup_schedule_hour: Optional[int] = Field(None, ge=0, le=23)
    backup_retention_count: Optional[int] = Field(None, ge=1)
    backup_local_path: Optional[str] = None
    backup_encryption_key: Optional[str] = None
    storage_s3_bucket: Optional[str] = None
    storage_s3_region: Optional[str] = None
    storage_s3_endpoint_url: Optional[str] = None
    storage_s3_access_key: Optional[str] = None
    storage_s3_secret_key: Optional[str] = None


class SimplefinSettingsRead(BaseModel):
    """The effective SimpleFIN provider configuration.

    Neither field is a secret, so the read shape echoes both values back
    verbatim (saved override or environment default).
    """

    simplefin_enabled: bool
    simplefin_api_url: str


class SimplefinSettingsUpdate(BaseModel):
    """Admin-editable SimpleFIN fields.

    An unset field keeps the stored override as it is. An empty string on
    the URL clears the stored override so the environment value applies
    again.
    """

    simplefin_enabled: Optional[bool] = None
    simplefin_api_url: Optional[str] = None


class BackupS3TestRequest(BaseModel):
    """Optional S3 credentials submitted from the form before saving.

    Any field left empty falls back to the saved (or environment) value so
    a test run validates what the next backup would actually use.
    """

    storage_s3_bucket: Optional[str] = None
    storage_s3_region: Optional[str] = None
    storage_s3_endpoint_url: Optional[str] = None
    storage_s3_access_key: Optional[str] = None
    storage_s3_secret_key: Optional[str] = None


class BackupS3TestResult(BaseModel):
    success: bool
    error: Optional[str] = None


class BackupRunResult(BaseModel):
    task_id: str
    status: str = "queued"
