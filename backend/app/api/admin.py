import logging
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserManager, current_active_user, current_superuser, get_user_manager
from app.core.auth_policy import require_local_auth_enabled
from app.core.database import get_async_session
from app.core.app_clock import (
    app_timezone,
    environment_timezone,
    invalidate_timezone_cache,
    is_valid_timezone,
    saved_timezone_name,
    timezone_names,
)
from app.models.user import User
from app.schemas.admin import (
    AdminUserCreate,
    AdminUserList,
    AdminUserRead,
    AdminUserUpdate,
    AppSettingRead,
    AppSettingUpdate,
    BackupRunResult,
    BackupS3TestRequest,
    BackupS3TestResult,
    BackupSettingsRead,
    BackupSettingsUpdate,
    TimezoneSettingRead,
)
from app.services import admin_service, backup_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])

ALLOWED_SETTINGS = {
    "registration_enabled",
    "credit_card_accounting_mode",
    "theme_color_light",
    "theme_color_dark",
    "number_format",
    "date_format",
    "timezone",
}


@router.get("/users", response_model=AdminUserList)
async def list_users(
    search: str = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    session: AsyncSession = Depends(get_async_session),
    _user: User = Depends(current_superuser),
):
    users, total = await admin_service.list_users(session, search, page, limit)
    return AdminUserList(
        items=[AdminUserRead.model_validate(u) for u in users],
        total=total,
    )


@router.post(
    "/users",
    response_model=AdminUserRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_local_auth_enabled)],
)
async def create_user(
    data: AdminUserCreate,
    session: AsyncSession = Depends(get_async_session),
    _user: User = Depends(current_superuser),
    user_manager: UserManager = Depends(get_user_manager),
):
    try:
        user = await admin_service.create_user(session, user_manager, data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return AdminUserRead.model_validate(user)


@router.get("/users/{user_id}", response_model=AdminUserRead)
async def get_user(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
    _user: User = Depends(current_superuser),
):
    user = await admin_service.get_user(session, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return AdminUserRead.model_validate(user)


@router.patch("/users/{user_id}", response_model=AdminUserRead)
async def update_user(
    user_id: uuid.UUID,
    data: AdminUserUpdate,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(current_superuser),
):
    if data.password is not None:
        require_local_auth_enabled()
    try:
        user = await admin_service.update_user(session, user_id, data, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return AdminUserRead.model_validate(user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(current_superuser),
):
    try:
        deleted = await admin_service.delete_user(session, user_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")


@router.get("/settings/{key}", response_model=AppSettingRead)
async def get_setting(
    key: str,
    session: AsyncSession = Depends(get_async_session),
    _user: User = Depends(current_superuser),
):
    if key in backup_config.SECRET_SETTING_KEYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Setting '{key}' is not readable",
        )
    setting = await admin_service.get_app_setting(session, key)
    if not setting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Setting not found")
    return AppSettingRead.model_validate(setting)


@router.patch("/settings/{key}", response_model=AppSettingRead)
async def update_setting(
    key: str,
    data: AppSettingUpdate,
    session: AsyncSession = Depends(get_async_session),
    _user: User = Depends(current_superuser),
):
    if key not in ALLOWED_SETTINGS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Setting '{key}' is not configurable",
        )
    if key == "timezone" and not is_valid_timezone(data.value):
        raise HTTPException(status_code=400, detail="Invalid IANA timezone")
    SETTING_VALIDATORS = {
        "registration_enabled": {"true", "false"},
        "credit_card_accounting_mode": {"cash", "accrual"},
        "number_format": {"auto", "comma_dot", "dot_comma", "space_comma"},
        "date_format": {"auto", "dmy", "mdy", "ymd"},
    }

    if key in SETTING_VALIDATORS and data.value not in SETTING_VALIDATORS[key]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid value for '{key}'. Allowed: {SETTING_VALIDATORS[key]}",
        )

    if key in ("theme_color_light", "theme_color_dark"):
        if not re.match(r"^#[0-9A-Fa-f]{6}$", data.value):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid hex color code for '{key}'. Expected format: #RRGGBB",
            )

    setting = await admin_service.set_app_setting(session, key, data.value)
    if key == "timezone":
        invalidate_timezone_cache()
    return AppSettingRead.model_validate(setting)


@router.delete("/settings/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_setting(
    key: str,
    session: AsyncSession = Depends(get_async_session),
    _user: User = Depends(current_superuser),
):
    """Forget a saved setting so the application falls back to its default."""
    if key not in ALLOWED_SETTINGS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Setting '{key}' is not configurable",
        )
    await admin_service.delete_app_setting(session, key)
    if key == "timezone":
        invalidate_timezone_cache()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/timezone", response_model=TimezoneSettingRead)
async def timezone_setting(
    session: AsyncSession = Depends(get_async_session),
    _user: User = Depends(current_superuser),
):
    return TimezoneSettingRead(
        timezone=str(app_timezone()),
        saved=await saved_timezone_name(session),
        fallback=str(environment_timezone()),
        available=sorted(timezone_names()),
    )


def _backup_settings_read(config: backup_config.BackupConfig) -> BackupSettingsRead:
    return BackupSettingsRead(
        storage_provider=config.storage_provider,
        backup_schedule_hour=config.backup_schedule_hour,
        backup_retention_count=config.backup_retention_count,
        backup_local_path=config.backup_local_path,
        backup_encryption_key_set=bool(config.backup_encryption_key),
        storage_s3_bucket=config.storage_s3_bucket,
        storage_s3_region=config.storage_s3_region,
        storage_s3_endpoint_url=config.storage_s3_endpoint_url,
        storage_s3_access_key_set=bool(config.storage_s3_access_key),
        storage_s3_secret_key_set=bool(config.storage_s3_secret_key),
    )


@router.get("/backup-settings", response_model=BackupSettingsRead)
async def get_backup_settings(
    session: AsyncSession = Depends(get_async_session),
    _user: User = Depends(current_superuser),
):
    """The effective backup configuration: saved overrides over env values.

    Secrets come back as *_set flags only.
    """
    config = await backup_config.get_backup_config(session)
    return _backup_settings_read(config)


@router.put("/backup-settings", response_model=BackupSettingsRead)
async def update_backup_settings(
    data: BackupSettingsUpdate,
    session: AsyncSession = Depends(get_async_session),
    _user: User = Depends(current_superuser),
):
    await backup_config.save_backup_settings(session, data)
    config = await backup_config.get_backup_config(session)
    return _backup_settings_read(config)


@router.post("/backup-settings/test-s3", response_model=BackupS3TestResult)
async def test_backup_s3(
    session: AsyncSession = Depends(get_async_session),
    _user: User = Depends(current_superuser),
    data: BackupS3TestRequest | None = None,
):
    """Probe the S3 bucket with the saved or just-submitted credentials."""
    success, error = await backup_config.test_s3_connection(session, data)
    return BackupS3TestResult(success=success, error=error)


@router.post("/backup/run", response_model=BackupRunResult)
async def run_backup_now(
    _user: User = Depends(current_superuser),
):
    """Enqueue the scheduled backup task immediately."""
    from app.worker import celery_app

    try:
        result = celery_app.send_task(
            "app.tasks.backup_tasks.scheduled_backup", kwargs={"force": True}
        )
    except Exception as exc:
        logger.warning("Backup dispatch failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Task queue unavailable",
        ) from exc
    return BackupRunResult(task_id=result.id)


@router.get("/registration-status")
async def registration_status(
    session: AsyncSession = Depends(get_async_session),
):
    enabled = await admin_service.is_registration_enabled(session)
    return {"enabled": enabled}


@router.get("/default-colors")
async def default_colors(
    session: AsyncSession = Depends(get_async_session),
):
    light = await admin_service.get_app_setting(session, "theme_color_light")
    dark = await admin_service.get_app_setting(session, "theme_color_dark")
    return {"light": light.value if light else None, "dark": dark.value if dark else None}


@router.get("/accounting-mode")
async def accounting_mode(
    session: AsyncSession = Depends(get_async_session),
    _user: User = Depends(current_active_user),
):
    mode = await admin_service.get_credit_card_accounting_mode(session)
    return {"mode": mode}


@router.get("/number-format")
async def number_format(
    session: AsyncSession = Depends(get_async_session),
    _user: User = Depends(current_active_user),
):
    """Global display format for numbers and dates. Readable by any signed-in
    user (not just admins) so the frontend can format consistently for everyone.
    Defaults to 'auto' - derive separators from each user's display currency."""
    fmt = await admin_service.get_number_format(session)
    return {"format": fmt}


@router.get("/date-format")
async def date_format(
    session: AsyncSession = Depends(get_async_session),
    _user: User = Depends(current_active_user),
):
    """Global display format for dates. Readable by any signed-in user.
    Defaults to 'auto' - derive the field order from the number format /
    display currency. Month names always follow the user's app language."""
    fmt = await admin_service.get_date_format(session)
    return {"format": fmt}


async def check_registration_enabled(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
):
    enabled = await admin_service.is_registration_enabled(session)
    if not enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registration is currently disabled",
        )
