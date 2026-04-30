# syntax=docker/dockerfile:1.7
FROM ghcr.io/astral-sh/uv:0.11.6-python3.13-trixie@sha256:b3c543b6c4f23a5f2df22866bd7857e5d304b67a564f4feab6ac22044dde719b AS uv_source
FROM tianon/gosu:1.19-trixie@sha256:3b176695959c71e123eb390d427efc665eeb561b1540e82679c15e992006b8b9 AS gosu_source
FROM debian:13.4

# Disable Python stdout buffering to ensure logs are printed immediately
ENV PYTHONUNBUFFERED=1

# Store Playwright browsers outside the volume mount so the build-time
# install survives the /opt/data volume overlay at runtime.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/hermes/.playwright

# Install system dependencies in one layer, clear APT cache
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential nodejs npm python3 ripgrep ffmpeg gcc python3-dev libffi-dev procps git && \
    rm -rf /var/lib/apt/lists/*

# Non-root user for runtime; UID can be overridden via HERMES_UID at runtime
RUN useradd -u 10000 -m -d /opt/data hermes

COPY --chmod=0755 --from=gosu_source /gosu /usr/local/bin/
COPY --chmod=0755 --from=uv_source /usr/local/bin/uv /usr/local/bin/uvx /usr/local/bin/

WORKDIR /opt/hermes

COPY --chown=hermes:hermes package*.json ./
RUN --mount=type=cache,target=/root/.npm \
    echo "Installing root npm dependencies" && \
    if [ -f package-lock.json ]; then \
        npm ci --prefer-offline --no-audit; \
    else \
        npm install --prefer-offline --no-audit; \
    fi

RUN --mount=type=cache,target=/root/.npm \
    echo "Installing Playwright Chromium shell" && \
    npx playwright install --with-deps chromium --only-shell

COPY --chown=hermes:hermes scripts/whatsapp-bridge/package*.json ./scripts/whatsapp-bridge/
RUN --mount=type=cache,target=/root/.npm \
    echo "Installing whatsapp-bridge npm dependencies" && \
    cd /opt/hermes/scripts/whatsapp-bridge && \
    if [ -f package-lock.json ]; then \
        npm ci --prefer-offline --no-audit; \
    else \
        npm install --prefer-offline --no-audit; \
    fi

COPY --chown=hermes:hermes pyproject.toml uv.lock ./
USER hermes

RUN --mount=type=cache,target=/opt/data/.cache/uv,uid=10000,gid=10000 \
    echo "Creating Python virtualenv and installing Python dependencies from pyproject.toml" && \
    uv venv && \
    uv pip install -r pyproject.toml --extra all

COPY --chown=hermes:hermes . /opt/hermes

RUN --mount=type=cache,target=/opt/data/.cache/uv,uid=10000,gid=10000 \
    echo "Installing Hermes package in editable mode" && \
    uv pip install --no-deps -e ".[all]"

USER root
RUN chmod +x /opt/hermes/docker/entrypoint.sh

ENV HERMES_HOME=/opt/data
VOLUME [ "/opt/data" ]
ENTRYPOINT [ "/opt/hermes/docker/entrypoint.sh" ]
