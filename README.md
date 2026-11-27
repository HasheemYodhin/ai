# Dabba

Dabba is a self-hosted AI workspace for chat, documents, image generation, and tool-assisted tasks. Run the web app and API locally, or deploy them together on Docker. Hosted model providers handle inference remotely, so a small server can run Dabba without loading a large model.

- **Chat.** Stream replies, upload files and images, use voice where supported, branch conversations, and save or share messages.
- **Documents.** Generate PDF, Word, Excel, PowerPoint, and Markdown files with templates, progress updates, and a short summary in chat.
- **Workspace.** Organize chats into projects, reuse prompts, and manage account preferences, usage, and saved memory.
- **Tools.** Connect MCP servers, run workflows in Cowork, and manage scheduled skills and approval requests.

## Run locally

Use Python 3.10 or newer and Node.js 22 or newer. From the repository root, start the API in one terminal.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-server.txt
DABBA_MODEL_PATH=rule_based DABBA_DATA_DIR="$PWD/.dabba-data" \
  python -m dabba.api.server --host 127.0.0.1 --port 8080
```

Check API and storage readiness.

```bash
curl --fail http://127.0.0.1:8080/ready
```

Start the web app in a second terminal.

```bash
cd frontend
npm ci
npm run dev
```

Open <http://localhost:5173/signup> and create the first account. It becomes the workspace owner and can manage provider keys and connectors. Vite proxies API requests to port 8080. Set `VITE_API_URL` before starting Vite if your backend uses another address.

## Connect a model provider

Add a provider key under **Settings → API Keys** or set the matching environment variable on the API server. Saved model-specific keys take precedence over the provider key, and saved provider keys take precedence over environment variables. Refresh the model picker after adding a key.

| Provider | Environment variable | Typical use |
| --- | --- | --- |
| NVIDIA | `NVIDIA_API_KEY` | Nemotron chat and FLUX.1-dev image generation |
| Google | `GEMINI_API_KEY` | Gemini chat, reasoning, and vision on supported models |
| VyceAI | `VYCEAI_API_KEY` | GLM 5.3 Flash, Nemotron 3.5 Super VL, GPT-OSS 120B, and Wave |
| OpenAI | `OPENAI_API_KEY` | GPT chat and optional hosted transcription |
| Anthropic | `ANTHROPIC_API_KEY` | Claude chat and tool use |
| Hugging Face | `HF_TOKEN` | Supported hosted models |

To generate an image, select **FLUX.1-dev (Image)** or choose **Create an image** from the composer. FLUX uses NVIDIA credentials. For VyceAI chat access, use **Test key** in Settings and verify your VyceAI account if the provider rejects the request. Promotional access and quotas depend on the provider account.

Use [.env.example](.env.example) as a configuration reference. Keep real keys and database URLs in your host’s secret settings.

### Usage limits

These server variables set rolling chat token limits per account. Set a window to `0` for unlimited usage in that window. Provider spend and rate limits are configured in the provider’s dashboard.

| Window | Variable | Default |
| --- | --- | ---: |
| 5 hours | `DABBA_CHAT_TOKEN_LIMIT_5H` | 250,000 |
| Daily | `DABBA_CHAT_TOKEN_LIMIT_DAILY` | 1,000,000 |
| Weekly | `DABBA_CHAT_TOKEN_LIMIT_WEEKLY` | 4,000,000 |

## Deploy Dabba

### Docker

The production image builds the web app and serves it from the API. Mount `/data` for persistent files and local databases.

```bash
docker build -t dabba .
docker run --name dabba --rm -p 127.0.0.1:8080:8080 \
  -e DABBA_LOW_MEMORY=true \
  -v dabba-data:/data dabba
```

Open <http://127.0.0.1:8080>. Use `/health` to check the API process and `/ready` to check whether it can access platform storage.

### Render with 512 MB and optional Neon Postgres

1. Use the [Render Blueprint](render.yaml) or a Docker web service built from the [Dockerfile](Dockerfile). The Blueprint listens on port `10000` and checks `/ready`.
2. Keep one API worker and set `DABBA_LOW_MEMORY=true` and `DABBA_MODEL_PATH=rule_based`. Add the keys for the hosted models you use.
3. For Neon, add its pooled PostgreSQL connection string as the secret `DATABASE_URL`, keeping the TLS settings supplied with the URL. SQLite is used when this variable is unset.
4. Keep `/data` on persistent storage for uploaded files and artifact binaries. Keep `DABBA_MASTER_KEY` stable across restarts so saved provider keys can still be decrypted.

For an existing SQLite deployment, back up and migrate the data before switching the live service. Follow the [storage migration and deployment guide](docs/cloudflare-render-deployment.md#optional-postgresql-storage-neon).

### Kubernetes

The [Helm chart](helm/dabba) uses port `8080`, probes `/health` and `/ready`, and mounts a 10 GiB persistent volume by default. Use an image repository and tag you have published.

```bash
helm upgrade --install dabba ./helm/dabba \
  --set image.repository=YOUR_IMAGE_REPOSITORY \
  --set image.tag=YOUR_IMAGE_TAG
```

Configure private registry credentials through `image.pullSecrets` and external access through `ingress` in [the chart values](helm/dabba/values.yaml).

## Tools, code, and voice

- **MCP connectors.** The workspace owner can manage them under **Connectors** or **Settings → Tools (MCP)**. Dabba starts MCP servers as local subprocesses. Presets using `npx` need a runtime with Node.js, such as the Dockerfile’s `developer-runtime` target. The Settings connection test checks whether the MCP process responds. Account access can be checked separately with a read-only tool call.
- **Code.** Python snippets can run in the browser. Hosted Java opens in JavaFiddle with the snippet preloaded. The local Java runner requires a JDK and the owner’s local code-execution setting.
- **Voice.** Check `/v1/audio/status` for server capabilities. Supported browsers can provide speech fallbacks. For hosted transcription, configure `DABBA_HOSTED_TRANSCRIPTION=openai` and an OpenAI key.

## Development and other clients

The web client lives in [frontend/](frontend/), the API in [dabba/api/](dabba/api/), and provider integrations in [dabba/providers/](dabba/providers/). Run frontend checks from `frontend/`.

```bash
npm run lint
npx tsc --noEmit
npm test
npx playwright install chromium
npm run test:e2e
```

See the [backend CI workflow](.github/workflows/platform-ci.yml) for the slim server suite and the separate model tests, which require the larger [training dependencies](requirements.txt).

- **Terminal.** Run [`bin/dabba`](bin/dabba) from the repository root.
- **VS Code.** See the [extension architecture guide](VSCODE_EXTENSION_ARCHITECTURE.md).
- **Chrome.** Add PNG icons named `icon16.png`, `icon48.png`, and `icon128.png` at the matching sizes under `chrome-extension/icons/`. Load [chrome-extension/](chrome-extension/) as an unpacked extension.
- **API clients.** Start with the [API guide](dabba/docs/api.md).

## Further reading

- [Day-to-day usage](HOW_TO_USE_DABBA.md)
- [Architecture](DABBA_ARCHITECTURE.md)
- [Installation, configuration, and model training](dabba/docs/index.md)
