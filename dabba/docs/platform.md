# Dabba Platform Services

The platform layer gives the web app, CLI, VS Code extension, and future
workers one durable backend contract. It is additive to the OpenAI-compatible
chat API.

## Services

- `ProviderGateway`: persistent health, bounded retries, circuit breakers,
  configured fallback chains, and normalized errors.
- `TaskOrchestrator`: durable task states, progress, event replay, cancellation,
  resume, idempotency, and worker handlers.
- `ApprovalService`: shared risk classification and auditable decisions.
- `IdentityService`: PBKDF2 password hashes and revocable bearer sessions.
- `WorkspaceService`: path containment, nested instructions, checkpoints,
  unified diffs, and rollback.
- `ArtifactService`: immutable binary artifacts with checksums and versions.
- `ConnectorRuntime`: authenticated tool discovery, scopes, OAuth PKCE state,
  token expiry, and encrypted token storage.
- `MemoryService`: explicit conversation, project, workspace, and preference
  scopes.
- `EvaluationService`: persisted regression suites, scores, and metrics.
- `TelemetryService`: request IDs, structured audit events, OpenTelemetry
  traces and HTTP metrics.
- `DocumentWorkspace`: immutable originals and same-format Word, Excel,
  PowerPoint, and PDF revisions.
- `CodeIndexService`: symbols and dependencies for Python, JavaScript,
  TypeScript, Java, Go, and Rust.
- `CoworkService`: user-scoped work queues with status, priority, assignment,
  due dates, tags, conversation links, autonomous model/agent execution,
  cancellation, persisted outputs, and an activity audit trail.
- `ScheduledSkillService`: interval, daily, and weekly skill automation with
  background execution, durable task tracking, enable/disable controls, and
  run history.

Discover the current contract:

```text
GET /v1/platform/capabilities
```

The complete interactive schema is available at `/docs`.

Cowork is exposed at `/v1/platform/cowork/items`. Scheduled Skills are exposed
at `/v1/platform/scheduled-skills`; the API process checks due schedules every
30 seconds and executes them through the configured model provider.

Cowork runs support `safe` mode (model-only) and explicit `agent` mode. Agent
mode can use built-in tools and connected MCP apps and can be grounded in an
optional workspace path. Run records link back to durable tasks and retain the
final response, tool count, changed files, errors, and timestamps.

The Cowork folder picker lists server-side directories under the current user
home and server working directory by default. Production deployments can limit
the picker and agent workspaces to explicit roots with the platform-specific
path separator (`:` on Linux/macOS, `;` on Windows):

```bash
export DABBA_WORKSPACE_ROOTS=/srv/projects:/data/shared
```

## Task States

```text
queued -> planning -> running -> completed
                         |       -> failed
                         |       -> cancelled
                         -> waiting_for_approval -> running
                         -> retrying -> running
```

Authenticated chat requests automatically create a task when the client sends
`X-Dabba-Session`. Streaming output is persisted in bounded event batches.

## Repository Instructions

Dabba loads `DABBA.md` and `AGENTS.md` from the workspace root down to the
active file. Deeper files take precedence. Keep instructions concise and put
specialized rules next to the code they govern.

## Provider Fallbacks

Configure cross-model fallback chains as JSON:

```bash
export DABBA_MODEL_FALLBACKS='{
  "deepseek-ai/deepseek-v4-flash": [
    "meta/llama-3.1-8b-instruct",
    "qwen/qwen2.5-coder-32b-instruct"
  ]
}'
```

Provider adapters may also perform safe model-specific continuation. The
gateway never retries a partially emitted generic stream because that could
duplicate text.

## Secrets

Provider keys and connector OAuth tokens are stored in `platform.db` as Fernet
ciphertext. The master key is read from `DABBA_MASTER_KEY` or generated at
`$DABBA_DATA_DIR/master.key` with mode `0600`.

Back up the database and master key together. Losing the key makes encrypted
credentials unrecoverable. Do not commit either file.

Existing plaintext keys in `cli_config.yaml` are migrated into the vault the
next time the production config is loaded and the YAML file is rewritten
without key values.

## OpenTelemetry

Set an OTLP HTTP collector endpoint:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318/v1/traces
```

Dabba emits:

- `http.request` spans with method, route, and request ID.
- `dabba.http.requests` counters.
- `dabba.http.duration` histograms.
- Correlated request IDs in response headers and structured server logs.
- Local audit events when no exporter is configured.

## Deployment

Build and run the complete web/API image:

```bash
docker build -t dabba .
docker run --rm -p 8080:8080 \
  -v dabba-data:/data \
  -e DABBA_MODEL_PATH=rule_based \
  dabba
```

Or from the repository root:

```bash
docker compose -f dabba/docker-compose.yml up --build
```

Endpoints:

- UI: `http://localhost:8080`
- API schema: `http://localhost:8080/docs`
- Liveness: `http://localhost:8080/health`
- Readiness: `http://localhost:8080/ready`

## Verification

```bash
python3 -m pytest dabba/tests/test_platform_services.py -q
cd frontend
npm test
npm run build
npm run test:e2e
```

Browser automation is optional at runtime. Install Playwright and Chromium if
the `/v1/platform/browser/inspect` capability is required.

## Security Boundaries

- Web agent writes, shell commands, document generation, and MCP calls require
  approval in `ask` mode.
- Critical actions require approval even when a client requests automatic mode.
- Workspace paths are resolved and checked against the registered root.
- Connector status is `connected` only after authenticated tools are
  discovered.
- Worktree creation requires an approved `worktree_create` action.
- OAuth token exchange URLs and client credentials remain connector-specific;
  the platform supplies PKCE state, scope persistence, expiry, and encrypted
  token storage.
