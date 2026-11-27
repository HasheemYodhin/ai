# Dabba audit

Scope: backend chat path to NVIDIA NIM, security and data handling, and the web frontend (`frontend/`). The CLI and VS Code extension were only checked where they share backend routes. Audited 2026-11-20 on branch `feat/firstbranch`, read-only.

Claims marked **verified** were reproduced against the running server or confirmed in code by a second reader.

## Summary

| Severity | Count | Theme |
|---|---|---|
| Critical | 5 | Unauthenticated routes that run shell commands, change API keys and spend model quota; open CORS; secrets committed to git |
| High | 15 | Stop doesn't stop upstream, error masking, no input limits, no context trimming, whole-app re-render per token, accessibility |
| Medium | 15 | Model config scattered, no usage tracking, reasoning output, stuck tasks, prompt injection, bundle size, design consistency |
| Low | 8 | Keepalive format, logging format, upload limits, small UI gaps |

The Critical items mean that today anyone on the same network, or any website the user visits while Dabba is running, can run shell commands on the machine. They should be fixed before anything else, and before Dabba is reachable from any shared network.

---

## Critical

### C1. Unauthenticated shell execution through the agent endpoint (verified)
- **Where:** `dabba/api/agent_endpoints.py:1225` sends any message that looks like a command to `_exec_shell_response`, which runs `subprocess.run(command, shell=True)` at line 449. `POST /v1/agent` has no session check.
- **Why it matters:** combined with C3 (open CORS) and the server listening on `0.0.0.0` (`dabba/config/api_config.py:17`), any device on the network, or any web page open in the user's browser, can run commands as the user.
- **Fix:** require a Dabba session on `/v1/agent*`. Remove the bare-command shortcut or put it behind the existing approval flow. Listen on `127.0.0.1` by default.

### C2. Unauthenticated routes that manage keys, MCP servers and hooks (verified for GET, code-read for writes)
- **Where:**
  - `POST`/`DELETE /v1/agent/keys` (`agent_endpoints.py:1458`, `1495`)
  - `POST /v1/mcp/servers` (`agent_endpoints.py:1586`, saves and launches any command)
  - `POST /v1/hooks` (`dabba/api/hooks_endpoints.py:42`, shell commands)
  - `POST /v1/agent/approve` (`agent_endpoints.py:1378`)
- **Verified:** `GET /v1/agent/keys` and `GET /v1/agent/models` return 200 with no session, while `GET /v1/platform/tasks` correctly returns 401.
- **Why it matters:** a caller can swap in their own provider key and collect every prompt, delete keys, or start arbitrary processes through MCP or hooks.
- **Fix:** session check on all of these, and restrict key, MCP and hook management to admin users.

### C3. CORS accepts any origin with credentials (verified)
- **Where:** `dabba/config/api_config.py:20` (`cors_origins=["*"]`) with `allow_credentials=True` in `dabba/api/server.py`.
- **Verified:** a preflight from `Origin: https://evil.example` is answered with that origin and `allow-credentials: true`.
- **Why it matters:** this is what lets any website the user visits call C1 and C2 from the user's browser.
- **Fix:** an explicit allow-list (the frontend's own origin), configurable through an env var.

### C4. Chat and code execution open to anyone (verified in code)
- **Where:** `dabba/api/chat_endpoints.py:119` and `:153` use `Depends(lambda: None)`, so `get_auth` (line 110) is never applied. `ApiKeyAuth` returns `None` when no keys are configured (`dabba/api/auth.py:96`), which is the default.
- **Why it matters:** anyone who can reach the server spends the NVIDIA quota. `/execute` runs code with resource limits but no filesystem or network isolation (`dabba/api/execution_endpoints.py:104`).
- **Fix:** require a session on `/v1/chat/completions` and `/execute`. Run `/execute` in a container or nsjail.

### C5. Secrets and user data committed to git (verified)
- **Where:** `.dabba-data/master.key`, `.dabba-data/platform.db` (a user's password hash and a session hash), `.dabba-data/backups/platform-before-auth-merge-*.db` and `.dabba-data/cli_config.yaml` are tracked. `.gitignore` covers `.dabba/` but not `.dabba-data/` or `.env`. There is no `.env.example`.
- **Note:** the committed `master.key` is not the one in use (`~/.config/dabba/master.key`), and the committed secrets table is empty, so no live provider key is exposed through git.
- **Why it matters:** a committed encryption key and password hash, and nothing stops the next one being committed.
- **Fix:**
  - `git rm --cached` the files and ignore `.dabba-data/` and `.env`.
  - Add `.env.example` with placeholders.
  - Reset that user's password.
  - Decide whether to rewrite history (see open questions).
- **Related:** an NVIDIA key was pasted into a chat earlier in this project's work. If it has not been revoked at build.nvidia.com yet, revoke it.

---

## High

### Backend

**H1. Stop doesn't cancel the upstream NVIDIA request.**
- **Plain chat** (`dabba/api/chat_endpoints.py:470-502`, `dabba/providers/nvidia_provider.py:501+`): on client abort only the asyncio side is cancelled. The worker thread keeps reading the stream, and up to 4 auto-continuations still run and are billed.
- **Agent path** (`agent_endpoints.py:628-636, 1191, 1289`): disconnects are deliberately ignored, so Stop only hides the output while tools and model calls continue.
- **Fix:** close the provider generator and the OpenAI stream in a `finally`, and check a cancel flag between chunks. For the agent, add a cancel endpoint or flag checked between steps, with "finish in background" as an opt-in.

**H2. Errors are misreported and trip the circuit breaker for everyone.**
- **Where:** `dabba/platform/provider_gateway.py:110-118, 216-219, 246-251`.
- **What's wrong:**
  - "NVIDIA API key not set" and HTTP 404/410 (retired model) are mapped to a generic, *retryable* `provider_unavailable`.
  - They are then retried, counted as failures, and after 3 they open the circuit for every user.
  - `stream()` silently skips a blocked model, so the user sees "No provider was available" instead of "cooling down".
- **Fix:** map a missing or invalid key to a non-retryable `provider_authentication` error and 404/410 to `model_unavailable`. Report the circuit-open reason in `stream()` the way `run()` does.

**H3. Key status disagrees with key use.**
- **Where:** `agent_endpoints.py:1419-1430` vs `dabba/providers/registry.py:76-80`.
- **What's wrong:** `has_key` ignores the provider-level `nvidia` key, but calls fall back to it. A stale per-model key takes priority over a valid provider key and causes 403s, which happened during this project.
- **Fix:** compute `has_key` with the same resolution as the call path, and show which key a model uses in the key settings.

**H4. No validation or size limits on chat requests.**
- **Where:** `dabba/api/openai_compat.py:51-105`, `chat_endpoints.py:136`, `registry.py:196-197`.
- **What's wrong:** messages, roles, content length, `temperature` and `max_tokens` are unchecked. A client `max_tokens` overrides the effort setting with no cap, and there's no body-size limit.
- **Fix:** a Pydantic request model with bounds (message count, characters per message, `max_tokens` ≤ the model's output limit, `temperature` 0–2) and a body-size middleware.

**H5. No context-window management for plain chat.**
- **Where:** `frontend/src/hooks/useChat.ts:236` sends the full history; `chat_endpoints.py` forwards it.
- **What's wrong:** long chats fail with `context_length_exceeded` (`provider_gateway.py:103`). Summarization exists only on the agent path (`dabba/agent/context_manager.py`, `agent_loop.py:744`).
- **Fix:** estimate tokens against the model's context window and trim or summarize the oldest turns, reusing the agent's context manager.

**H6. Rate limiting is per IP and covers only some routes.**
- **Where:** `dabba/api/rate_limiter.py:198`, `chat_endpoints.py:141`.
- **What's wrong:** only chat, embeddings and execute are limited. `/v1/agent`, images, audio, platform and skill import are not. Users behind one proxy share a bucket.
- **Fix:** key by user ID and apply to all model and write routes.

**H7. Published artifacts run as HTML on the API's own origin.**
- **Where:** `dabba/api/platform_endpoints.py:1834` (`FileResponse`, no CSP).
- **What's wrong:** when the frontend is served from the same origin (`DABBA_FRONTEND_DIR`), a published page can read the session token from `localStorage`.
- **Fix:** send `Content-Security-Policy: sandbox allow-scripts`, and serve published pages from a separate origin.

### Frontend

**H8. Every token re-renders the whole app.**
- **Where:** `frontend/src/hooks/useChat.ts:194,198`, `frontend/src/hooks/useHistory.ts:~115`, `frontend/src/components/MessageBubble.tsx:27`.
- **What's wrong:**
  - Each chunk builds a new `messages` array and calls `saveConversation`, then `setConversations`.
  - So the app, the sidebar, the conversation list and every message re-render on every token. `MessageBubble` is not memoized.
- **Why it matters:** the jank on long chats. Today's fix (throttled reveal, deferred markdown) reduced the cost but not the cause.
- **Fix:**
  - `memo(MessageBubble)` with stable callbacks.
  - Buffer streamed text and commit once per frame.
  - Update the sidebar once when the stream ends.

**H9. The default model doesn't exist.**
- **Where:** `frontend/src/hooks/useSettings.tsx:54` (`'dabba-10m'`) and `frontend/src/lib/models.ts:9-11`.
- **What's wrong:** the server's local model ID is `dabba`, so new users start on an invalid model.
- **Fix:** default to the catalog's `current` (or first) model and drop the stale fallback list.

**H10. Failed chat saves are silent.**
- **Where:** `frontend/src/hooks/useHistory.ts:82, 162` only call `console.error`.
- **Why it matters:** the chat exists only in memory and is lost on reload, with no warning.
- **Fix:** a visible "Not saved, retry" state, a local queue, and retry with backoff.

**H11. Dialogs and menus aren't keyboard accessible.**
- **Where:** `ModelSwitcher`, `PlusMenu`, `SettingsModal`, `SkillModal`, `SkillImportModal` and `ProjectModal`.
- **What's wrong:** no `role="dialog"`, `aria-modal` or focus trap, and Esc doesn't close them.
- **Fix:** one shared `Dialog` primitive with focus trap, Esc, and focus returned to the trigger.

**H12. Icon-only buttons without labels.**
- **Where:** `SettingsModal` (21 buttons, 4 labelled), `CoworkPage` (13/5), `Sidebar` (13/4), `ArtifactPanel` (11/5), `CoworkWorkspace` (8/1), `FolderPicker` (7/0).
- **Fix:** `aria-label` on every icon-only button.

**H13. Model IDs hardcoded in the frontend.**
- **Where:**
  - `frontend/src/hooks/useChat.ts:25-26` (fallback models)
  - `frontend/src/lib/models.ts:42-53` (vision detection by regex)
- **Fix:** read fallback and vision flags from `/v1/agent/models` (depends on M1).

**H14. The model picker shows no capabilities.**
- **Where:** `frontend/src/components/ModelSwitcher.tsx`.
- **What's wrong:** only the name, tier and description are shown; no context size, vision or reasoning.
- **Fix:** small capability labels from the catalog (depends on M1).

**H15. No offline handling.**
- **What's wrong:** a dropped stream becomes a generic error with Retry, and the partial text isn't treated as partial.
- **Fix:** an offline banner, keep the partial text, and offer "Continue" when the stream breaks mid-way.

---

## Medium

**M1. No single model registry.**
- **What's wrong:** model properties are spread across string matches and lists.
  - `dabba/providers/base.py` `ModelInfo` has no `max_output_tokens` or `supports_vision`.
  - Hardcoded IDs and rules:
    - `nvidia_provider.py:41-45` (capacity fallbacks)
    - `nvidia_provider.py:352-374` (reasoning and timeout rules by string)
    - `platform_endpoints.py:474-478` (Cowork fallbacks)
    - `api_config.py:23-25` (`available_models` = dabba, llama3, gpt-4)
    - the frontend items in H13
  - The NVIDIA catalog also went stale once (19 of 20 models retired), which went unnoticed until chats failed.
- **Fix:**
  - Add the missing fields to `ModelInfo` and drive fallbacks, reasoning, vision and timeouts from them.
  - Expose them through `/v1/agent/models`.
  - Add a check that flags catalog models NVIDIA no longer lists.

**M2. `max_tokens` ignores the model's output limit.**
- **Where:** `dabba/providers/base.py:9-15` (`EFFORT_PARAMS`: Max = 32768 for every model).
- **Fix:** clamp to `ModelInfo.max_output_tokens`.

**M3. Reasoning output is dropped or leaked.**
- **Where:** `nvidia_provider.py:747-756` reads only `delta.content`.
- **What's wrong:**
  - `reasoning_content` is discarded, so reasoning models look frozen while they think.
  - Inline `<think>…</think>` isn't stripped.
- **Fix:** stream reasoning as a separate SSE field, strip `<think>` blocks, and show a collapsible "Thinking" section in the UI.

**M4. No per-user usage or cost tracking.**
- **What's wrong:** usage is only inside task-result JSON, despite cost fields existing on `ModelInfo`.
- **Fix:** a `usage` table (user_id, model, prompt/completion tokens, cost, timestamp) written when each stream ends.

**M5. Chat storage can't be queried.**
- **Where:** `~/.config/dabba/conversations.db` stores each chat's messages as one JSON text field (`dabba/api/conversations_endpoints.py:36`), separate from `platform.db`.
- **Fix:** a `messages` table with model, tokens and timestamp columns (see open question on the database).

**M6. Every chat request writes a task row containing the full history.**
- **Where:** `chat_endpoints.py:438-467`.
- **What's wrong:** tasks interrupted by a restart stay "running" forever. Three are stuck now.
- **Fix:** store a reference rather than the history, and mark interrupted tasks failed at startup.

**M7. No prompt-injection handling for untrusted content.**
- **What's wrong:** document text, fetched pages, MCP tool output and imported skills reach the model unlabelled.
- **Fix:** wrap them in delimited "untrusted content" blocks, and require approval for actions that content asks for.

**M8. Status endpoints open without a session.**
- **What's wrong:** `/v1/agent/keys` (which providers have keys), `/v1/mcp/status`, `/v1/hooks` and `/v1/agent/processes` all answer without a session. No key values leak.
- **Fix:** put them behind the session check (folds into C2).

**M9. `NVIDIA_API_KEY` from the environment is ignored.**
- **Where:** `nvidia_provider.py` reads only the encrypted vault.
- **Fix:** read the env var as a fallback, or document that only the vault counts.

**M10. Encryption key stored next to the vault.**
- **Where:** `~/.config/dabba/master.key` sits beside the encrypted secrets.
- **Fix:** document `DABBA_MASTER_KEY` (already supported at `dabba/platform/services.py:719`) for production.

**M11. Long chats aren't virtualized.**
- **What's wrong:** every message stays mounted. This is fine below roughly 200 messages.
- **Fix:** add after H8, either `react-virtuoso` or "Show earlier messages".

**M12. Bundle size.**
- **Where:** `frontend/src/components/MarkdownRenderer.tsx:3`, `frontend/src/components/ArtifactPanel.tsx:2`.
- **What's wrong:** the full Prism build of `react-syntax-highlighter` is imported, and its theme chunk alone is 663 KB.
- **Fix:** `PrismLight` with about a dozen registered languages.

**M13. No LaTeX.**
- **Fix:** add `remark-math` and `rehype-katex`, lazy-loaded with the markdown chunk.

**M14. Chat titles.**
- **Where:** `frontend/src/hooks/useHistory.ts:6-15`.
- **What's wrong:** the title is the first message cut to 60 characters, and empty chats are saved as "New conversation".
- **Fix:** generate a short title with a fast model after the first reply, and don't save empty chats.

**M15. Design consistency outside the chat screen.**
- **What's wrong:**

  | Problem | Count | Worst files |
  |---|---|---|
  | Hardcoded palette classes | 167 | `ConnectorsPage` 32, `MarkdownRenderer` 13 |
  | 8–10px text | 72 | `SettingsModal` 14, `CoworkPage` 10 |
  | `font-bold` | 37 | `SettingsModal` 14 |
  | `uppercase` labels | 21 | `SettingsModal` 8 |

  - Markdown inline code, tables and blockquotes also use off-token colors and italic.
- **Fix:** the same polish pass the chat screen got, applied to Settings, Cowork and Connectors, and colors mapped to tokens.

---

## Low

- **L1.** `chat_endpoints.py:487-490`: the keepalive sends an empty content chunk instead of an SSE comment. Yield `": keepalive\n\n"`, as the local path does at line 367.
- **L2.** Logging is plain text with only a request ID. Use a JSON formatter with user, model, tokens and latency.
- **L3.** Upload limits are very generous: 10 GB zip, 100k entries, 100 MB multipart (`dabba/api/document_endpoints.py:22-29`). Image `size` is passed through unchecked. Lower the limits and allow-list sizes.
- **L4.** `conversations_endpoints.py:7-9`: the docstring says knowing a `user_id` grants access, but the code checks the session (lines 95, 163). Fix the docstring.
- **L5.** No approximate token count in the composer; the character counter appears only near 50k (`frontend/src/components/InputArea.tsx:~479`).
- **L6.** Follow-up suggestions appear about a second before the reply finishes revealing (`frontend/src/components/ChatWindow.tsx`, follow-up row).
- **L7.** The jump-to-bottom button is `position: fixed` and can overlap the composer on small screens. Make it sticky inside the scroll area.
- **L8.** The skill import's SSRF check resolves DNS before connecting, which leaves a small DNS-rebinding window (`dabba/platform/skill_import.py`). Pin the resolved IP for the request.

---

## Tests

- **Python:** 443 tests. Chat-completion basics are covered in `dabba/tests/test_api.py`.
- **Not covered:**
  - SSE streaming, `[DONE]` and errors mid-stream
  - client abort cancelling upstream
  - 429/5xx retries and the error mapping in H2
  - authentication on every route
- **Frontend:** 10 unit tests and 1 end-to-end test (login).
- **Plan:** each Critical/High fix lands with a test for the path it changes. Add an auth test that walks every registered route and asserts 401 without a session.

## Already done well

- No browser-to-model calls: all model traffic goes through the backend.
- Provider keys are encrypted at rest and never returned by the API.
- Passwords use PBKDF2 (310k iterations). Session tokens are stored hashed.
- Conversation routes check the session against the user.
- OpenAI-style SSE with `[DONE]`, a usage chunk, and errors sent in-stream to the UI.
- Explicit NVIDIA timeouts, capacity backoff, max-tokens clamp on 422, and a per-model circuit breaker with persisted health.
- No raw HTML in markdown (no XSS through replies). Artifact previews run in `sandbox="allow-scripts"` iframes.
- The frontend already has Stop (aborts the request), regenerate with model choice, edit-and-resend, copy on messages and code, Retry on failures, smart auto-scroll with a jump button, an auto-growing input with Enter/Shift+Enter, and dark/light themes.

---

## Open questions (needed before Phase 2)

1. **Auth model.** Dabba already has user accounts and sessions. Should every API route require that session, including use by the CLI and VS Code extension? If so, the CLI and extension need a login or token flow. Is there any route that must stay open?
2. **The bare-command shortcut (C1).** Typing a shell command into the agent runs it directly. Should it be removed, kept behind the approval prompt, or kept for local-only use?
3. **Git history (C5).** Remove the committed `.dabba-data/` files going forward only, or also rewrite history? Rewriting needs a force-push and coordination with anyone who has cloned the repo.
4. **Database.** Keep SQLite (current) and add proper `messages` and `usage` tables, or move to Postgres?
5. **Code execution isolation (C4).** Is Docker available where Dabba runs (to sandbox `/execute`), or should code execution be disabled outside local use?
6. **Branch.** Phase 2 work would go on a new `feature/dabba-audit-fixes` branch. The current branch `feat/firstbranch` has a lot of uncommitted work from earlier sessions (NVIDIA catalog, UI redesign, skill import, streaming). Should that be committed on `feat/firstbranch` first, or carried onto the new branch?

## Remediation review

The changes below were made on the current branch. SQLite remains the storage backend.

| Finding | Change or remaining work |
|---|---|
| C1, C2, C3, M8 | API routes require a session, with public exceptions for account creation, login and published artifacts. Host tools and shared settings require an administrator. The bare-shell shortcut was removed. The API defaults to loopback and an explicit CORS allowlist. |
| C4 | Chat requires a session. API code execution is disabled by default. A server operator can enable local administrator access through the API configuration. Container isolation remains open. |
| C5 | Runtime files were removed from Git’s index and preserved locally. Added ignore rules, an environment template and a password reset command. Password reset, provider-key revocation and repository-history coordination require the account or repository operator. |
| H1, L1 | Chat streams emit SSE comment keepalives and close the NVIDIA stream after the current blocking read finishes. Agent streams stop draining on disconnect. Immediate interruption of a blocking provider read or a running tool still needs work. |
| H2, H3, M9, M10 | Provider authentication and retired-model errors are classified without tripping the circuit breaker. Streaming reports cooldowns. Model key status uses the same resolution as requests and shows the key source. Documented the vault master key and added the NVIDIA environment fallback. |
| H4, H5, H6, M2 | Chat input is validated and bounded. Catalog-backed providers clamp output budgets and trim older turns using estimated context size. API writes use per-user rate limits. Exact per-model output ceilings and local model context handling remain incomplete. |
| H7 | Public responses use a sandbox CSP and an opaque origin. Dedicated artifact hosting remains open. |
| H8, H10, H15, M11 | Plain chat batches token renders, memoizes bubbles and avoids history updates for each token. Long chats initially show the latest 100 messages. Failed saves show a retry action and queue locally for retry after a reload. The app shows offline state, preserves partial replies and offers Continue after an interruption. Agent stream batching remains open. Local retries fall back to memory if browser storage is full or disabled. |
| H9, H13, H14, M1 | Migrated the invalid default to `dabba` and removed stale frontend model choices. The picker consumes context, reasoning, vision and fallback metadata from the API. Full provider registry consolidation, default selection from the live catalog and catalog retirement monitoring remain open. |
| H11, H12, L5–L7 | Added keyboard focus management and labels to audited controls, approximate composer token count, reveal-aware follow-ups and scroll-area positioning for the jump button. A browser-wide accessibility pass remains open. |
| M4, M6, L2 | Provider-reported token usage is stored per user and chat task. New task records omit the full prompt history. Startup recovers stale chat tasks after a grace period. Request logs include JSON request, latency and user fields. Cost attribution, usage from interrupted responses and model/token fields in request logs remain open. |
| M7 | Tool, document and research content is labelled untrusted. Imported skill handling and mandatory approval for actions suggested by untrusted content remain open. |
| M12, L3, L4, L8 | Reduced the syntax-highlighting bundle, tightened attachment and image inputs, corrected the conversation auth docstring and pinned DNS-validated connections for skill imports. |
| M14 | Empty conversations stay out of remote history. A configured fast model can generate a title after the first completed reply. |
| M5 | Added a queryable SQLite message index with model, token and timestamp columns. The migration backfills existing chats. |
| M3 | NVIDIA inline thoughts and native reasoning deltas are separated from answer text. The chat displays reasoning in a collapsible Thinking section. |
| M13, M15 | The lazy Markdown renderer handles LaTeX. Settings, Cowork, Connectors and Markdown use more consistent type and neutral colors. |
