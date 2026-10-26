<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="favicons/quad4-mark.svg" />
    <source media="(prefers-color-scheme: light)" srcset="favicons/quad4-mark-black.svg" />
    <img src="favicons/quad4-mark.svg" width="160" alt="Quad4" />
  </picture>
</p>

<h3 align="center">Finance apps want your data. This one doesn't.</h3>

<p align="center">
Quad4 Finance is a security-hardened fork of <a href="https://github.com/securo-finance/securo">Securo</a>: a self-hosted, open-source finance manager that keeps every byte of your financial data on your own infrastructure. This fork strips third-party bank widgets, removes Brazil-specific integrations, and rebuilds the deployment for extreme security and privacy: rootless Chainguard images, kernel-level sandboxing with Landlock and seccomp, and encrypted off-site backups.
</p>

## Quick Start

**Linux & macOS** (uses Docker or Podman; installs Docker if neither is present):

```bash
git clone https://github.com/Quad4-Software/finance.git && cd finance
./install.sh
```

Or manually:

```bash
cp .env.example .env   # set SECRET_KEY and POSTGRES_PASSWORD
docker compose -f docker-compose.prod.yml up -d
```

Open [http://localhost:3000](http://localhost:3000) and create an account.

## Security model

- **Rootless, minimal images.** Both services build on Chainguard images (Wolfi-based, near-zero CVEs, nonroot by default). The production compose file adds `read_only` root filesystems, `cap_drop: ALL`, `no-new-privileges` and tmpfs-only scratch space.
- **Kernel sandboxing.** The API, Celery worker and beat processes self-sandbox at startup: Landlock restricts filesystem access to the data and secrets directories, and a seccomp-BPF denylist blocks dangerous syscalls (mount, ptrace, kexec, bpf, key management, module loading, namespace escapes). No extra privileges required; both degrade gracefully on kernels without support. Toggle via `SANDBOX_*` env vars.
- **Encrypted backups.** On-demand export produces AES-256 encrypted archives (pyzipper). A daily scheduled job writes encrypted per-workspace backups to local disk or S3-compatible object storage with retention. Set `BACKUP_ENCRYPTION_KEY` to keep backups decryptable independent of `SECRET_KEY` rotation.
- **Secrets hygiene.** All secrets can come from files (`/run/secrets`, systemd `CREDENTIALS_DIRECTORY`) instead of environment variables. Bank credentials are stored encrypted at rest (Fernet over a PBKDF2-derived key).
- **Hardened HTTP.** Security headers at both nginx (CSP, nosniff, frame-ancestors) and the API layer; strict rate limiting on auth endpoints; TOTP and WebAuthn/passkey support.
- **Supply chain.** All GitHub Actions are pinned to commit SHAs with hardened runners and zizmor static analysis; images ship with SLSA provenance, SBOMs and keyless cosign signatures; Python deps install from a frozen lockfile with hash checking.

## Features

- Multi-account management with running balances
- Transaction management with search, filters, and CSV export
- File import (OFX, QIF, CAMT, CSV)
- Auto-categorization rules engine
- Recurring transactions and budgets
- Goals and savings targets with progress tracking
- Asset management with valuation tracking and growth rules
- Reports: Net Worth and Income vs Expenses with category sparklines
- Bank sync via Enable Banking (~2500 European PSD2 banks) and SimpleFIN (US and international); extensible provider layer
- Multi-currency support with automatic FX conversion
- Multi-user support with admin panel and registration controls
- Two-factor authentication (TOTP) with brute-force protection
- Passkeys (WebAuthn) and OIDC login (Authentik, Pocket ID, standard providers)
- AI Agents (optional, off by default): self-hosted LLM chat with tool-use over your data, plus a per-agent RAG knowledge base

## Bank Sync (Optional)

Add credentials for a supported provider to `.env`, then restart with `docker compose -f docker-compose.prod.yml up -d`. Each provider auto-registers when its credentials are present.

See [automatic bank synchronization](docs/automatic-bank-sync.md) to configure the minimum polling interval (including PSD2 four-access-per-day limits).

### Enable Banking -- European banks (PSD2)

Sign up at [enablebanking.com](https://enablebanking.com), create a Production application, and download its PEM private key. Save the PEM to `./secrets/` (gitignored), then add:

```
ENABLE_BANKING_APP_ID=your-application-id
ENABLE_BANKING_PRIVATE_KEY_FILE=/app/secrets/your-key.pem
ENABLE_BANKING_OAUTH_REDIRECT_URI=https://your-host/oauth/callback
```

The redirect URI must match exactly one of the Allowed Redirect URLs in your EB application. Production EB requires HTTPS -- for local development, expose your frontend via a tunnel (ngrok, cloudflared) or use the EB sandbox.

> **Free tier -- restricted mode.** Enable Banking's free plan requires you to pre-link the accounts you want to import inside the EB portal *before* connecting from Quad4 Finance. If you skip that step, the connection returns no accounts and Quad4 Finance will surface a banner with a link to the portal.

### SimpleFIN -- US and international banks

[SimpleFIN](https://www.simplefin.org/) is a read-only open protocol. No API key needed -- each connection brings its own credentials via a single-use Setup Token from the [SimpleFIN Bridge](https://bridge.simplefin.org/). Just enable the feature:

```
SIMPLEFIN_ENABLED=true
SIMPLEFIN_API_URL=https://beta-bridge.simplefin.org   # sandbox; use bridge.simplefin.org for real banks
```

Then in Quad4 Finance: **Accounts -> Connect Bank -> SimpleFIN**, and paste the token. The [developer page](https://beta-bridge.simplefin.org/info/developers) gives out free demo tokens if you want to try it without a real bank.

## OIDC Login (Optional)

Quad4 Finance can delegate login to any standard OIDC provider, including Authentik and Pocket ID. Create a confidential/web application in your provider and register this redirect URI:

```
https://your-quad4-host/api/auth/oidc/callback
```

Then add the provider settings to `.env` and restart:

```
OIDC_ENABLED=true
OIDC_PROVIDER_NAME=Pocket ID
OIDC_DISCOVERY_URL=https://id.example.com/.well-known/openid-configuration
OIDC_CLIENT_ID=quad4
OIDC_CLIENT_SECRET=your-client-secret
# Optional; defaults to ${FRONTEND_URL}/api/auth/oidc/callback
OIDC_REDIRECT_URI=https://your-quad4-host/api/auth/oidc/callback
```

To require SSO-only access after OIDC is configured, set `LOCAL_AUTH_ENABLED=false`. Quad4 Finance will start in this mode only when `OIDC_ENABLED=true`, `OIDC_CLIENT_ID`, and `OIDC_DISCOVERY_URL` are all configured; otherwise startup fails with a validation error instead of leaving the instance with no usable login method. The login page shows an explicit configuration error if the server reports that neither local auth nor OIDC is available. If only the optional OIDC-config request fails, the client keeps local controls available with a warning; the backend remains authoritative and still rejects them in OIDC-only mode.

With local auth disabled, Quad4 Finance rejects password and passkey login, public registration, first-admin password setup, admin or workspace-invite creation of password-backed users, forgot/reset-password requests, password updates, new passkey registration or verification, and new TOTP setup or enablement. Local credential controls are hidden from login, account, setup, registration, and admin user-management screens. Existing users, password hashes, active sessions, passkeys, and TOTP configuration are not deleted; existing passkeys and TOTP can still be removed as cleanup paths. OIDC user provisioning and existing-account linking remain controlled separately by `OIDC_AUTO_REGISTER` and `OIDC_EXISTING_USER_LINK_MODE`.

On a fresh OIDC-only instance, the first account must be provisioned through OIDC. Keep `OIDC_AUTO_REGISTER=true`, enable `OIDC_SYNC_ROLES=true`, and include one of the values from `OIDC_ADMIN_ROLES` in that identity's configured roles claim so the first login becomes a Quad4 Finance administrator. Do not disable OIDC auto-registration before at least one matching account exists.

New OIDC users are auto-provisioned by default (`OIDC_AUTO_REGISTER=true`) using verified email addresses. Set `OIDC_AUTO_REGISTER=false` to allow only existing Quad4 Finance users whose email matches the provider claim.

### Linking existing accounts

An account that already exists in Quad4 Finance (created with a password) is never linked to an OIDC identity automatically, so the first SSO login of an existing user is rejected by default. `OIDC_EXISTING_USER_LINK_MODE` controls that:

```
OIDC_EXISTING_USER_LINK_MODE=disabled
```

| Value | Behavior |
|-------|----------|
| `disabled` (default) | Never link. Existing accounts must keep using password login. |
| `verified_email` | Link the existing account when the provider sends `email_verified=true` for the same email. |
| `email` | Link on a matching email alone, even without `email_verified`. |

Use `verified_email` to move existing users to SSO without recreating their accounts and data. Only pick `email` if you trust your provider to own every address it asserts, since anyone able to set an email there could claim the matching Quad4 Finance account. An OIDC identity already linked to another account is always rejected, in every mode.

### Optional OIDC role sync

Quad4 Finance can also synchronize provider roles/groups into its built-in permissions when `OIDC_SYNC_ROLES=true`. The default claim is `groups`, which works well with Authentik group mappings and Pocket ID role/group assignments.

```
OIDC_SYNC_ROLES=true
OIDC_ROLES_CLAIM=groups
OIDC_ADMIN_ROLES=quad4-admins
OIDC_WORKSPACE_ROLE_MAP={"quad4-owners":"owner","quad4-editors":"editor","quad4-viewers":"viewer"}
```

`OIDC_ADMIN_ROLES` grants or revokes Quad4 Finance admin (`is_superuser`) on each OIDC login. `OIDC_WORKSPACE_ROLE_MAP` maps provider roles/groups to the user's Personal workspace role (`owner`, `editor`, or `viewer`); if multiple mapped roles are present, Quad4 Finance applies the highest permission. Leave `OIDC_SYNC_ROLES=false` to keep all Quad4 Finance roles managed locally.

## Passkeys (Optional)

Sign in with Touch ID, Face ID, Windows Hello, or a security key. Passkeys are on by default and need no configuration: they follow whatever address you open Quad4 Finance on.

Two rules come from the WebAuthn standard itself, and no setting can work around them:

- **An IP address is never valid.** `http://192.168.1.10:3000` cannot register passkeys.
- **Plain HTTP is never valid, except on `localhost`.**

So use passkeys on `http://localhost:3000`, or put Quad4 Finance on a domain behind an HTTPS reverse proxy. When serving from a domain, point `FRONTEND_URL` at it (this also covers CORS and OAuth callbacks):

```
FRONTEND_URL=https://quad4.example.com
```

To pin passkeys to one domain, set `WEBAUTHN_RP_ID` (use the parent domain if you reach Quad4 Finance on several subdomains). Otherwise Quad4 Finance follows the browser, and requests from an unusable address get an explanation in the UI instead of a silent failure.

## Backups and S3 (Optional)

On-demand workspace exports are always available from Settings. For unattended backups, the daily scheduler writes an AES-256 encrypted archive per workspace to the configured storage provider and prunes everything older than `BACKUP_RETENTION_COUNT` archives.

Local disk (default) stores under `BACKUP_LOCAL_PATH`. For off-site backups on S3-compatible storage:

```
STORAGE_PROVIDER=s3
STORAGE_S3_BUCKET=my-backups
STORAGE_S3_REGION=auto
STORAGE_S3_ACCESS_KEY=...
STORAGE_S3_SECRET_KEY=...
STORAGE_S3_ENDPOINT_URL=https://<account>.r2.cloudflarestorage.com  # MinIO, R2, B2, ...
BACKUP_ENCRYPTION_KEY=...   # keep stable; needed to decrypt archives
```

## Exchange Rates (Optional)

For automatic currency conversion, add a free [Open Exchange Rates](https://openexchangerates.org/) key to `.env`:

```
OPENEXCHANGERATES_APP_ID=your-app-id
```

Rates are fetched on-demand when foreign-currency transactions are created. Without a key, cross-currency amounts default to a 1:1 fallback rate with a visual warning.

## Timezone

Balances, budgets, due dates and recurring transactions turn over at midnight in the application timezone. Set it once in Admin Settings -> Date and time; a workspace that keeps its books somewhere else can pick its own timezone in Workspace settings. Without a saved value the application follows `TZ` from the environment, then the host timezone, then UTC.

## AI Agents (Optional)

Self-hosted AI assistants over your Quad4 Finance data -- multi-provider (OpenAI, Anthropic, Ollama, OpenAI-compatible), tool-use via MCP, per-agent RAG knowledge base, ⌘J global chat panel.

Add to `.env`:

```
AGENTS_ENABLED=true
COMPOSE_PROFILES=agents
```

Then `docker compose -f docker-compose.prod.yml up -d`. Settings -> AI Agents to add a provider connection. Off by default; zero cost when off.

### Without Docker

`COMPOSE_PROFILES=agents` only tells Docker Compose to start the extra `mcp-server` container, so on a bare-metal or LXC install set `AGENTS_ENABLED=true` alone. The built-in MCP server is a plain uvicorn app in the same virtualenv; run it next to the API and point the backend at it:

```bash
uvicorn mcp_server.main:app --host 127.0.0.1 --port 8765
```

```
AGENTS_ENABLED=true
AGENTS_BUILTIN_MCP_URL=http://127.0.0.1:8765/mcp
```

Without that server the agents still chat, but they have no tools and cannot read your data. The backend log says which MCP server it failed to reach.

## Tech Stack

| Layer | Stack |
|-------|-------|
| Backend | FastAPI, SQLAlchemy, Alembic, Celery |
| Frontend | React, TypeScript, Vite, Tailwind CSS |
| Database | PostgreSQL |
| Queue | Redis + Celery |
| Containers | Chainguard base images, rootless, multi-stage |
| Sandbox | landlockpy + seccompy |

## Development

```bash
# Run backend tests (from backend/, needs Python 3.11+; same as CI)
cd backend
pip install -e ".[dev]"   # first time only -- installs pytest and dev deps
pytest

# Rebuild after dependency changes
docker compose up --build
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

This project is licensed under the [GNU Affero General Public License v3.0](LICENSE), inherited from upstream [Securo](https://github.com/securo-finance/securo). Any modifications -- including when used as a network service -- must also be released under the AGPL-3.0.
