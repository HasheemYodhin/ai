#!/bin/sh
# Container entrypoint. With LITESTREAM_BUCKET set, restores the SQLite
# databases from Cloudflare R2, then runs the server under Litestream so every
# write is copied back to R2. Without it, runs the server directly.
set -eu

if [ -z "${LITESTREAM_BUCKET:-}" ]; then
  exec "$@"
fi

for var in R2_ACCOUNT_ID LITESTREAM_ACCESS_KEY_ID LITESTREAM_SECRET_ACCESS_KEY DABBA_MASTER_KEY; do
  eval "value=\${$var:-}"
  if [ -z "$value" ]; then
    # DABBA_MASTER_KEY must be fixed: otherwise a new key is generated on each
    # restart and secrets in the restored database can no longer be decrypted.
    echo "entrypoint: $var must be set when LITESTREAM_BUCKET is set" >&2
    exit 1
  fi
done

CONFIG=/etc/litestream.yml
for db in platform.db conversations.db; do
  # Restore only when the local file is missing and a backup exists, so the
  # first deploy (empty bucket) and local restarts both succeed.
  litestream restore -config "$CONFIG" -if-db-not-exists -if-replica-exists \
    "$DABBA_DATA_DIR/$db"
done

# Make sure both files exist in WAL mode (Litestream replicates through the
# WAL) before replication starts; the app creates its tables on first use.
python3 - <<'PY'
import os, sqlite3
for name in ("platform.db", "conversations.db"):
    conn = sqlite3.connect(os.path.join(os.environ["DABBA_DATA_DIR"], name))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.close()
PY

# Litestream starts the server as a child process and does a final sync when
# the container is stopped.
exec litestream replicate -config "$CONFIG" -exec "$*"
