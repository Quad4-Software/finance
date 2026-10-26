from app.providers.base import (
    AccountData,
    BankProvider,
    ConnectTokenData,
    ConnectionData,
    HoldingData,
    InstitutionData,
    InstitutionListData,
    ProviderUserActionRequired,
    RefreshOutcome,
    SessionExpiredError,
    TransactionData,
)

# Registry of available providers.
_PROVIDERS: dict[str, type[BankProvider]] = {}

# All known providers the system supports (extensible for future connectors).
KNOWN_PROVIDERS = [
    {
        "name": "enable_banking",
        "display_name": "Enable Banking",
        "description": "European banks via PSD2 open banking",
        "flow_type": "oauth",
        "requires_institution_select": True,
        "supports_asset_sync": False,
    },
    {
        "name": "simplefin",
        "display_name": "SimpleFIN",
        "description": "US and international banks via SimpleFIN Bridge",
        "flow_type": "token",
        "requires_institution_select": False,
        "supports_asset_sync": True,
    },
]


def register_provider(name: str, cls: type[BankProvider]) -> None:
    """Register a bank provider implementation."""
    _PROVIDERS[name] = cls


# Extra fields merged into each KNOWN_PROVIDERS entry by all_known_providers,
# populated from the effective admin config by refresh_provider_flags.
_PROVIDER_EXTRAS: dict[str, dict] = {}


def get_provider(name: str) -> BankProvider:
    """Get an instance of a registered bank provider by name."""
    provider_class = _PROVIDERS.get(name)
    if not provider_class:
        available = ", ".join(_PROVIDERS.keys()) or "(none)"
        raise ValueError(f"Unknown provider: {name}. Available: {available}")
    return provider_class()


def list_providers() -> list[dict[str, str]]:
    """Return info about all registered providers."""
    return [{"name": name, "flow_type": cls().flow_type} for name, cls in _PROVIDERS.items()]


def all_known_providers() -> list[dict]:
    """Return all known providers with a configured flag."""
    return [
        {
            **p,
            **_PROVIDER_EXTRAS.get(p["name"], {}),
            "configured": p["name"] in _PROVIDERS,
        }
        for p in KNOWN_PROVIDERS
    ]


async def refresh_provider_flags(session) -> None:
    """Sync the registry with admin-saved provider settings.

    Registration at import time only sees the environment; the admin
    settings stored in app_settings override it without a restart. Callers
    holding a session invoke this before listing providers or resolving one
    for a connect/sync so the effective flag applies. Currently only
    SimpleFIN is admin-configurable.
    """
    from app.services.simplefin_config import get_simplefin_config

    config = await get_simplefin_config(session)
    if config.simplefin_enabled:
        from app.providers.simplefin import SimpleFinProvider

        register_provider("simplefin", SimpleFinProvider)
    else:
        _PROVIDERS.pop("simplefin", None)
    api_url = config.simplefin_api_url.rstrip("/")
    _PROVIDER_EXTRAS["simplefin"] = {
        "connect_url": f"{api_url}/simplefin/create" if api_url else None,
    }


def _auto_register_providers() -> None:
    """Auto-register providers when credentials are configured."""
    from app.core.config import get_settings

    settings = get_settings()

    eb_has_key = bool(
        settings.enable_banking_private_key or settings.enable_banking_private_key_file
    )
    if settings.enable_banking_app_id and eb_has_key:
        from app.providers.enable_banking import EnableBankingProvider

        register_provider("enable_banking", EnableBankingProvider)

    if settings.simplefin_enabled:
        from app.providers.simplefin import SimpleFinProvider

        register_provider("simplefin", SimpleFinProvider)


_auto_register_providers()


_storage_provider = None


def get_storage_provider():
    """Get the configured storage provider (singleton)."""
    global _storage_provider
    if _storage_provider is None:
        from app.core.config import get_settings

        settings = get_settings()
        if settings.storage_provider == "local":
            from app.providers.local_storage import LocalStorageProvider

            _storage_provider = LocalStorageProvider()
        elif settings.storage_provider == "s3":
            from app.providers.s3_storage import S3StorageProvider

            _storage_provider = S3StorageProvider()
        else:
            raise NotImplementedError(
                f"Storage provider '{settings.storage_provider}' is not implemented. "
                "Supported: 'local', 's3'"
            )
    return _storage_provider


__all__ = [
    "BankProvider",
    "AccountData",
    "TransactionData",
    "ConnectionData",
    "ConnectTokenData",
    "HoldingData",
    "InstitutionData",
    "InstitutionListData",
    "ProviderUserActionRequired",
    "RefreshOutcome",
    "SessionExpiredError",
    "register_provider",
    "get_provider",
    "list_providers",
    "all_known_providers",
    "get_storage_provider",
]
