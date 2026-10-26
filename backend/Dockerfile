# syntax=docker/dockerfile:1
# Quad4 Finance backend - multi-stage Chainguard build, rootless runtime.
#
# Build stage uses the dev variant (shell, pip, uv) to resolve the locked
# dependency set into a virtualenv. The runtime stage is the minimal
# cgr.dev/chainguard/python image: no shell, no package manager, running as
# the nonroot user (uid 65532). Landlock and seccomp are applied by the app
# itself at startup (app/core/sandbox.py) and need no extra privileges.

FROM cgr.dev/chainguard/python:latest-dev AS build

WORKDIR /app

# Wolfi is musl-based: packages without musllinux wheels (lxml and friends)
# build from source, so the toolchain and headers live only in this stage.
USER root
RUN apk update && apk add --no-cache build-base libxml2-dev libxslt-dev
USER nonroot

# Dependencies come from uv.lock (the source of truth - see scripts/lock.sh).
# The export never touches the lock (--frozen); pip then installs with hash
# checking, so the image only ever contains the exact audited versions.
# This layer is cached until pyproject.toml or uv.lock change.
COPY pyproject.toml uv.lock ./
RUN python -m venv /home/nonroot/venv \
    && ln -s "$(/home/nonroot/venv/bin/python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')" /home/nonroot/pylibs
ENV PATH="/home/nonroot/venv/bin:$PATH"
RUN uv export --frozen --no-emit-project -o /tmp/requirements.txt \
    && pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# /app is root-owned and setuptools writes egg-info into it during the
# in-tree wheel build, so this step runs as root.
USER root
COPY . .
# The project itself: deps are already satisfied above, so --no-deps keeps
# this layer from re-resolving anything outside the lock.
RUN pip install --no-cache-dir --no-deps . \
    && mkdir -p /app/data-skel/attachments /app/data-skel/backups \
       /app/data-skel/agent_knowledge /app/data-skel/embedding_models

FROM cgr.dev/chainguard/python:latest

WORKDIR /app

COPY --from=build /home/nonroot/venv /home/nonroot/venv
COPY --from=build /home/nonroot/pylibs /home/nonroot/pylibs
# Runtime needs the package source (migrations, MCP server, CLI entry), not
# the whole build context - and never the venv twice.
COPY --from=build /app/app /app/app
COPY --from=build /app/alembic /app/alembic
COPY --from=build /app/alembic.ini /app/pyproject.toml ./
COPY --from=build /app/mcp_server /app/mcp_server
# Empty writable roots: named volumes initialized from these paths inherit
# the nonroot ownership, so the runtime user can write without any chown.
COPY --from=build --chown=65532:65532 /app/data-skel /app/data

# The Chainguard entrypoint is the absolute /usr/bin/python, so PATH alone
# never reaches the venv: PYTHONPATH puts the locked site-packages on the
# interpreter, and PATH still resolves console scripts (celery, alembic).
ENV PATH="/home/nonroot/venv/bin:$PATH" \
    PYTHONPATH=/home/nonroot/pylibs \
    PYTHONUNBUFFERED=1 \
    STORAGE_LOCAL_PATH=/app/data/attachments \
    BACKUP_LOCAL_PATH=/app/data/backups \
    AGENTS_KNOWLEDGE_STORAGE_PATH=/app/data/agent_knowledge

EXPOSE 8000

# The image entrypoint is /usr/bin/python; compose services override
# entrypoint+command for celery, beat and the migration job.
CMD ["-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
