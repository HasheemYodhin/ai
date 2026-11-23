# syntax=docker/dockerfile:1.7
FROM node:22-bookworm-slim AS frontend-builder
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.10-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DABBA_DATA_DIR=/data \
    DABBA_FRONTEND_DIR=/app/frontend \
    DABBA_MODEL_PATH=rule_based
WORKDIR /app

COPY requirements-server.txt ./
RUN pip install --no-cache-dir -r requirements-server.txt \
    && pip uninstall --yes setuptools wheel

# Litestream: optional SQLite backup/restore to Cloudflare R2, enabled at
# runtime by LITESTREAM_BUCKET (see deploy/docker-entrypoint.sh). The download
# is pinned to a release and verified against its published SHA-256.
ARG LITESTREAM_VERSION=0.5.18
ADD --checksum=sha256:d3687b9fd0f2e9426bbd3da828429ff3f1dfc5c9b74d54fdf028e4ee510e7dea \
    https://github.com/benbjohnson/litestream/releases/download/v${LITESTREAM_VERSION}/litestream-${LITESTREAM_VERSION}-linux-x86_64.tar.gz \
    /tmp/litestream.tar.gz
RUN tar -xzf /tmp/litestream.tar.gz -C /usr/local/bin litestream \
    && rm /tmp/litestream.tar.gz
COPY deploy/litestream.yml /etc/litestream.yml
COPY deploy/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

COPY dabba/ ./dabba/
COPY bin/dabba /usr/local/bin/dabba
COPY --from=frontend-builder /build/frontend/dist/ ./frontend/

RUN groupadd --system dabba \
    && useradd --system --gid dabba --home-dir /app dabba \
    && mkdir -p /data/tmp \
    && chown -R dabba:dabba /app /data /usr/local/bin/dabba
ENV TMPDIR=/data/tmp
USER dabba

EXPOSE 8080
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python3", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/ready', timeout=4)"]

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python3", "-m", "dabba.api.server", "--host", "0.0.0.0", "--port", "8080"]

# Optional development target for coding/worktree tools and npx-based stdio
# MCP servers. These tools are deliberately excluded from the production
# image because Debian's npm package pulls hundreds of build-only packages.
FROM runtime AS developer-runtime
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl git nodejs npm \
    && rm -rf /var/lib/apt/lists/*
USER dabba

FROM runtime AS production
