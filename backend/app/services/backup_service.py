"""Packing a workspace backup into a zip, optionally encrypted.

The archive is the user's own copy of their data, so it stays a plain zip of
plain JSON by default: anything that can open a zip can read it, today and in
ten years. A password swaps the container for an AES-256 one (WinZip AES, the
scheme 7-Zip, Keka and WinRAR all speak) so the file stays openable by ordinary
tools while the contents travel safely through whatever cloud or drive the user
keeps it on.

AES rather than the legacy ZipCrypto that "password-protected zip" often means:
ZipCrypto's key is recoverable from a few known plaintext bytes, and a backup
full of JSON is nothing but known plaintext.
"""

import asyncio
import base64
import hashlib
import io
import json
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pyzipper
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

#: The zip encrypts entry *contents*, never the central directory, so the file
#: names and their sizes stay readable without the password. Nothing sensitive
#: goes in a name - they are the fixed entity names below plus `metadata.json`.
_COMPRESSION = zipfile.ZIP_DEFLATED


def build_backup_archive(files: dict[str, object], password: str | None = None) -> bytes:
    """Serialize `files` (name -> JSON-serializable payload) into a zip.

    Returns the archive bytes. With a password the entries are encrypted with
    AES-256; without one the result is byte-for-byte the plain zip Quad4 Finance has
    always produced.
    """
    buf = io.BytesIO()
    if password:
        archive = pyzipper.AESZipFile(
            buf, "w", compression=_COMPRESSION, encryption=pyzipper.WZ_AES
        )
        archive.setpassword(password.encode("utf-8"))
    else:
        archive = zipfile.ZipFile(buf, "w", _COMPRESSION)

    with archive as zf:
        for name, payload in files.items():
            zf.writestr(name, json.dumps(payload, indent=2, ensure_ascii=False))

    return buf.getvalue()


def _serialize(obj) -> dict:
    """Convert a SQLAlchemy model instance to a JSON-serializable dict."""
    d = {}
    for col in obj.__table__.columns:
        val = getattr(obj, col.key)
        if isinstance(val, UUID):
            val = str(val)
        elif isinstance(val, (datetime, date)):
            val = val.isoformat()
        elif isinstance(val, Decimal):
            val = str(val)
        d[col.key] = val
    return d


async def collect_workspace_export(session: AsyncSession, workspace) -> dict[str, object]:
    """Every entity in the workspace, keyed by the file it becomes.

    Shared by the interactive /api/export/backup endpoint and the scheduled
    Celery backup so both produce the same archive contents.
    """
    from app.models.account import Account
    from app.models.asset import Asset
    from app.models.asset_value import AssetValue
    from app.models.budget import Budget
    from app.models.category import Category
    from app.models.category_group import CategoryGroup
    from app.models.import_log import ImportLog
    from app.models.recurring_transaction import RecurringTransaction
    from app.models.rule import Rule
    from app.models.transaction import Transaction

    ws_id = workspace.id
    accounts = (
        (await session.execute(select(Account).where(Account.workspace_id == ws_id)))
        .scalars()
        .all()
    )
    transactions = (
        (await session.execute(select(Transaction).where(Transaction.workspace_id == ws_id)))
        .scalars()
        .all()
    )
    categories = (
        (await session.execute(select(Category).where(Category.workspace_id == ws_id)))
        .scalars()
        .all()
    )
    category_groups = (
        (await session.execute(select(CategoryGroup).where(CategoryGroup.workspace_id == ws_id)))
        .scalars()
        .all()
    )
    rules = (await session.execute(select(Rule).where(Rule.workspace_id == ws_id))).scalars().all()
    recurring_transactions = (
        (
            await session.execute(
                select(RecurringTransaction).where(RecurringTransaction.workspace_id == ws_id)
            )
        )
        .scalars()
        .all()
    )
    budgets = (
        (await session.execute(select(Budget).where(Budget.workspace_id == ws_id))).scalars().all()
    )
    assets = (
        (await session.execute(select(Asset).where(Asset.workspace_id == ws_id))).scalars().all()
    )
    import_logs = (
        (await session.execute(select(ImportLog).where(ImportLog.workspace_id == ws_id)))
        .scalars()
        .all()
    )

    asset_ids = [a.id for a in assets]
    if asset_ids:
        asset_values = (
            (await session.execute(select(AssetValue).where(AssetValue.asset_id.in_(asset_ids))))
            .scalars()
            .all()
        )
    else:
        asset_values = []

    entities = {
        "accounts": accounts,
        "transactions": transactions,
        "categories": categories,
        "category_groups": category_groups,
        "rules": rules,
        "recurring_transactions": recurring_transactions,
        "budgets": budgets,
        "assets": assets,
        "asset_values": asset_values,
        "import_logs": import_logs,
    }

    files: dict[str, object] = {}
    entity_counts = {}
    for name, rows in entities.items():
        serialized = [_serialize(r) for r in rows]
        entity_counts[name] = len(serialized)
        files[f"{name}.json"] = serialized

    files["metadata.json"] = {
        "export_date": datetime.now(timezone.utc).isoformat(),
        "format_version": "1.0",
        "workspace_id": str(ws_id),
        "workspace_name": workspace.name,
        "entity_counts": entity_counts,
    }
    return files


# ---------------------------------------------------------------------------
# Scheduled backups: encryption key + storage backend
# ---------------------------------------------------------------------------

#: Salt for deriving the scheduled-backup password from SECRET_KEY when no
#: dedicated BACKUP_ENCRYPTION_KEY is configured. Same PBKDF2-SHA256 pattern
#: as app.agents.services.crypto.
_BACKUP_KEY_SALT = b"quad4-scheduled-backups-v1"


def scheduled_backup_password() -> str:
    """The AES-256 passphrase used for scheduled backup archives.

    An explicit BACKUP_ENCRYPTION_KEY wins; otherwise a passphrase is
    derived from SECRET_KEY so the feature works zero-config while staying
    encrypted at rest. Rotating SECRET_KEY changes the derived password,
    which only affects archives written afterwards.
    """
    from app.core.config import get_settings

    settings = get_settings()
    explicit = settings.backup_encryption_key.get_secret_value()
    if explicit:
        return explicit
    secret = settings.secret_key.get_secret_value().encode("utf-8")
    raw = hashlib.pbkdf2_hmac("sha256", secret, _BACKUP_KEY_SALT, iterations=100_000, dklen=32)
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _backup_key(workspace_id: UUID, filename: str) -> str:
    return f"backups/{workspace_id}/{filename}"


def _local_backup_dir(workspace_id: UUID) -> Path:
    from app.core.config import get_settings

    return Path(get_settings().backup_local_path) / str(workspace_id)


async def store_backup(workspace_id: UUID, filename: str, data: bytes) -> str:
    """Persist one archive under the configured backend. Returns the key/path."""
    from app.core.config import get_settings

    settings = get_settings()
    if settings.storage_provider == "s3":
        from app.providers import get_storage_provider

        key = _backup_key(workspace_id, filename)
        await get_storage_provider().upload(key, data, "application/zip")
        return key
    path = _local_backup_dir(workspace_id) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(path.write_bytes, data)
    return str(path)


async def list_backup_names(workspace_id: UUID) -> list[str]:
    """Existing backup filenames for one workspace, oldest first."""
    from app.core.config import get_settings

    settings = get_settings()
    if settings.storage_provider == "s3":
        from app.providers import get_storage_provider

        provider = get_storage_provider()
        prefix = f"backups/{workspace_id}/"
        keys = await provider.list_keys(prefix)
        return sorted(k[len(prefix) :] for k in keys if k.startswith(prefix))
    directory = _local_backup_dir(workspace_id)
    if not directory.exists():
        return []
    return sorted(p.name for p in directory.glob("*.zip"))


async def delete_backup(workspace_id: UUID, filename: str) -> None:
    from app.core.config import get_settings

    settings = get_settings()
    if settings.storage_provider == "s3":
        from app.providers import get_storage_provider

        await get_storage_provider().delete(_backup_key(workspace_id, filename))
        return
    path = _local_backup_dir(workspace_id) / filename
    if path.exists():
        path.unlink()
