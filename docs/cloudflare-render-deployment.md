# Deploy the frontend on Cloudflare Pages and the backend on Render

## What this project uses

- Frontend: React 18, TypeScript, and Vite (`frontend/`)
- Backend: Python and FastAPI (`dabba/api/server.py`)
- Database: two local SQLite files (`platform.db` and `conversations.db`)

This version does not use PostgreSQL. On Render, SQLite must be stored on a
persistent disk. Without a disk, accounts, sessions, conversations, artifacts,
and settings can disappear whenever the service restarts or redeploys.

## 1. Push the repository to GitHub or GitLab

Both Cloudflare Pages and Render can deploy automatically from the same
repository and branch.

## 2. Deploy the backend on Render

1. In Render, choose **New > Blueprint** and connect this repository.
2. Render detects the root `render.yaml` file and creates `dabba-api`.
3. When prompted for `DABBA_CORS_ORIGINS`, enter the future Cloudflare Pages
   origin, for example `https://your-project.pages.dev`. Do not include a
   trailing slash. Multiple allowed origins can be comma-separated.
4. Deploy and wait for `/ready` to report HTTP 200.
5. Copy the service URL, for example `https://dabba-api.onrender.com`.

The Blueprint uses Render's paid Starter service because Render persistent
disks are not available for free web services. To run on the free plan and
still keep data, remove the `disk` block, change `plan` to `free`, and follow
"Free persistence with Litestream and Cloudflare R2" below.

The included Docker image uses the rule-based Dabba engine. Hosting a local
GGUF model requires enough RAM/CPU (or GPU), storing the model separately, and
setting `DABBA_MODEL_PATH` to its mounted path. Provider-backed models can be
configured from the app after signup.

## Free persistence with Litestream and Cloudflare R2

Render's free web service wipes the disk on every restart, redeploy, and
spin-down. The Docker image includes [Litestream](https://litestream.io),
which copies `platform.db` and `conversations.db` to Cloudflare R2 about once
a second and restores them when the container starts. Accounts, sessions,
chats, and projects then survive restarts at no cost.

1. In the Cloudflare dashboard, open **R2** and create a bucket, for example
   `dabba-backup`. Note your **Account ID** shown on the R2 overview page.
2. In **R2 > Manage API tokens**, create a token with **Object Read & Write**
   permission, limited to that bucket. Copy the access key ID and secret.
3. Generate a master key locally (keep it secret, never commit it):

   ```bash
   python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

4. In Render, open the service's **Environment** tab and add:

   | Key | Value |
   | --- | --- |
   | `LITESTREAM_BUCKET` | The bucket name |
   | `R2_ACCOUNT_ID` | Your Cloudflare account ID |
   | `LITESTREAM_ACCESS_KEY_ID` | The R2 token's access key ID |
   | `LITESTREAM_SECRET_ACCESS_KEY` | The R2 token's secret |
   | `DABBA_MASTER_KEY` | The key from step 3 |

5. Save. Render redeploys; sign up once, and your account remains after
   restarts.

Notes:

- When `LITESTREAM_BUCKET` is unset, the container runs without Litestream.
- The container refuses to start if `LITESTREAM_BUCKET` is set without the
  other four values. `DABBA_MASTER_KEY` must stay the same; changing it makes
  previously encrypted secrets unreadable.
- Writes made in the last second before a crash can be lost.
- Only the two databases are backed up. Settings saved to `cli_config.yaml`
  (for example keys saved in the app) are not; set provider keys as Render
  environment variables instead (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
  `NVIDIA_API_KEY`, ...).
- Check R2's current free-tier limits in Cloudflare's pricing page.

## 3. Deploy the frontend on Cloudflare Pages

Create a Pages project from the same repository and use:

| Setting | Value |
| --- | --- |
| Framework preset | React (Vite) |
| Root directory | `frontend` |
| Build command | `npm run build` |
| Build output directory | `dist` |
| Environment variable | `VITE_API_URL=https://dabba-api.onrender.com` |

Use the actual Render URL and do not add a trailing slash. Add
`VITE_API_URL` to both Production and Preview if preview deployments should
use the backend. Vite embeds this value during the build, so trigger a new
Cloudflare deployment after changing it.

The committed `frontend/public/_redirects` file makes client-side routes fall
back to `index.html` on Cloudflare Pages.

## 4. Finish the CORS setting

After Cloudflare assigns the final Pages URL, update `DABBA_CORS_ORIGINS` in
Render to that exact origin and redeploy. If a custom frontend domain is added,
include both origins, for example:

```text
https://app.example.com,https://your-project.pages.dev
```

## 5. Verify

1. Open `https://dabba-api.onrender.com/ready`; it should show ready storage.
2. Open the Cloudflare Pages URL and create an account.
3. Send a message, reload the page, and confirm the account and conversation
   still exist.
4. Check the browser Network panel: API requests should go to the Render URL,
   not the Cloudflare domain.

Do not put OpenAI, Anthropic, or other private provider keys in Cloudflare's
`VITE_*` variables; those values are public in the browser bundle. Enter
provider keys through the authenticated app/backend or as secret Render
environment variables supported by the backend.

### Full backup and restore drill

Litestream restores the two SQLite databases. Artifact binaries, imported
documents, and other files under `DABBA_DATA_DIR` also need a backup. Keep the
master key in your secret manager and verify it is available to the restore
environment.

For a consistent full snapshot, stop writes first. On a self-hosted instance,
stop Dabba and archive the entire data directory to a protected location
outside that directory:

```sh
bash deploy/backup-data.sh /path/to/dabba-data /protected/dabba-backup.tar.gz
```

On Render, use a consistent snapshot of the persistent
disk or an equivalent file backup taken while writes are stopped. Record the
release version and when the snapshot was taken.

Restore into an empty staging disk using the same application version,
absolute data directory path, and master key. Stored file records can contain
absolute paths. Before enabling jobs or accepting traffic, check sign-in, recent
conversations, downloads of an artifact and an original document, and
decryption of a saved provider key. Record the oldest missing change and the
time it took to restore. Keep the existing production disk available during
a restore or rollback.


### Optional PostgreSQL storage (Neon)

SQLite is the default. Set `DATABASE_URL` to a PostgreSQL connection string to
use PostgreSQL for platform records and conversations. For Render on Neon, use
the pooled URL for the app and keep the TLS options supplied by Neon. Store the
URL in Render's Environment settings as a secret. The server image includes
the driver. For a local migration, install it with
`python3 -m pip install 'psycopg[binary]>=3.2,<4'`.

The API reuses up to four PostgreSQL connections per worker. Keep one worker
on a 512 MB service and choose a Neon region close to the Render service.

For an existing deployment, migrate before setting `DATABASE_URL` on the
live service:

1. Take consistent copies of `platform.db` and `conversations.db` while
   writes are stopped, or restore both from the same backup. Retain the
   originals and the existing `DABBA_MASTER_KEY`.
2. From a trusted machine, set `DATABASE_URL` privately in your environment
   to the direct URL for an empty Neon database. Run
   `python3 -m dabba.platform.migrate_sqlite /path/to/snapshot-directory`
   from the repo. The importer reads the snapshots without editing them,
   copies both stores in one transaction, rebuilds the message index, and
   refuses a destination containing Dabba data.
3. Verify sign-in, chats, search, usage, and saved provider keys against a
   test deployment before switching production. For the final migration,
   stop writes and use fresh snapshots and an empty destination. Keep the
   SQLite backup until you have verified the cutover. If you revert to that
   backup, writes made after the cutover require separate reconciliation.

PostgreSQL mode bypasses Litestream. Back up PostgreSQL separately, and keep
the files under `DABBA_DATA_DIR` on persistent storage or back them up
separately. Uploaded documents and artifact binaries still live there.

### 512 MB Render services

Set `DABBA_LOW_MEMORY=true` on an existing Render service. The Blueprint includes
it for services created or synchronized from `render.yaml`. Keep one API worker
and use hosted models or the built-in rule-based model. Browser Python and
browser speech fallbacks avoid loading local interpreter and speech models in the
API process.

This profile admits two interactive generation requests at a time, with one
active generation per signed-in account. It also admits one document or audio
request at a time and runs background jobs one at a time. An occupied slot returns
HTTP 429 with a retry hint. The profile accepts multipart uploads up to 26 MiB
including request overhead and transcription request bodies up to 9 MiB.
The profile reduces concurrency and payload pressure. Check memory in the Render
dashboard under your actual workbook, PDF, and connector workloads.
