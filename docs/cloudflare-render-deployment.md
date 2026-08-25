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
disks are not available for free web services. For a temporary demo, remove
the `disk` block and change `plan` to `free`, but all SQLite data will be
ephemeral.

The included Docker image uses the rule-based Dabba engine. Hosting a local
GGUF model requires enough RAM/CPU (or GPU), storing the model separately, and
setting `DABBA_MODEL_PATH` to its mounted path. Provider-backed models can be
configured from the app after signup.

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
