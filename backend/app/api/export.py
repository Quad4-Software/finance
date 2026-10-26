from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.app_clock import app_today
from app.core.database import get_async_session
from app.core.workspace_context import WorkspaceContext, current_workspace
from app.schemas.export import BackupRequest
from app.services.backup_service import build_backup_archive, collect_workspace_export

router = APIRouter(prefix="/api/export", tags=["export"])


def _as_download(archive: bytes) -> StreamingResponse:
    today = app_today().isoformat()
    return StreamingResponse(
        iter([archive]),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="quad4-backup-{today}.zip"'},
    )


@router.get("/backup")
async def backup(
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    """Export every entity in the current workspace as a JSON zip.

    Backup is scoped to one workspace at a time -- users with multiple
    workspaces back each one up separately. AssetValue inherits its
    workspace from its Asset and is filtered transitively.
    """
    return _as_download(
        build_backup_archive(await collect_workspace_export(session, ctx.workspace))
    )


@router.post("/backup")
async def backup_protected(
    body: BackupRequest,
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    """The same archive, encrypted with AES-256 when a password is given.

    A POST because the password belongs in a body: a query string is written
    to browser history, proxy logs and server access logs. Quad4 Finance never stores
    the password and cannot recover the archive without it.
    """
    password = body.password.get_secret_value() if body.password else None
    return _as_download(
        build_backup_archive(await collect_workspace_export(session, ctx.workspace), password)
    )
