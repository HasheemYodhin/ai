# Changelog

All notable changes to the dabba VS Code extension are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.3.3] — 2026-07-10

### Changed
- Restored Dabba's green brand accent across primary actions, focus states,
  active controls, composer highlights, and changed-file review UI while
  retaining VS Code theme colors for backgrounds, text, and surfaces.

## [0.3.2] — 2026-07-10

### Changed
- Upgraded the backend agent contract from a basic tool-calling assistant to
  a persistent VS Code software-engineering agent: inspect before editing,
  plan multi-step work, maintain task progress, execute changes directly,
  verify with focused checks, respect approvals and existing work, and finish
  with an evidence-based handoff.

## [0.3.1] — 2026-07-10

### Added
- First-run welcome screen with common coding actions, workspace context,
  backend health, and API-key setup status.
- Searchable unified session switcher and a compact overflow menu.
- Live request phases that distinguish preparing, provider wait, tool use,
  response streaming, authentication errors, and backend failures.
- Persistent “Review all” access to the last turn's batched file diff.

### Changed
- Simplified the header and composer hierarchy for narrow VS Code sidebars.
- Reworked tool calls into a compact activity timeline.
- Replaced fixed branding colors with VS Code theme tokens and added
  high-contrast focus states, reduced-motion support, responsive popovers,
  keyboard-operable history rows, and Escape-to-close overlays.

## [0.3.0] — 2026-07-07

Skipped 0.2.0 deliberately — see the history note below on why that version
number is already spent on an ambiguous, untracked build.

### Fixed
- `dabba.clearConversation` now calls `ChatViewProvider.clearConversation()`
  directly instead of the generic `workbench.action.webview.sendMessage`,
  which only reached whichever webview currently had focus.
- Removed stale `out/sidePanel.js` (dead code from a pre-refactor
  architecture, no matching `src/sidePanel.ts`) and added a `clean` script
  so it can't silently reappear in a `.vsix`.
- Stripped redundant `activationEvents` — `onStartupFinished` already
  covered every launch, making the per-command/view entries dead weight.
- `/v1/agent` requests now have a 20s connect timeout (previously could
  hang indefinitely against an unreachable server), a dedicated 401 path
  that prompts to re-run `dabba.setApiKey`, and one automatic silent
  reconnect on a mid-stream connection drop before surfacing a Retry button.
- `deactivate()` now aborts any in-flight request and denies every tool
  call still awaiting approval, instead of leaving the server's approval
  `Future` orphaned until its timeout.
- `@`-mention file search now uses `vscode.workspace.findFiles` (respects
  `.gitignore`/`files.exclude`/`search.exclude`) instead of a manual
  recursive walk with a hardcoded directory skip-list.
- Multi-root workspace support — file-relative operations (`@`-mentions,
  diffs, attachments, editor context) now resolve against the workspace
  folder containing the *active* file instead of always `workspaceFolders[0]`.
- Dangerous tool calls (`shell_exec`, `file_write`, etc.) now always show
  the approval card in an untrusted workspace, even in `auto` permission
  mode.
- MCP config path (and the Python backend's config/permissions/history
  paths) now resolve to an OS-appropriate location (`%APPDATA%\dabba` on
  Windows, `~/Library/Application Support/dabba` on macOS) instead of a
  POSIX-only `~/.config/dabba` that silently never existed on those
  platforms. No change on Linux.

### Added
- **Regenerate** — discard the last response and re-send the same message,
  without retyping it.
- **Batched multi-file diff review** — a turn that edits several files now
  shows one multi-file diff (`vscode.changes`) instead of a diff tab
  auto-popping open after every single edit.
- **Context preview** — the composer toolbar chip now shows active
  file/selection size/pinned+mentioned+attached file counts and a rough
  token estimate, with a full breakdown on hover.
- **Pinned context** — `📌` a mentioned file to auto-include it in every
  subsequent message for the rest of the session, instead of just the one
  message it was mentioned in.
- Diagnostics suggestions now surface as a real quick-fix lightbulb
  (`vscode.CodeActionProvider`) wired to `dabba.applySuggestion`, which
  previously had no UI path that ever invoked it.
- PowerShell/background-process/SSH/Docker execution tools on the backend,
  with matching slash commands in the terminal TUI (`/powershell`, `/ps`,
  `/ssh`, `/docker`).

### Changed
- Bundling: `esbuild` now produces a single `out/extension.js` instead of
  one compiled file per `src/*.ts` module. `tsc` is now type-check-only
  (`npm run check-types`, `noEmit: true`) — it no longer emits anything.
- Added a unit test suite (`vitest` + a hand-written `vscode` mock) covering
  `SettingsManager`, `DiffManager`, and `ChatViewProvider`'s message-handler
  switch, plus a GitHub Actions workflow running lint/compile/test on every
  PR and failing if `package.json`'s version wasn't bumped since the last tag.

## [0.2.0] — history note

A `dabba-vscode-0.2.0.vsix` exists in this repo with genuinely different
code from `0.1.0` (`media/main.js`, `media/style.css`, several `out/*.js`
files all differ), but its bundled `package.json` still reports version
`0.1.0` — whoever built it ran `vsce package` without bumping the version
field first. There is no corresponding changelog entry for it because
there's no way to know what it actually shipped versus `0.1.0` beyond a
line-by-line diff of the two `.vsix` files. Going forward, `npm run package`
refuses to run if the version wasn't bumped, so this shouldn't recur.

## [0.1.0]

Initial tracked version — chat panel, inline chat, code actions
(explain/refactor/find bugs/add comments), auto-review-on-save diagnostics,
MCP server support, session persistence, and provider settings.
