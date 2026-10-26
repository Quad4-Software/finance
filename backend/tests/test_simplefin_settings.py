"""Admin-configurable SimpleFIN settings: resolution, endpoints, provider flag."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_settings import AppSetting
from app.models.user import User
from app.providers import _PROVIDERS, refresh_provider_flags
from app.schemas.admin import SimplefinSettingsUpdate
from app.services import simplefin_config

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _restore_provider_registry():
    """Undo any registration change a test made through the runtime flag."""
    snapshot = dict(_PROVIDERS)
    yield
    _PROVIDERS.clear()
    _PROVIDERS.update(snapshot)


class TestEffectiveConfig:
    """Saved app_settings rows override the env-derived config."""

    async def test_env_defaults(self, session: AsyncSession, clean_db):
        config = await simplefin_config.get_simplefin_config(session)

        assert config.simplefin_enabled is False
        assert config.simplefin_api_url == "https://beta-bridge.simplefin.org"

    async def test_stored_overrides(self, session: AsyncSession, clean_db):
        session.add_all(
            [
                AppSetting(key="simplefin_enabled", value="true"),
                AppSetting(key="simplefin_api_url", value="https://bridge.simplefin.org"),
            ]
        )
        await session.commit()

        config = await simplefin_config.get_simplefin_config(session)

        assert config.simplefin_enabled is True
        assert config.simplefin_api_url == "https://bridge.simplefin.org"

    async def test_stored_disable_beats_env(self, session: AsyncSession, clean_db):
        """A saved 'false' wins over SIMPLEFIN_ENABLED=true in the env."""
        from unittest.mock import patch

        session.add(AppSetting(key="simplefin_enabled", value="false"))
        await session.commit()

        with patch(
            "app.services.simplefin_config.get_settings"
        ) as mock_settings:
            mock_settings.return_value.simplefin_enabled = True
            mock_settings.return_value.simplefin_api_url = "https://x.example"
            config = await simplefin_config.get_simplefin_config(session)

        assert config.simplefin_enabled is False

    async def test_empty_string_clears_override(self, session: AsyncSession, clean_db):
        await simplefin_config.save_simplefin_settings(
            session,
            SimplefinSettingsUpdate(
                simplefin_enabled=True,
                simplefin_api_url="https://bridge.simplefin.org",
            ),
        )
        await simplefin_config.save_simplefin_settings(
            session, SimplefinSettingsUpdate(simplefin_api_url="")
        )

        assert await session.get(AppSetting, "simplefin_api_url") is None
        # The untouched flag override is still stored.
        config = await simplefin_config.get_simplefin_config(session)
        assert config.simplefin_enabled is True
        assert config.simplefin_api_url == "https://beta-bridge.simplefin.org"

    async def test_bool_serialized_lowercase(self, session: AsyncSession, clean_db):
        await simplefin_config.save_simplefin_settings(
            session, SimplefinSettingsUpdate(simplefin_enabled=True)
        )

        row = await session.get(AppSetting, "simplefin_enabled")
        assert row is not None
        assert row.value == "true"


class TestSimplefinSettingsApi:
    """GET/PUT /api/admin/simplefin-settings."""

    async def test_get_effective_settings(
        self, client: AsyncClient, admin_auth_headers: dict, test_superuser: User
    ):
        response = await client.get(
            "/api/admin/simplefin-settings", headers=admin_auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["simplefin_enabled"] is False
        assert data["simplefin_api_url"] == "https://beta-bridge.simplefin.org"

    async def test_put_persists_overrides(
        self,
        client: AsyncClient,
        admin_auth_headers: dict,
        test_superuser: User,
        session: AsyncSession,
    ):
        response = await client.put(
            "/api/admin/simplefin-settings",
            json={
                "simplefin_enabled": True,
                "simplefin_api_url": "https://bridge.simplefin.org",
            },
            headers=admin_auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["simplefin_enabled"] is True
        assert data["simplefin_api_url"] == "https://bridge.simplefin.org"

        row = await session.get(AppSetting, "simplefin_enabled")
        assert row is not None
        assert row.value == "true"

    @pytest.mark.parametrize(
        "payload",
        [
            {"simplefin_enabled": "not-a-bool"},
            {"simplefin_api_url": 42},
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
            "/api/admin/simplefin-settings", json=payload, headers=admin_auth_headers
        )
        assert response.status_code == 422

    async def test_put_toggles_provider_registration(
        self,
        client: AsyncClient,
        admin_auth_headers: dict,
        test_superuser: User,
    ):
        """Saving enabled=true registers the provider without a restart."""
        _PROVIDERS.pop("simplefin", None)

        response = await client.put(
            "/api/admin/simplefin-settings",
            json={"simplefin_enabled": True},
            headers=admin_auth_headers,
        )

        assert response.status_code == 200
        assert "simplefin" in _PROVIDERS

    async def test_providers_endpoint_reads_effective_flag(
        self,
        client: AsyncClient,
        admin_auth_headers: dict,
        auth_headers: dict,
        test_superuser: User,
        test_user: User,
        session: AsyncSession,
    ):
        """The connections providers listing reflects the DB-side enable."""
        session.add(AppSetting(key="simplefin_enabled", value="true"))
        await session.commit()

        response = await client.get("/api/connections/providers", headers=auth_headers)

        assert response.status_code == 200
        simplefin = next(
            p for p in response.json()["providers"] if p["name"] == "simplefin"
        )
        assert simplefin["configured"] is True
        assert simplefin["connect_url"].endswith("/simplefin/create")

    async def test_disabled_clears_registration(
        self, session: AsyncSession, clean_db
    ):
        from app.providers import register_provider
        from app.providers.simplefin import SimpleFinProvider

        session.add(AppSetting(key="simplefin_enabled", value="false"))
        await session.commit()
        # Pretend env registration had put the provider in the registry.
        register_provider("simplefin", SimpleFinProvider)

        await refresh_provider_flags(session)

        assert "simplefin" not in _PROVIDERS

    async def test_non_admin_forbidden(
        self, client: AsyncClient, auth_headers: dict, test_user: User
    ):
        response = await client.get(
            "/api/admin/simplefin-settings", headers=auth_headers
        )
        assert response.status_code == 403

    async def test_anon_unauthenticated(self, client: AsyncClient):
        response = await client.get("/api/admin/simplefin-settings")
        assert response.status_code == 401
