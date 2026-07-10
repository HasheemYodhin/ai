# How to Use Dabba

Dabba is a personal AI coding assistant built by Hasheem. It runs as a local
server and can be used three ways: a terminal TUI, a VSCode extension, or any
OpenAI-compatible client. This guide covers day-to-day usage.

---

## 1. Start the server

Everything (TUI, VSCode extension) talks to one backend server.

```bash
cd "/home/hasheem/Hasheem files/Hasheem sub foders/ai"
python3 -m dabba.api.server
```

Leave this running. Verify it's up:

```bash
curl http://localhost:8080/health
# {"status":"healthy","version":"0.1.0","model_loaded":true}
```

To restart after a code change:

```bash
pkill -f "dabba.api.server"
cd "/home/hasheem/Hasheem files/Hasheem sub foders/ai"
python3 -m dabba.api.server
```

---

## 2. Pick a model — this matters more than anything else

Dabba supports six providers. Click the model chip in the VSCode panel (or
press **F2** in the TUI) to switch.

| Provider | Example model | Needs API key? | Good for |
|---|---|---|---|
| Anthropic | `claude-sonnet-4-6` | Yes | **Real agentic work** — editing files, running commands, multi-step tasks |
| NVIDIA NIM | `meta/llama-3.3-70b-instruct` | Yes (free tier) | Free alternative to Claude, reliable tool use |
| OpenAI | `gpt-4o` | Yes | General coding, reasoning |
| Google | `gemini-2.5-pro` | Yes | Long-context tasks (1M tokens) |
| Ollama | `llama3.3` (local) | No | Free, offline, moderate reliability |
| **dabba** (own model) | `dabba` | No | Casual chat only — **see limitation below** |

### ⚠️ Known limitation: the `dabba` model

The `dabba` model is a tiny model (8.89M parameters) trained from scratch on a
small dataset. It is **not capable of real agentic work** — it does not
reliably call tools, and for anything beyond a short greeting it tends to
repeat memorized fragments of its own training data verbatim instead of
generating a real answer. This is expected behavior for a model this size,
not a bug.

**For anything beyond casual chat — editing files, running shell commands,
multi-step tasks — switch the model chip to `claude-sonnet-4-6` or
`meta/llama-3.3-70b-instruct`.** The `dabba` model will remain available for
casual conversation and as the target of future fine-tuning (see
`train_dabba_colab.ipynb`).

Setting an API key: click the model → if no key is stored, a paste screen
opens automatically. Or in the TUI: `/keys set anthropic <key>`.

---

## 3. Using the VSCode extension

Install once:
```bash
cd "/home/hasheem/Hasheem files/Hasheem sub foders/ai/vscode-extension"
npx vsce package --allow-missing-repository
code --install-extension dabba-vscode-*.vsix --force
```

Open the ⬡ icon in the VSCode activity bar (left sidebar).

**Interface:**
- **Model chip** (top) — switch provider/model
- **Effort chip** — low / medium / high / xhigh / max (controls token budget + reasoning depth)
- **Session tabs** — multiple parallel conversations, each with its own saved history
- **🗑 button** — delete all chat history (two-step confirm)
- **⚙ button** — in-panel Settings (API endpoint, key, effort, temperature, theme)
- **📎 button** — attach a file to your next message
- **@ in the input box** — mention a workspace file, its content gets included
- **/ in the input box** — slash command autocomplete (see below)

**Live indicators while the agent works:**
- Tool cards — click to expand IN (arguments) / OUT (result)
- Todo checklist — appears automatically for multi-step requests, updates live
- Changed-files bar — shows every file the agent edited this session, click to open
- Token counter — `↑in ↓out` shown live in the status bar while thinking

Chat history is saved to disk automatically and survives VSCode reloads.

---

## 4. Slash commands

Type `/` in the chat input for autocomplete. Available commands:

| Command | What it does |
|---|---|
| `/explain` | Explain the currently **selected code** |
| `/fix` | Fix bugs in the **selected code** |
| `/test` | Generate unit tests for the **active file** |
| `/review` | Review the **active file** for issues |
| `/model <id>` | Switch model directly |
| `/effort <tier>` | Set reasoning effort: low / medium / high / xhigh / max |
| `/keys` | Show which providers have API keys configured |
| `/git <status\|diff\|log\|branch\|commit "msg">` | Run git commands |
| `/plan <goal>` | Ask the agent to plan steps before executing |
| `/tools` | List every tool the agent can call |
| `/usage` | Session token/step usage and current config |
| `/memory` | What's currently in the conversation context |
| `/compact` | Trim conversation history to save context |
| `/new-session` / `/clear` | Start a fresh conversation |
| `/help` | Show this list inside the chat |

`/explain` and `/fix` need code **selected** in the editor first. `/test` and
`/review` work on the **currently open file**, no selection needed.

---

## 5. Using the terminal TUI instead

```bash
dabba
```

Same server, same models, different interface:

- **F2** — model picker
- **F3** — effort picker
- **F4** — upload a file into the conversation
- **Ctrl+Q** — quit (not Ctrl+C — that's left free for copy/paste)
- **Ctrl+L** — clear screen
- `/keys`, `/git`, `/view <file>`, `/create <file>`, `/run <cmd>` — same idea as the slash commands above

---

## 6. What the agent can actually do (tools)

When using a capable model (Claude, 70B+), the agent can:

- **Read / write / edit files** — `file_read`, `file_write`, `file_edit`
- **List / search files** — `file_list`, `file_search`
- **Run shell commands** — `shell_exec` (git, python, npm, etc. — see allowed list in `dabba/tools/shell_tools.py`)
- **Analyze code** — `code_analyze` (pass a file path directly, or inline code)
- **Format / explain code** — `code_format`, `code_explain`
- **Track its own progress** — `todo_write` / `todo_update`, shown as a live checklist for multi-step requests

---

## 7. Training your own model further

`train_dabba_colab.ipynb` fine-tunes a real open-weight model (Llama 3.1 8B)
on free Google Colab, producing a much more capable `dabba` model than the
current tiny one. See that notebook for full instructions. After training:

```bash
export DABBA_MODEL_PATH="/home/hasheem/dabba-8b-Q4_K_M.gguf"
python3 -m dabba.api.server
```

Runs 100% offline once loaded — no Ollama, no internet required.

---

## 8. Troubleshooting

| Symptom | Likely cause |
|---|---|
| Agent repeats itself / gives nonsense | You're on the `dabba` model — switch to Claude or a 70B model |
| Shell commands / file edits silently fail | Restart the server — an old process is holding stale code in memory (Python doesn't hot-reload) |
| VSCode extension icon missing | `Ctrl+Shift+P → Reload Window` after installing/updating the extension |
| Wrong identity ("I'm Claude" instead of "I'm Dabba") | Fixed as of the persona system prompt update — restart the server if you still see this |
| Chat history gone after reload | Should now persist automatically — if not, check `workspaceState` wasn't cleared |
