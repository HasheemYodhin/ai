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
