"""Admin-configurable backup settings: resolution, endpoints, S3 probe."""

from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_settings import AppSetting
from app.models.user import User
from app.schemas.admin import BackupSettingsUpdate
from app.services import backup_config

pytestmark = pytest.mark.asyncio


class TestEffectiveConfig:
    """Saved app_settings rows override the env-derived config."""

    async def test_env_defaults(self, session: AsyncSession, clean_db):
        config = await backup_config.get_backup_config(session)

        assert config.storage_provider == "local"
        assert config.backup_schedule_hour == 3
        assert config.backup_retention_count == 14
        assert config.backup_local_path == "./data/backups"
        assert config.storage_s3_bucket == ""

    async def test_stored_overrides(self, session: AsyncSession, clean_db):
        session.add_all(
            [
                AppSetting(key="storage_provider", value="s3"),
                AppSetting(key="backup_schedule_hour", value="5"),
                AppSetting(key="backup_retention_count", value="30"),
                AppSetting(key="backup_local_path", value="/mnt/backups"),
                AppSetting(key="storage_s3_bucket", value="saved-bucket"),
                AppSetting(key="storage_s3_region", value="eu-west-1"),
            ]
        )
        await session.commit()

        config = await backup_config.get_backup_config(session)

        assert config.storage_provider == "s3"
        assert config.backup_schedule_hour == 5
        assert config.backup_retention_count == 30
        assert config.backup_local_path == "/mnt/backups"
        assert config.storage_s3_bucket == "saved-bucket"
        assert config.storage_s3_region == "eu-west-1"

    async def test_invalid_stored_values_fall_back(self, session: AsyncSession, clean_db):
        session.add_all(
            [
                AppSetting(key="storage_provider", value="carrier-pigeon"),
                AppSetting(key="backup_schedule_hour", value="not-an-int"),
            ]
        )
        await session.commit()

        config = await backup_config.get_backup_config(session)

        assert config.storage_provider == "local"
        assert config.backup_schedule_hour == 3

    async def test_secret_round_trip(self, session: AsyncSession, clean_db):
        await backup_config.save_backup_settings(
            session, BackupSettingsUpdate(backup_encryption_key="top-secret")
        )

        row = await session.get(AppSetting, "backup_encryption_key")
        assert row is not None
        assert row.value != "top-secret"

        config = await backup_config.get_backup_config(session)
        assert config.backup_encryption_key == "top-secret"

    async def test_empty_secret_clears_override(self, session: AsyncSession, clean_db):
        await backup_config.save_backup_settings(
            session, BackupSettingsUpdate(backup_encryption_key="top-secret")
        )
        await backup_config.save_backup_settings(
            session, BackupSettingsUpdate(backup_encryption_key="")
        )

        assert await session.get(AppSetting, "backup_encryption_key") is None
        config = await backup_config.get_backup_config(session)
        assert config.backup_encryption_key == ""


class TestBackupSettingsApi:
    """GET/PUT /api/admin/backup-settings."""

    async def test_get_effective_settings(
        self, client: AsyncClient, admin_auth_headers: dict, test_superuser: User
    ):
        response = await client.get("/api/admin/backup-settings", headers=admin_auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["storage_provider"] == "local"
        assert data["backup_schedule_hour"] == 3
        assert data["backup_retention_count"] == 14
        assert data["backup_encryption_key_set"] is False
        assert data["storage_s3_access_key_set"] is False
        assert data["storage_s3_secret_key_set"] is False

    async def test_put_persists_overrides(
        self,
        client: AsyncClient,
        admin_auth_headers: dict,
        test_superuser: User,
        session: AsyncSession,
    ):
        response = await client.put(
            "/api/admin/backup-settings",
            json={
                "storage_provider": "s3",
                "backup_schedule_hour": 22,
                "backup_retention_count": 7,
                "backup_encryption_key": "correct-horse",
                "storage_s3_bucket": "quad4-backups",
                "storage_s3_access_key": "AKIATEST",
                "storage_s3_secret_key": "s3cr3t",
            },
            headers=admin_auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["storage_provider"] == "s3"
        assert data["backup_schedule_hour"] == 22
        assert data["backup_retention_count"] == 7
        assert data["storage_s3_bucket"] == "quad4-backups"
        assert data["backup_encryption_key_set"] is True
        assert data["storage_s3_access_key_set"] is True
        assert data["storage_s3_secret_key_set"] is True
        # Secrets are write-only: never echoed back.
        assert "correct-horse" not in response.text
        assert "AKIATEST" not in response.text
        assert "s3cr3t" not in response.text

        row = await session.get(AppSetting, "backup_encryption_key")
        assert row is not None
        assert row.value != "correct-horse"

    @pytest.mark.parametrize(
        "payload",
        [
            {"backup_schedule_hour": 24},
            {"backup_schedule_hour": -1},
            {"backup_retention_count": 0},
            {"storage_provider": "ftp"},
        ],
    )
    async def test_put_rejects_invalid_values(
        self,
        client: AsyncClient,
        admin_auth_headers: dict,
        test_superuser: User,
        payload: dict,
    ):
        response = await client.put(
            "/api/admin/backup-settings", json=payload, headers=admin_auth_headers
        )
        assert response.status_code == 422

    async def test_secret_not_readable_via_generic_settings(
        self,
        client: AsyncClient,
        admin_auth_headers: dict,
        test_superuser: User,
        session: AsyncSession,
    ):
        await backup_config.save_backup_settings(
            session, BackupSettingsUpdate(backup_encryption_key="top-secret")
        )

        response = await client.get(
            "/api/admin/settings/backup_encryption_key", headers=admin_auth_headers
        )
        assert response.status_code == 400

    async def test_non_admin_forbidden(
        self, client: AsyncClient, auth_headers: dict, test_user: User
    ):
        response = await client.get("/api/admin/backup-settings", headers=auth_headers)
        assert response.status_code == 403

    async def test_anon_unauthenticated(self, client: AsyncClient):
        response = await client.get("/api/admin/backup-settings")
        assert response.status_code == 401


class TestS3ConnectionProbe:
    """POST /api/admin/backup-settings/test-s3."""

    async def test_no_bucket_configured(
        self, client: AsyncClient, admin_auth_headers: dict, test_superuser: User
    ):
        response = await client.post(
            "/api/admin/backup-settings/test-s3", json={}, headers=admin_auth_headers
        )

        assert response.status_code == 200
        assert response.json() == {"success": False, "error": "No S3 bucket configured"}

    async def test_success(
        self,
        client: AsyncClient,
        admin_auth_headers: dict,
        test_superuser: User,
        session: AsyncSession,
    ):
        session.add(AppSetting(key="storage_s3_bucket", value="quad4-backups"))
        await session.commit()

        mock_client = MagicMock()
        with patch("boto3.client", return_value=mock_client) as boto3_client:
            response = await client.post(
                "/api/admin/backup-settings/test-s3", json={}, headers=admin_auth_headers
            )

        assert response.status_code == 200
        assert response.json() == {"success": True, "error": None}
        boto3_client.assert_called_once()
        assert boto3_client.call_args.args == ("s3",)
        mock_client.head_bucket.assert_called_once_with(Bucket="quad4-backups")

    async def test_submitted_credentials_win(
        self,
        client: AsyncClient,
        admin_auth_headers: dict,
        test_superuser: User,
    ):
        mock_client = MagicMock()
        with patch("boto3.client", return_value=mock_client) as boto3_client:
            response = await client.post(
                "/api/admin/backup-settings/test-s3",
                json={
                    "storage_s3_bucket": "unsaved-bucket",
                    "storage_s3_region": "us-east-1",
                    "storage_s3_endpoint_url": "http://localhost:9000",
                    "storage_s3_access_key": "AKIAUNSAVE",
                    "storage_s3_secret_key": "unsaved-secret",
                },
                headers=admin_auth_headers,
            )

        assert response.status_code == 200
        assert response.json()["success"] is True
        kwargs = boto3_client.call_args.kwargs
        assert kwargs["region_name"] == "us-east-1"
        assert kwargs["endpoint_url"] == "http://localhost:9000"
        assert kwargs["aws_access_key_id"] == "AKIAUNSAVE"
        assert kwargs["aws_secret_access_key"] == "unsaved-secret"
        mock_client.head_bucket.assert_called_once_with(Bucket="unsaved-bucket")

    async def test_failure_returns_safe_error(
        self,
        client: AsyncClient,
        admin_auth_headers: dict,
        test_superuser: User,
        session: AsyncSession,
    ):
        session.add(AppSetting(key="storage_s3_bucket", value="quad4-backups"))
        await session.commit()

        mock_client = MagicMock()
        mock_client.head_bucket.side_effect = RuntimeError("endpoint unreachable")
        with patch("boto3.client", return_value=mock_client):
            response = await client.post(
                "/api/admin/backup-settings/test-s3", json={}, headers=admin_auth_headers
            )

        assert response.status_code == 200
        assert response.json() == {"success": False, "error": "endpoint unreachable"}


class TestRunBackupNow:
    """POST /api/admin/backup/run."""

    async def test_enqueues_task(
        self, client: AsyncClient, admin_auth_headers: dict, test_superuser: User
    ):
        from app.worker import celery_app

        with patch.object(
            celery_app, "send_task", return_value=MagicMock(id="task-123")
        ) as send_task:
            response = await client.post("/api/admin/backup/run", headers=admin_auth_headers)

        assert response.status_code == 200
        assert response.json() == {"task_id": "task-123", "status": "queued"}
        send_task.assert_called_once_with(
            "app.tasks.backup_tasks.scheduled_backup", kwargs={"force": True}
        )

    async def test_broker_unavailable(
        self, client: AsyncClient, admin_auth_headers: dict, test_superuser: User
    ):
        from app.worker import celery_app

        with patch.object(celery_app, "send_task", side_effect=OSError("no broker")):
            response = await client.post("/api/admin/backup/run", headers=admin_auth_headers)

        assert response.status_code == 503

    async def test_non_admin_forbidden(
        self, client: AsyncClient, auth_headers: dict, test_user: User
    ):
        response = await client.post("/api/admin/backup/run", headers=auth_headers)
        assert response.status_code == 403
