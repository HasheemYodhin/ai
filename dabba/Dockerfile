# Compatibility Dockerfile for commands that explicitly use dabba/Dockerfile.
# Build with the repository root as context:
#   docker build -f dabba/Dockerfile .
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
CMD ["python3", "-m", "dabba.api.server", "--host", "0.0.0.0", "--port", "8080"]

FROM runtime AS developer-runtime
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl git nodejs npm \
    && rm -rf /var/lib/apt/lists/*
USER dabba

FROM runtime AS production
