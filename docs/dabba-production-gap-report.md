# Dabba production gap report

**26 November 2026**

Dabba already has a public trial and a broad signed-in workspace. The highest-value changes are account recovery, cross-device project storage, and a release check that exercises real user workflows. These address concrete gaps in the existing product before expanding the model catalog or adding more automation features.

## What was verified on Render

The public site was inspected in an isolated Chromium browser at desktop width and the homepage at 390 px. HTTP checks covered public routes, readiness, health, search metadata, and the signed-out authentication boundary.

| Check | Result |
|---|---|
| Homepage, trial, login, signup, privacy, and terms | All six pages rendered. The inspected pages had no horizontal overflow. The browser captured no JavaScript errors during this walkthrough. |
| Mobile homepage | Login, signup, trial, and footer links remained visible. The desktop section navigation disappeared from the mobile header. |
| Unknown page | A direct request to `/features` returned HTTP 200, then rendered the app’s page-not-found view. The landing page’s Product link uses `#features` and is valid. |
| Search and sharing metadata | The tested HTML routes shared the homepage title. The homepage response had no canonical link. robots.txt was served, and sitemap.xml returned HTTP 404. |
| Backend readiness | /ready returned HTTP 200 with storage available. /health returned HTTP 200 with a loaded model flag. |
| Protected data | The usage endpoint returned HTTP 401 without a session. |

[Live homepage](https://ai-x8ud.onrender.com/) · [Guest trial](https://ai-x8ud.onrender.com/try) · [Login](https://ai-x8ud.onrender.com/login) · [Readiness](https://ai-x8ud.onrender.com/ready) · [Robots](https://ai-x8ud.onrender.com/robots.txt) · [Sitemap](https://ai-x8ud.onrender.com/sitemap.xml)

The signed-in findings below come from the repository. Guest generation, third-party credentials, protected production workflows, first-token latency on hosted models, and real microphone playback were outside this walkthrough. The public browser session did not submit messages or forms or change production data.

## P0 before wider hosted use

### Account recovery and workspace onboarding

The live login screen offers login and account creation. It has no password-recovery link. The workspace card on the homepage points to the same signup route as the personal card, while the application assigns owner access to the first account on an installation. The personal card also advertises scheduled skills, which the app currently gates to owners.

Add password recovery with expiring single-use links and session revocation. Give hosted signup and self-hosted setup distinct destinations. Explain on each signup path which features the new account will receive. For an installation intended for a team, define how the operator establishes ownership and invites members. Verify signup, reset, sign-in, revocation, and deep-link return on a disposable staging account. [Login](https://ai-x8ud.onrender.com/login) · [Landing plans](../frontend/src/content/landing.ts) · [Identity service](../dabba/platform/services.py)

### Projects across devices and accounts

Conversation records carry a project ID on the server. Project names, colors, and instructions are stored under a single browser-local key without account scoping. This can leave projects missing on another device and can retain project metadata for the next account in the same browser. The landing page also describes grouping files by project, while the project settings inspected in source manage folder metadata and instructions.

Move projects and their instructions into account-scoped server records. Migrate existing projects once with a preview, keep conversation associations intact, and define explicit project-file behavior. Verify that one account sees the same project and instructions on two devices and that a second account cannot see them. [Project storage](../frontend/src/hooks/useProjects.ts) · [Project editor](../frontend/src/components/ProjectModal.tsx) · [Conversation API](../dabba/api/conversations_endpoints.py)

### Releases and full backups

Render is configured to deploy commits automatically. Its readiness route checks database access. That signal can stay green while a cloud model, guest trial, connector, or speech feature is unavailable. The repo already has an image smoke check, a full-data backup script, and SQLite replication. The live health response reports a generic version and does not identify the deployed revision. Replication covers two SQLite databases, while documents and artifacts also have file content.

Expose a release identifier and provide a staging smoke run for guest status, signed-in chat, first token, settings, and browser Python. Keep readiness focused on the core service and surface optional capability failures separately. Schedule a full-data backup and run a clean-disk restore drill that checks conversations, provider-key decryption, artifacts, and original documents. Record backup freshness, recovery time, and the last tested rollback target. [Render config](../render.yaml) · [Platform CI](../.github/workflows/platform-ci.yml) · [Backup configuration](../deploy/litestream.yml) · [Full-data backup script](../deploy/backup-data.sh)

## P1 strengthen everyday workflows

| Module | What to change behind it | Acceptance check |
|---|---|---|
| **Chat and model routing** | Add a single turn identifier across client, API, and provider calls. Repeated IDs currently prevent a second call but do not replay a completed result. Return existing status or output, preserve partial replies, and distinguish connecting, reasoning, capacity, and interrupted states. Surface the actual model used when a fallback occurs. | Disconnect once mid-stream and retry. Confirm one provider generation, one saved turn, and a clear recovery action. [Chat API](../dabba/api/chat_endpoints.py) · [Web chat](../frontend/src/hooks/useChat.ts) |
| **Models and keys** | Lead with usable presets for everyday chat, fast replies, and deeper reasoning. Show which credentials are configured and which have been verified. Provide an explicit owner-initiated provider check and actionable errors for expired credentials or retired models. | Each supported provider has a staged success, rejected-key, and unavailable-model case. [Model picker](../frontend/src/components/ModelSwitcher.tsx) · [Settings](../frontend/src/components/SettingsModal.tsx) |
| **Guest trial** | Explain limits and availability near the composer. The guest transcript is stored in that browser. Add an explicit way to copy it or import it after sign-in, with consent and clear retention terms. Keep the trial usable when the configured provider is down by showing a sample transcript and a retry state. | Open trial, check the outage state, and complete a consented upgrade with the expected transcript. [Guest chat](../frontend/src/components/GuestChatPage.tsx) · [Guest API](../dabba/api/guest_endpoints.py) |
| **Voice, files, and code** | Explain microphone permissions, browser fallback, and runtime limitations where users act. Add per-file progress and retry, and preserve page or section references in extraction results where available. Label browser Python separately from server execution and clarify when a snippet needs a terminal. | Use real desktop and mobile microphone/playback checks. Test a scanned PDF, a partial extraction, Python input, and a timed-out snippet. [Voice](../frontend/src/lib/voice.ts) · [Document API](../dabba/api/document_endpoints.py) · [Browser runner](../frontend/src/lib/browserPython.ts) |
| **History and search** | Conversation saves already use revisions and preserve a recoverable copy. Search now finds message text and shows snippets. Add a jump to the matching message, paginated history, and clear pending-save or delete states. | Find an older message, open it directly, then verify offline edits and deletion recovery across two sessions. [History](../frontend/src/hooks/useHistory.ts) · [Conversation list](../frontend/src/components/ConversationList.tsx) |
| **Agents, Cowork, and Task Center** | Give users a run detail page with effective settings, approvals, output, and cancellation state. Task Center polls every five seconds. Its generic Resume action can put a task back in the queue, but the route alone does not prove a worker will resume every task type. Only offer Resume where an executor can honor it. | Verify cancel and retry for each task type, including worker restart and a pending approval. [Task Center](../frontend/src/components/TaskCenterPage.tsx) · [Task API](../dabba/api/platform_endpoints.py) |
| **Scheduled Skills** | Let the owner select an IANA time zone and show the next run in that zone. The scheduler currently computes cadence in UTC. Define what happens when a server is down at the scheduled time and make interrupted runs actionable. | Verify weekday scheduling, a time-zone change, missed occurrences, and recovery without duplicate runs. [Schedules UI](../frontend/src/components/ScheduledSkillsPage.tsx) · [Schedule service](../dabba/platform/services.py) |
| **Connectors and Hooks** | Show installation, tool discovery, account authentication, and tool permissions as distinct states. Add a supported connector verification step and last-success timestamp. For hooks, provide event examples, a controlled dry-run workflow, and visible run history. | Verify a connected test account, an expired credential, a stopped connector, and a dry-run result on staging. [Connectors](../frontend/src/components/ConnectorsPage.tsx) · [Hooks](../frontend/src/components/HooksPage.tsx) |
| **Usage and data controls** | The three chat budgets count tokens reported by completed requests. If hosted budgets must be hard spending limits, reserve capacity at admission and reconcile on completion. Define metering for failed or interrupted replies and background runs. Add a separate account-level export and deletion workflow if hosting other users, with clearly documented scope. | Submit simultaneous requests near a limit and verify the expected admission behavior. Verify that exports contain the stated data and that account deletion follows the stated retention rules. [Usage service](../dabba/platform/services.py) · [Settings](../frontend/src/components/SettingsModal.tsx) |

## P2 improve discovery and support

- **Public pages and search metadata.** Set the deployment’s public site URL so the sitemap is emitted. Serve distinct titles, canonical URLs, and social previews for indexable public pages. Return an actual HTTP 404 for unknown routes while preserving known application deep links. Add crawl and sharing checks to the build. [Metadata build](../frontend/scripts/site-metadata.mjs) · [Server routing](../dabba/api/server.py)
- **Help and first-run setup.** Add a Help entry with a hosted quick start, provider-key setup, self-host instructions, extension setup, and common errors. On mobile, give users a way to reach homepage sections from the header. Explain which landing figures represent catalog entries, configured capabilities, or verified connections. [Homepage](https://ai-x8ud.onrender.com/) · [Landing content](../frontend/src/content/landing.ts)
- **Support and diagnostics.** Carry the existing request ID into user-facing errors and let a user copy it. Give operators a view of first-token latency, provider failures, rate limits, job backlog, backup freshness, and release version. Keep prompts and credentials out of diagnostics. [Server request logging](../dabba/api/server.py)
- **Chrome and VS Code.** Verify account sign-in, key expiry, model selection, and streaming against the same staging server. The Chrome extension currently declares broad site access. Review that scope and use the minimum needed for its features. [Chrome manifest](../chrome-extension/manifest.json) · [VS Code client](../vscode-extension/src/chatViewProvider.ts)
- **Accessibility and performance.** Expand tests from layout assertions to keyboard-only navigation, focus restoration, readable errors, and real touch devices. Measure a cold start, opening a long conversation, and scrolling Markdown during generation. Use those results to choose performance work. [Browser test configuration](../frontend/playwright.config.ts)

## Delivery order

1. **Staging and release verification.** Identify the deployed build and document what works for guests, members, and owners. Set up the release smoke test, recovery flow, and full restore drill.
2. **Cross-device product behavior.** Move projects to the server, make signup expectations clearer, and finish chat retry and search recovery.
3. **Background work and limits.** Implement executor-aware task recovery, explicit connector verification, local-time scheduling, and the budget policy chosen for hosted accounts.
4. **Capabilities and discovery.** Improve attachments, audio and code guidance, extension parity, public metadata, help, and measured mobile performance.

The first release is ready when a staging guest can open the trial, a member can recover access and use the same project on two devices, and an owner can verify a connector and restore the workspace into a fresh environment.
