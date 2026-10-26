"""Effective SimpleFIN provider configuration.

Values saved through the admin API live in the app_settings table and
override the matching environment variables wherever the provider is
registered or listed. Neither field is a secret, so values are stored
in plaintext - unlike the backup settings there is nothing to encrypt.
"""

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.app_settings import AppSetting
from app.schemas.admin import SimplefinSettingsUpdate

logger = logging.getLogger(__name__)

#: app_settings keys backing the admin SimpleFIN form.
SIMPLEFIN_SETTING_KEYS = (
    "simplefin_enabled",
    "simplefin_api_url",
)


@dataclass(frozen=True)
class SimplefinConfig:
    """The SimpleFIN configuration after admin overrides over env defaults."""

    simplefin_enabled: bool
    simplefin_api_url: str


def _bool_or(value: str | None, fallback: bool) -> bool:
    if value is None:
        return fallback
    return value.strip().lower() in ("true", "1", "yes", "on")


async def _stored_values(session: AsyncSession) -> dict[str, str]:
    rows = (
        await session.execute(
            select(AppSetting).where(AppSetting.key.in_(SIMPLEFIN_SETTING_KEYS))
        )
    ).scalars()
    return {row.key: row.value for row in rows}


async def get_simplefin_config(session: AsyncSession) -> SimplefinConfig:
    """Saved admin settings merged over the env-derived defaults."""
    settings = get_settings()
    stored = await _stored_values(session)

    return SimplefinConfig(
        simplefin_enabled=_bool_or(
            stored.get("simplefin_enabled"), settings.simplefin_enabled
        ),
        simplefin_api_url=stored.get("simplefin_api_url") or settings.simplefin_api_url,
    )


async def _upsert(session: AsyncSession, key: str, value: str) -> None:
    row = await session.get(AppSetting, key)
    if row is None:
        session.add(AppSetting(key=key, value=value))
    else:
        row.value = value


async def save_simplefin_settings(session: AsyncSession, data: SimplefinSettingsUpdate) -> None:
    """Persist the fields the update carries.

    Unset fields leave the stored row alone. An empty string deletes the
    stored override so the environment value applies again.
    """
    for key, value in data.model_dump(exclude_unset=True).items():
        if value is None:
            continue
        if value == "":
            row = await session.get(AppSetting, key)
            if row is not None:
                await session.delete(row)
        elif isinstance(value, bool):
            await _upsert(session, key, "true" if value else "false")
        else:
            await _upsert(session, key, str(value))
    await session.commit()
