"""Scheduled per-workspace backups to the configured storage backend.

Runs daily via Celery beat. For every workspace it builds the same archive
the /api/export/backup endpoint streams, encrypts it with AES-256, stores
it under backups/<workspace_id>/, and prunes archives beyond
BACKUP_RETENTION_COUNT.
"""

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.services import backup_service
from app.worker import celery_app

logger = logging.getLogger(__name__)


def _make_session_maker():
    """Create a fresh engine+session for the Celery worker event loop."""
    engine = create_async_engine(get_settings().database_url)
    return engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _backup_one_workspace(session: AsyncSession, workspace, now: datetime) -> str:
    files = await backup_service.collect_workspace_export(session, workspace)
    archive = backup_service.build_backup_archive(files, backup_service.scheduled_backup_password())
    filename = f"quad4-backup-{now:%Y%m%d-%H%M}.zip"
    return await backup_service.store_backup(workspace.id, filename, archive)


async def _prune_backups(workspace_id, retention: int) -> int:
    names = await backup_service.list_backup_names(workspace_id)
    deleted = 0
    for name in names[:-retention] if retention else names:
        await backup_service.delete_backup(workspace_id, name)
        deleted += 1
    return deleted


async def _run() -> dict:
    from app.models.workspace import Workspace

    settings = get_settings()
    engine, session_maker = _make_session_maker()
    now = datetime.now(timezone.utc)
    backed_up = 0
    pruned = 0
    try:
        async with session_maker() as session:
            workspace_ids = (await session.execute(select(Workspace.id))).scalars().all()

        for ws_id in workspace_ids:
            try:
                async with session_maker() as session:
                    workspace = await session.get(Workspace, ws_id)
                    if workspace is None:
                        continue
                    key = await _backup_one_workspace(session, workspace, now)
                pruned += await _prune_backups(ws_id, settings.backup_retention_count)
                backed_up += 1
                logger.info("Scheduled backup stored at %s", key)
            except Exception:
                logger.exception("Scheduled backup failed for workspace %s", ws_id)
    finally:
        await engine.dispose()
    return {"workspaces": len(workspace_ids), "backed_up": backed_up, "pruned": pruned}


@celery_app.task(name="app.tasks.backup_tasks.scheduled_backup")
def scheduled_backup() -> dict:
    """Celery task: archive every workspace to the configured storage."""
    result = asyncio.run(_run())
    logger.info("Scheduled backup complete: %s", result)
    return result
