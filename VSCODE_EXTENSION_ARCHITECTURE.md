# Dabba VSCode Extension — How It Works

Analysis of `vscode-extension/` as of the current source tree. Covers the manifest, activation flow, webview provider, backend protocol, webview frontend, editor integration, contributed commands, state persistence, and packaging — plus a list of inconsistencies worth fixing.

---

## 1. Extension Manifest (`vscode-extension/package.json`)

- **Identity**: `dabba-vscode`, display name "dabba AI", `version: 0.1.0`, `main: ./out/extension.js`.
- **Activation events**: `onStartupFinished`, `onCommand:dabba.openChat`, `onCommand:dabba.inlineChat`, `onCommand:dabba.explainCode`, `onCommand:dabba.refactorCode`, `onView:dabba.chat`. `onStartupFinished` makes the extension activate on every VS Code launch — the command-specific triggers are effectively redundant with it.
- **Contributed commands** (9 in the manifest): `dabba.openChat`, `dabba.focusPanel`, `dabba.newSession`, `dabba.inlineChat`, `dabba.explainCode`, `dabba.refactorCode`, `dabba.reviewFile`, `dabba.setApiKey`, `dabba.clearConversation`.
- **Views**: one activity-bar container `dabba` (icon `media/icon.svg`) containing a single webview view `dabba.chat`.
- **Keybindings**: `Ctrl+Shift+I` inline chat (editor focused, not readonly) · `Ctrl+Shift+C` focus panel · `Ctrl+Shift+J` open chat (editor not focused) · `Ctrl+Shift+N` new session (chat view focused).
- **Menus**: `editor/context` adds "Explain Code"/"Refactor Code" when text is selected.
- **Settings** (`dabba.*`): `apiEndpoint` (default `http://localhost:8080`), `model` (default `"dabba"`), `effort` (low/medium/high/xhigh/max, default medium), `maxTokens` (4096), `temperature` (0.7), `autoReviewOnSave`, `enableDiagnostics` (default true), `theme` (auto/light/dark).
- **Build scripts**: `compile` → `tsc -p ./`, `watch` → `tsc -watch`, `package` → `vsce package`. No bundler — plain `tsc` compiling `src/**/*.ts` → `out/*.js` (one file per module, CommonJS/`node16`, strict mode).

## 2. Entry Point (`src/extension.ts`)

`activate(context)`:
1. Builds `SettingsManager`, then one `ChatViewProvider` (given `extensionUri`, `settings`, `context`).
2. Builds `InlineChat`, wired to `DabbaCodeActionProvider` — quick-fix kinds (`explain`/`refactor`/`findBugs`/`addComments`) become a canned prompt + selected code, passed to `inlineChat.activateWithText(...)`.
3. Builds `DabbaDiagnostics` (auto-review on save).
4. Calls `registerAllCommands(...)` to wire every VS Code command.
5. Creates an always-visible status bar item ("$(comment-discussion) dabba") that opens chat on click.
6. Registers `ChatViewProvider` for view type `dabba.chat` with **`retainContextWhenHidden: true`** — the key setting that keeps the webview's live DOM/JS state alive when the sidebar loses focus (it does *not* survive a full VS Code reload — that's handled separately, see §8).
7. Shows a one-time welcome toast gated on `globalState.dabba.hasShownWelcome`.

`deactivate()` is a no-op; cleanup relies entirely on `context.subscriptions`.

## 3. Webview Provider (`src/chatViewProvider.ts`, ~1100 lines)

`ChatViewProvider implements vscode.WebviewViewProvider`, `viewType = 'dabba.chat'`.

**HTML/JS**: `_getHtmlContent()` builds a static HTML shell as a template string, referencing `media/style.css` and `media/main.js` via `webview.asWebviewUri(...)`, under a strict CSP (`default-src 'none'`; scripts/styles/fonts/images scoped to `webview.cspSource`, `data:`/`blob:` allowed for images). The markup includes the entire chat UI: header icons, session tabs, changed-files bar, messages container, status bar, composer (textarea, mic, attach, diff-mode toggle, model/effort chips, permission-mode toggle, send), and two full overlay panels (Settings, MCP servers) inline in the same HTML.

**Message protocol**: `resolveWebviewView` sets `enableScripts: true`, `localResourceRoots: [extensionUri]`, and listens via `onDidReceiveMessage` — a large `switch` over `message.type` handling ~30 kinds from the webview:

| Message type | Purpose |
|---|---|
| `sendMessage` | `_runAgent(text, attachments, mentions)` |
| `stopAgent` | Aborts the in-flight fetch via `AbortController` |
| `clearConversation` / `newSession` / `switchSession` / `deleteSession` / `deleteAllHistory` | Session lifecycle |
| `openSettings` / `saveSettings` / `saveApiKey` / `openNativeSettings` | In-panel settings |
| `openMcpPanel` / `addMcpServer` / `deleteMcpServer` / `reloadMcpServers` | MCP server config |
| `loadModels` / `setModel` / `setEffort` | Model/effort pickers |
| `togglePermissionMode` | Flips `ask` ↔ `auto` |
| `attachFile`, `startVoiceInput` / `stopVoiceInput` | Attachments and voice recording |
| `searchFiles`, `getMentionFileContent` | `@`-mention support |
| `approveToolCall` / `denyToolCall` | Tool-approval decisions |
| `viewDiff`, `openFile`, `insertCode` | Diff/file actions |

Extension → webview messages all flow through one helper, `_postMessage`, which also transparently records "persistable" event types (`addMessage`, `agentText`, `toolCall`, `toolResult`, `todoUpdate`, `agentPlan`, `fileChanged`) into the active session's transcript for replay after reload.

**Tool approval**: `DANGEROUS_TOOLS = {shell_exec, file_write, file_edit, markdown_to_pdf, markdown_to_docx}` plus any `mcp__*`-prefixed tool. In `ask` mode, a dangerous tool call triggers `_requestPermission`, which posts a `permissionRequired` card to the webview. The actual pause happens **server-side** — the agent's async generator blocks mid-stream awaiting `POST /v1/agent/approve` (see `dabba/api/agent_endpoints.py`'s `_pending_approvals` Future map) — the extension doesn't block locally, it just renders the prompt and forwards the decision.

**Editor context**: `_editorContext()` gathers `{workspace, active_file, selection}` (selection capped at 8000 chars) and sends it with every agent request.

**Diff handling**: On a `file_write`/`file_edit` tool call, the provider reads the target file's *current* content into `_pendingEdits` (keyed by `call_id`) before the server executes the write. On the matching `tool_result`, it re-reads the file and opens VS Code's native diff view via `DiffManager.showLiveDiff(before, after)` — read-only, since the write already happened. The webview's "⇄ View Diff" button on a tool-result card instead opens an accept/reject diff via `DiffManager.showDiff`.

## 4. Backend Communication

Uses global `fetch`, not `EventSource` — SSE is hand-parsed from a raw stream (likely because `EventSource` can't send custom `Authorization` headers or a POST body).

| Endpoint | Used by | Notes |
|---|---|---|
| `POST /v1/agent` | `_runAgent` | Body: `{message, model?, effort, permission_mode, workspace?, active_file?, selection?}`. Response streamed via `response.body.getReader()` + `TextDecoder`; buffer split on `\n\n`, `data:` prefix stripped, each chunk JSON-parsed. Events: `text`, `tool_call`, `tool_result`, `plan`, `usage`, `error`, `tool_denied`. |
| `POST /v1/agent/approve` | `_sendApproval` | Body: `{call_id, approved}` |
| `POST /v1/agent/reset` | new/clear/delete session | No body |
| `GET /v1/agent/models` | `_loadModels` | Populates the model picker |
| `GET /v1/mcp/status`, `POST /v1/mcp/reload` | MCP panel | Connect status / hot-reload |
| `POST /v1/transcribe` | voice input | Body: `{audio_base64}` |
| `POST /v1/chat/completions` | `InlineChat`, `DabbaDiagnostics` | Plain OpenAI-style completions (`stream: false`) — **a different, non-agentic endpoint** from the main chat panel; diagnostics asks for a JSON array of `{line, column?, message, severity, suggestion?}` |

All calls attach `Authorization: Bearer <key>` when a key is stored. Only the inline-chat/diagnostics endpoints use `dabba.maxTokens`/`dabba.temperature` — the main `/v1/agent` call never sends them.

## 5. Webview Frontend (`media/main.js`, ~970 lines; `media/style.css`)

Vanilla JS, no framework — a single IIFE calling `acquireVsCodeApi()` once.

- **Markdown rendering**: small regex-based renderer (no external library) — escapes HTML, turns `<thinking>...</thinking>` into collapsible cards, fenced code blocks into `.code-block` cards with copy/insert buttons, handles inline backticks/bold/newlines.
- **Message list**: `addUserMessage`, `addAgentText`, `addToolCall`/`addToolResult` (collapsible IN/OUT JSON cards with a colored status dot and friendly name via `prettyToolName`), `addPermissionCard` (Allow/Deny → `approveToolCall`/`denyToolCall`), `addPlanCard`, `addError`, `addSystemLine`, and a live `todo-card` checklist driven by `todoUpdate` events.
- **Session tabs / history**: two-click "arm/confirm" pattern for destructive deletes, since `window.confirm()` is blocked in VS Code webviews.
- **Model/effort pickers**: dropdowns from `modelsLoaded` / a hard-coded `['low','medium','high','xhigh','max']`.
- **`@`-mention picker**: fuzzy-filters a cached file list (populated via `searchFiles`), inserts a chip, fetches content via `getMentionFileContent`.
- **`/`-slash picker**: static list of 16 commands (`/explain /fix /test /review /effort /keys /git /usage /memory /new-session /model /plan /compact /diff /tools /help`). **Only `/clear` and `/new-session` are special-cased client-side** — every other slash command is sent as plain chat text; its behavior depends entirely on server-side interpretation.
- **Attachments/voice**: file chips with base64 image thumbnails; mic button toggles `startVoiceInput`/`stopVoiceInput` (recording happens in the extension host, not the webview).
- On load, posts `{type: 'ready'}` to trigger session-state + history replay, then focuses the input.

## 6. Editor Integration

- **Workspace root**: `vscode.workspace.workspaceFolders[0].uri.fsPath` — always the *first* folder; multi-root workspaces aren't specifically handled.
- **Active file/selection**: `vscode.window.activeTextEditor` → document path + selected text (capped 8000 chars), sent with every `/v1/agent` call.
- **Workspace file listing** (for `@`-mentions): a manual recursive `fs.readdirSync` walk (depth-limited to 5), skipping `.git, node_modules, __pycache__, .venv, venv, out, dist, build, .next` — does not use `vscode.workspace.findFiles`.
- **Insert-at-cursor**: `editor.edit(...)` at `editor.selection.active`, used by both the chat's code-block insert button and `InlineChat`'s result panel.
- **Code actions**: registered globally for any non-empty selection — Explain/Refactor/Find bugs/Add comments quick-fixes routing through `dabba._executeCodeAction` → `InlineChat.activateWithText`.
- **Diagnostics on save**: `onDidSaveTextDocument`, gated by `autoReviewOnSave` + `enableDiagnostics`, file size < 50000 chars, fixed language allowlist (JS/TS/Python/Java/Go/Rust/C/C++/C#/Ruby/PHP/Swift/Kotlin). Publishes to a dedicated `dabba` diagnostic collection.

## 7. Commands Contributed

| Command | Keybinding | Behavior |
|---|---|---|
| `dabba.openChat` | `Ctrl+Shift+J` | Reveals the activity-bar container |
| `dabba.focusPanel` | `Ctrl+Shift+C` | Focuses the chat view |
| `dabba.newSession` | `Ctrl+Shift+N` | Focuses the view (actual session creation happens via webview postMessage) |
| `dabba.inlineChat` | `Ctrl+Shift+I` | Input box + side panel response |
| `dabba.explainCode` / `dabba.refactorCode` | — | Canned prompt + selection → `InlineChat.activateWithText` |
| `dabba.reviewFile` | — | `DabbaDiagnostics.reviewDocument(activeEditor.document)` |
| `dabba.setApiKey` | — | Password-masked input box → `SettingsManager.setApiKey` |
| `dabba.clearConversation` | — | See §9, "known issues" |
| `dabba._executeCodeAction` *(internal)* | — | Used by code-action quick-fixes |
| `dabba.applySuggestion` *(internal)* | — | Applies a diagnostic's suggested fix |

## 8. State / Persistence

- **Chat sessions**: kept in memory as `_sessions: Session[]` (`{id, label, messages, createdAt}`), persisted to `context.workspaceState` under `dabba.chatSessions.v1`. **Scope is per-workspace** — sessions don't follow you across projects.
- **Message replay**: only `PERSISTABLE_EVENTS` are recorded per session, capped at 500 messages/session (oldest trimmed). On webview `ready`, the full stored transcript is replayed so the UI looks unchanged after a reload.
- **Webview retention**: `retainContextWhenHidden: true` keeps live DOM/JS state across sidebar-hide/show; the workspaceState replay is what covers a full VS Code reload instead.
- **API key**: VS Code `SecretStorage` (`dabba.apiKey`) — OS keychain-backed.
- **Other settings**: standard VS Code configuration (`dabba.*`), global scope.
- **Welcome flag**: `globalState.dabba.hasShownWelcome` — global, not per-workspace.
- **MCP server config**: outside VS Code state entirely — `~/.config/dabba/mcp_servers.json`, read/written directly via `fs`.

## 9. Packaging & Known Issues

- Current manifest version: **0.1.0**.
- **Version mismatch**: `dabba-vscode-0.1.0.vsix` and `dabba-vscode-0.2.0.vsix` both exist, but *both* bundled `package.json` files report `"version": "0.1.0"` internally. Whoever built the "0.2.0" file didn't bump `version` before running `vsce package` — the code inside genuinely differs between the two files (`media/main.js`, `media/style.css`, `out/chatViewProvider.js`, `out/diffManager.js`, `out/extension.js`), but the extension itself can't tell them apart at runtime. **Fix**: bump `package.json`'s `version` before every `vsce package` run.
- **Stale build artifact**: both `.vsix` files contain `out/sidePanel.js` (a `SidePanel` wrapper class that used to register `ChatViewProvider`), with no corresponding `src/sidePanel.ts` anywhere in the current source tree. It's dead code from an earlier architecture, later collapsed directly into `extension.ts`'s `activate()`, shipped because `out/` wasn't cleaned before packaging. **Fix**: `rm -rf out/` before `tsc` + `vsce package`, or add a `clean` script.
- **`dabba.clearConversation` may not reach the right webview**: it's implemented as `workbench.action.webview.sendMessage`, a generic VS Code command that targets whichever webview currently has focus — not guaranteed to be the dabba chat panel. The in-panel clear button (which posts directly through `ChatViewProvider`'s own channel) is the reliable path; the command-palette version is not.
- **No runtime npm dependencies** — the extension calls global `fetch`, `child_process.spawn`, and Node's `fs`/`path`/`os`, all either global or built-in. `devDependencies` only: `@vscode/vsce`, `typescript`, ESLint + `@typescript-eslint`.
- **No bundler**: plain `tsc -p ./`, one output file per source module. Fine for an extension this size, but means `vsce package` ships many small `out/*.js` files rather than one bundle.

---

## Summary: How a message actually flows

1. User types in the webview composer → `main.js` posts `{type: 'sendMessage', text, attachments, mentions}`.
2. `ChatViewProvider.resolveWebviewView`'s message handler calls `_runAgent`, which gathers editor context (`_editorContext()`) and `fetch`es `POST /v1/agent` on the FastAPI backend (`dabba/api/agent_endpoints.py`), with the response body manually read as a stream of `data: {...}` JSON chunks.
3. Each chunk is dispatched through `_handleAgentEvent` → `_postMessage` → the webview, which renders text tokens, tool-call/result cards, plans, or a permission-required card.
4. If a dangerous tool call needs approval, the *server* pauses execution on an `asyncio.Future`; the user's Allow/Deny click round-trips through `POST /v1/agent/approve` to resolve it.
5. On file-editing tool calls, the extension diffs the file before/after locally and opens VS Code's native diff view.
6. Session state (message history) is persisted to `workspaceState` as it streams in, so a VS Code reload replays the same conversation without re-hitting the server.
