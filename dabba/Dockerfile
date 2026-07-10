# Stage 1: Build dependencies
FROM python:3.10-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    make \
    && rm -rf /var/lib/apt/lists/*

# Copy only requirements first for layer caching
COPY pyproject.toml setup.cfg setup.py README.md ./
COPY dabba/ dabba/

# Build the package
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir build && \
    python -m build

# Stage 2: Runtime
FROM python:3.10-slim AS runtime

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy the built package
COPY --from=builder /build/dist/ ./dist/

# Install the package
RUN pip install --no-cache-dir ./dist/*.whl

# Create non-root user
RUN groupadd -r dabba && useradd -r -g dabba -d /app -s /bin/false dabba && \
    chown -R dabba:dabba /app

USER dabba

# Expose the API port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default command
ENTRYPOINT ["dabba"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
