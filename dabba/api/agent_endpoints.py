"""
Agent streaming endpoints — powers the VSCode extension's Claude Code-style panel.

POST /v1/agent  →  Server-Sent Events stream of agent loop events:
    {"type": "text",        "content": "..."}
    {"type": "tool_call",   "content": {"name": ..., "arguments": {...}}}
    {"type": "tool_result", "content": {"tool": ..., "success": ..., "output": ...}}
    {"type": "done",        "content": {"steps": N}}
    {"type": "error",       "content": "..."}
"""
from __future__ import annotations

import asyncio
import json
import subprocess
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from dabba.utils.memory_manager import get_memory_manager

_memory_manager = get_memory_manager()


class AgentRequest(BaseModel):
    message: str
    model: Optional[str] = None
    effort: Optional[str] = None
    # Editor context sent by the extension
    workspace: Optional[str] = None       # workspace root path
    active_file: Optional[str] = None     # currently open file
    selection: Optional[str] = None       # selected code
    reset: bool = False                   # clear conversation first
    permission_mode: str = "ask"          # "ask" pauses for approval, "auto" skips it


class ApprovalRequest(BaseModel):
    call_id: str
    approved: bool


# Same set the CLI's `/keys` command validates against — see cli/session.py's _cmd_keys.
VALID_KEY_PROVIDERS = {"anthropic", "openai", "google", "nvidia", "huggingface"}


class SetApiKeyRequest(BaseModel):
    provider: str
    key: str


class AddMcpServerRequest(BaseModel):
    name: str
    command: str
    args: List[str] = []
    env: Dict[str, str] = {}


# Tools that pause for approval in "ask" mode — must match the real registered
# tool names in dabba/tools/*.py (shell_exec, file_write, file_edit, and the
# markdown_to_pdf/docx artifact tools, which write files just like file_write).
APPROVAL_REQUIRED_TOOLS = {"shell_exec", "file_write", "file_edit", "markdown_to_pdf", "markdown_to_docx"}
APPROVAL_TIMEOUT_SECONDS = 180


def _requires_approval(tool_name: str) -> bool:
    """
    Every "mcp__<server>__<tool>" tool requires approval regardless of the
    static set above — it's arbitrary third-party code from a
    user-configured external server (see dabba/agent/mcp_client.py), not a
    reviewed built-in tool.
    """
    return tool_name in APPROVAL_REQUIRED_TOOLS or tool_name.startswith("mcp__")

# call_id -> Future[bool], resolved by POST /v1/agent/approve.
# A tool call genuinely pauses server-side execution until this resolves —
# the client can no longer just cosmetically delay showing the result after
# the command has already run.
_pending_approvals: Dict[str, "asyncio.Future[bool]"] = {}

# One shared proxy per server process — keeps conversation context between requests
_agent_proxy = None

# Track last-seen context to avoid repeating workspace/file tags on every turn.
# The LLM interprets a repeated "[Workspace: /foo]" tag as "user switched to /foo"
# every time it appears — so only announce context when it actually changes.
_last_context = {
    "workspace": None,
    "active_file": None,
    "selection_hash": None,
}


def _get_agent_proxy():
    global _agent_proxy
    if _agent_proxy is None:
        from dabba.cli.agent_proxy import AgentProxy
        _agent_proxy = AgentProxy()
        # Extension runs headless — never block on interactive approval.
        # Two separate gates exist: PermissionManager (CLI/TUI) and
        # AgentConfig.require_tool_approval (checked inside AgentLoop itself,
        # which auto-rejects shell_exec/file_write with no way to approve
        # them over this SSE endpoint) — both must be disabled or every
        # shell command and file write silently fails as "requires approval".
        _agent_proxy.permissions.set_mode("allow")
        _agent_proxy.agent_config.require_tool_approval = False
    return _agent_proxy


def _text_stream(message: str) -> StreamingResponse:
    """One-shot SSE response for a canned reply — used when a command can't proceed."""
    async def gen():
        yield f"data: {json.dumps({'type': 'text', 'content': message})}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'content': {'steps': 0}})}\n\n"
    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


def _is_likely_command(text: str) -> bool:
    """Heuristic: is this text likely a shell command, not a question/conversation?"""
    if not text or len(text) < 2:
        return False
    stripped = text.strip()
    q_starters = {"what", "why", "how", "when", "where", "who", "whom", "whose",
                  "which", "is", "are", "was", "were", "do", "does", "did",
                  "can", "could", "will", "would", "shall", "should", "may",
                  "might", "must", "has", "have", "had", "explain", "describe",
                  "tell", "show", "define", "list", "find", "search", "summarize"}
    first_word = stripped.split()[0].lower().rstrip("?,.;:!")
    if first_word in q_starters:
        return False
    import shutil
    common_commands = {
        "ls", "df", "du", "ps", "top", "htop", "who", "whoami", "pwd", "id",
        "uname", "date", "cal", "clear", "env", "printenv", "which", "whereis",
        "type", "time", "sleep", "yes", "seq", "shuf", "sort", "uniq", "wc",
        "head", "tail", "cat", "tac", "rev", "cut", "tr", "fmt", "pr", "fold",
        "nl", "od", "base64", "cksum", "sum", "md5sum", "sha1sum", "sha256sum",
        "git", "curl", "wget", "ssh", "scp", "rsync", "tar", "gzip", "gunzip",
        "zip", "unzip", "make", "cmake", "ninja", "meson", "npm", "yarn",
        "pnpm", "pip", "pip3", "cargo", "go", "rustc", "gcc", "g++", "clang",
        "clang++", "python", "python3", "node", "deno", "bun", "ruby", "perl",
        "php", "swift", "kotlin", "docker", "podman", "kubectl", "helm",
        "terraform", "ansible", "vagrant", "chmod", "chown", "cp", "mv", "rm",
        "mkdir", "rmdir", "touch", "ln", "mount", "umount", "dd", "find",
        "locate", "grep", "egrep", "fgrep", "awk", "sed", "xargs", "tee",
        "echo", "printf", "read", "test", "expr", "let", "set", "export",
        "source", ".", "exec", "eval", "trap", "kill", "pkill", "killall",
        "nohup", "disown", "fg", "bg", "jobs", "screen", "tmux", "sudo",
        "doas", "su", "passwd", "useradd", "usermod", "groupadd", "systemctl",
        "journalctl", "service", "iptables", "ufw", "ping", "traceroute",
        "nslookup", "dig", "host", "netstat", "ss", "ip", "ifconfig",
        "nmcli", "nmtui", "iwctl", "bluetoothctl", "alsamixer", "pactl",
        "xrandr", "xset", "xinput", "xdg-open", "open",
    }
    tokens = stripped.split()
    first = tokens[0]
    first_lower = first.lower()
    if first_lower in common_commands:
        return True
    if first_lower == "man" and len(tokens) >= 2:
        return True
    if len(tokens) > 1 and any(t.startswith("-") for t in tokens[1:]):
        return True
    if any(op in stripped for op in ["|", ">", "<", "&", ";", "&&", "||", "$("]):
        return True
    if first.startswith(("./", "/", "~/")):
        return True
    if shutil.which(first_lower):
        return True
    return False


def _exec_shell_response(command: str) -> StreamingResponse:
    """Execute a shell command and return output as SSE."""
    async def gen():
        try:
            cmd_label = f"$ {command}"
            yield f"data: {json.dumps({'type': 'text', 'content': '```bash' + chr(10) + cmd_label + chr(10) + '```'})}\n\n"
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=30
            )
            buf = ""
            if result.stdout:
                buf += result.stdout
            if result.stderr:
                buf += result.stderr
            if not buf.strip():
                buf = f"(exit code {result.returncode})"
            elif result.returncode != 0:
                buf += chr(10) + chr(10) + f"*exit code: {result.returncode}*"
            yield f"data: {json.dumps({'type': 'text', 'content': '```bash' + chr(10) + buf.strip() + chr(10) + '```'})}\n\n"
        except subprocess.TimeoutExpired:
            yield f"data: {json.dumps({'type': 'text', 'content': chr(9166) + ' Command timed out (30s limit)'})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'text', 'content': chr(10060) + ' Command failed: ' + str(exc)})}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'content': {'steps': 0}})}\n\n"
    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


def _build_prompt(req: AgentRequest) -> str:
    """
    Build the user message sent to the agent loop.

    IMPORTANT: workspace and file context are NOT injected here on every turn
    — the system prompt already has the workspace root and directory tree.
    Repeating '[Workspace: ...]' on every turn makes the LLM think the user
    keeps switching workspaces, causing useless "it seems like you switched
    workspace" responses. Only announce context when it actually changes.
    """
    global _last_context
    parts = []

    memory_block = _memory_manager.get_context_string()
    if memory_block:
        parts.append(memory_block)

    # Only announce workspace/file changes, not the same context every turn
    if req.workspace and req.workspace != _last_context["workspace"]:
        parts.append(f"[Workspace: {req.workspace}]")
        _last_context["workspace"] = req.workspace

    if req.active_file and req.active_file != _last_context["active_file"]:
        prev = _last_context["active_file"]
        if prev is not None:
            parts.append(f"[Active file changed: {req.active_file}]")
        else:
            parts.append(f"[Active file: {req.active_file}]")
        _last_context["active_file"] = req.active_file

    # Selection is user-driven per-turn — always inject when present
    if req.selection:
        parts.append(f"[Selected code:]\n```\n{req.selection}\n```")

    parts.append(req.message)
    return "\n".join(parts)


# Code-action commands rewrite the message into a real prompt and fall through
# to the normal agent/LLM stream, instead of returning a canned response.
_CODE_ACTION_PROMPTS = {
    "/explain": "Explain what this code does, step by step, in plain language:",
    "/fix": "Find and fix any bugs in this code. Show the corrected code and explain what was wrong:",
    "/test": "Write thorough unit tests for this code:",
    "/review": "Review this code for bugs, style issues, and potential improvements:",
}


def create_agent_router() -> APIRouter:
    router = APIRouter()

    @router.post("/v1/agent")
    async def agent_stream(req: AgentRequest, request: Request):
        proxy = _get_agent_proxy()

        if req.reset:
            proxy.reset()

        # Per-request model/effort override
        if req.model:
            proxy.cli_config.default_model = req.model
        if req.effort:
            proxy.cli_config.effort = req.effort

        msg_stripped = req.message.strip()
        first_word = msg_stripped.split()[0].lower() if msg_stripped else ""

        # /explain, /fix — operate on the current editor selection
        if first_word in ("/explain", "/fix"):
            if not req.selection:
                return _text_stream("Select some code in the editor first, then run " + first_word + ".")
            req.message = f"{_CODE_ACTION_PROMPTS[first_word]}\n\n```\n{req.selection}\n```"
            msg_stripped = ""  # no longer a slash command — falls through to the agent below

        # /test, /review — operate on the whole active file (read server-side, same machine as VSCode)
        elif first_word in ("/test", "/review"):
            if not req.active_file:
                return _text_stream("Open a file in the editor first, then run " + first_word + ".")
            try:
                with open(req.active_file, "r", errors="replace") as f:
                    content = f.read(20000)
            except Exception as exc:
                return _text_stream(f"Could not read {req.active_file}: {exc}")
            req.message = f"{_CODE_ACTION_PROMPTS[first_word]} `{req.active_file}`:\n\n```\n{content}\n```"
            msg_stripped = ""

        # Check for remaining slash commands
        if msg_stripped.startswith('/'):
            parts = msg_stripped.split()
            cmd = parts[0].lower()
            args = parts[1:]

            async def command_event_gen():
                try:
                    if cmd in ('/clear', '/new', '/new-session', '/reset'):
                        proxy.reset()
                        yield f"data: {json.dumps({'type': 'text', 'content': '🧹 Conversation cleared and session reset successfully.'})}\n\n"
                    elif cmd == '/tools':
                        try:
                            tools = proxy._get_registry().list_tools()
                            lines = ["🔧 **Available Tools:**\n"]
                            for t in tools:
                                lines.append(f"- `{t.name}` — {t.description[:80]}")
                            msg = "\n".join(lines) if tools else "No tools registered."
                        except Exception as exc:
                            msg = f"Could not list tools: {exc}"
                        yield f"data: {json.dumps({'type': 'text', 'content': msg})}\n\n"
                    elif cmd == '/mcp':
                        try:
                            proxy._get_registry()  # ensures connect() has run at least once
                            status = proxy.mcp_manager.status()
                            if not status["servers"]:
                                from dabba.agent.mcp_client import MCP_CONFIG_PATH
                                msg = (
                                    f"No MCP servers connected. Configure servers in `{MCP_CONFIG_PATH}` "
                                    '(e.g. `{"mcpServers": {"name": {"command": "npx", "args": [...]}}}`) '
                                    "and restart the Dabba server."
                                )
                            else:
                                lines = ["🔌 **Connected MCP Servers:**\n"]
                                for server, tools in status["tools_by_server"].items():
                                    lines.append(f"- **{server}** ({len(tools)} tools): {', '.join(tools)}")
                                msg = "\n".join(lines)
                        except Exception as exc:
                            msg = f"Could not get MCP status: {exc}"
                        yield f"data: {json.dumps({'type': 'text', 'content': msg})}\n\n"
                    elif cmd == '/plan':
                        goal = " ".join(args) or req.message
                        loop_agent = proxy._ensure_agent_loop(req.workspace)
                        tool_dicts = [
                            {"name": t.name, "description": t.description, "parameters": t.parameters_to_json_schema()}
                            for t in proxy._get_registry().list_tools()
                        ]
                        try:
                            plan = loop_agent.planner.create_plan(goal, tool_dicts)
                            steps = [s.description or s.tool_name for s in plan.steps] or ["No steps — try phrasing the goal differently."]
                        except Exception as exc:
                            steps = [f"Planning failed: {exc}"]
                        yield f"data: {json.dumps({'type': 'plan', 'content': steps})}\n\n"
                    elif cmd == '/compact':
                        loop_agent = proxy._ensure_agent_loop(req.workspace)
                        cm = loop_agent.context_manager
                        before = cm.entry_count
                        before_tokens = cm.total_tokens
                        try:
                            if hasattr(cm, "compact"):
                                cm.compact()
                            elif hasattr(cm, "truncate"):
                                cm.truncate()
                            else:
                                # Fallback: keep system prompt + last 6 entries, recompute token total
                                cm._entries = cm._entries[-6:]
                                cm._total_tokens = cm._system_token_count + sum(
                                    e.token_count for e in cm._entries
                                )
                            msg = (
                                "📦 **Context compacted**\n"
                                f"- Entries: {before} → {cm.entry_count}\n"
                                f"- Tokens: ~{before_tokens} → ~{cm.total_tokens}"
                            )
                        except Exception as exc:
                            msg = f"Compact failed: {exc}"
                        yield f"data: {json.dumps({'type': 'text', 'content': msg})}\n\n"
                    elif cmd == '/diff':
                        msg = "⇄ Use the **View Diff** button under a file-edit tool result to open a diff. `/diff` with no active edit has nothing to show."
                        yield f"data: {json.dumps({'type': 'text', 'content': msg})}\n\n"
                    elif cmd == '/usage':
                        metrics = proxy._get_metrics()
                        steps = metrics.get("step_count", 0)
                        tool_calls = metrics.get("tool_call_count", 0)
                        total_tokens = metrics.get("context_total_tokens", 0)
                        usage_ratio = metrics.get("context_usage_ratio", 0.0)
                        msg = (
                            "📊 **Current Session Usage:**\n"
                            f"- **Steps Taken:** {steps}\n"
                            f"- **Tool Calls:** {tool_calls}\n"
                            f"- **Total Tokens:** ~{total_tokens} ({usage_ratio*100:.1f}% of context)\n"
                            f"- **Active Model:** `{proxy.cli_config.default_model}`\n"
                            f"- **Reasoning Effort:** `{getattr(proxy.cli_config, 'effort', 'medium')}`"
                        )
                        yield f"data: {json.dumps({'type': 'text', 'content': msg})}\n\n"
                    elif cmd == '/effort':
                        tiers = ("low", "medium", "high", "xhigh", "max")
                        if args and args[0].lower() in tiers:
                            proxy.cli_config.effort = args[0].lower()
                            proxy.cli_config.save()
                            msg = f"⚙ Reasoning effort → `{args[0].lower()}`"
                        else:
                            current = getattr(proxy.cli_config, 'effort', 'medium')
                            msg = f"💡 Current effort: `{current}`. Usage: `/effort <low|medium|high|xhigh|max>`"
                        yield f"data: {json.dumps({'type': 'text', 'content': msg})}\n\n"
                    elif cmd == '/keys':
                        if args and args[0] == "set" and len(args) >= 3:
                            provider = args[1].lower()
                            key_value = args[2]
                            valid = {"anthropic", "openai", "google", "nvidia", "huggingface"}
                            if provider not in valid:
                                msg = f"❌ Unknown provider: `{provider}`. Valid: {', '.join(sorted(valid))}"
                            else:
                                api_keys = getattr(proxy.cli_config, "api_keys", {})
                                if api_keys is None:
                                    api_keys = {}
                                api_keys[provider] = key_value
                                proxy.cli_config.api_keys = api_keys
                                proxy.cli_config.save()
                                # Reset provider registry so the new key takes effect
                                if hasattr(proxy, "_provider_registry"):
                                    proxy._provider_registry = None
                                msg = f"✅ API key saved for **{provider}**"
                            yield f"data: {json.dumps({'type': 'text', 'content': msg})}\n\n"
                        elif args and args[0] == "delete" and len(args) >= 2:
                            provider = args[1].lower()
                            api_keys = getattr(proxy.cli_config, "api_keys", {}) or {}
                            if provider in api_keys:
                                del api_keys[provider]
                                proxy.cli_config.api_keys = api_keys
                                proxy.cli_config.save()
                                msg = f"🗑 API key removed for **{provider}**"
                            else:
                                msg = f"⚠ No key set for **{provider}**"
                            yield f"data: {json.dumps({'type': 'text', 'content': msg})}\n\n"
                        else:
                            keys = getattr(proxy.cli_config, "api_keys", {}) or {}
                            providers = ["anthropic", "openai", "google", "nvidia", "huggingface"]
                            lines = ["🔑 **API Key Status:**\n"]
                            for p in providers:
                                status = "✅ set" if keys.get(p) else "⬜ not set"
                                lines.append(f"- **{p}**: {status}")
                            lines.append("\nUsage: `/keys set <provider> <key>` or `/keys delete <provider>`")
                            yield f"data: {json.dumps({'type': 'text', 'content': chr(10).join(lines)})}\n\n"
                    elif cmd == '/git':
                        import subprocess
                        cwd = req.workspace or "."
                        subcmd = args[0].lower() if args else "status"
                        git_cmds = {
                            "status": ["git", "status", "--short"],
                            "diff":   ["git", "diff", "--stat"],
                            "log":    ["git", "log", "--oneline", "-10"],
                            "branch": ["git", "branch"],
                        }
                        if subcmd == "commit":
                            commit_msg = " ".join(args[1:]) or "update"
                            git_cmd = ["git", "commit", "-am", commit_msg]
                        else:
                            git_cmd = git_cmds.get(subcmd)
                        if not git_cmd:
                            msg = f"Unknown git subcommand: `{subcmd}`. Try: status, diff, log, branch, commit \"msg\""
                        else:
                            try:
                                result = subprocess.run(git_cmd, cwd=cwd, capture_output=True, text=True, timeout=15)
                                output = (result.stdout + result.stderr).strip() or "(no output)"
                                msg = f"```\n$ git {subcmd}\n{output}\n```"
                            except Exception as exc:
                                msg = f"git command failed: {exc}"
                        yield f"data: {json.dumps({'type': 'text', 'content': msg})}\n\n"
                    elif cmd == '/memory':
                        loop_agent = proxy._ensure_agent_loop(req.workspace)
                        history_len = loop_agent.context_manager.entry_count
                        msg = (
                            "🧠 **Session Memory:**\n"
                            f"- **Active Messages in Context:** {history_len}\n"
                            f"- **System Prompt Present:** Yes\n"
                        )
                        import os
                        if req.workspace and os.path.exists(os.path.join(req.workspace, 'attachments')):
                            files = os.listdir(os.path.join(req.workspace, 'attachments'))
                            if files:
                                msg += f"- **Attached Files:** {', '.join(files)}\n"
                        yield f"data: {json.dumps({'type': 'text', 'content': msg})}\n\n"
                    elif cmd == '/search':
                        query = " ".join(args)
                        if not query:
                            yield f"data: {json.dumps({'type': 'text', 'content': '💡 Usage: `/search <query>`'})}\n\n"
                        else:
                            yield f"data: {json.dumps({'type': 'text', 'content': f'🔍 Searching for: **{query}**...'})}\n\n"
                            try:
                                from dabba.tools.web_tools import search_web, WebToolError
                                results = search_web(query, num_results=6)
                                lines = [f"🔍 **Web Search Results for:** `{query}`\n"]
                                for i, r in enumerate(results, 1):
                                    lines.append(f"**{i}. [{r['title']}]({r['url']})**")
                                    if r.get('snippet'):
                                        lines.append(f"   {r['snippet']}")
                                msg = "\n".join(lines)
                                # Inject results into agent context for follow-up questions
                                loop_agent = proxy._ensure_agent_loop(req.workspace)
                                loop_agent.context_manager.add_entry(
                                    role="assistant",
                                    content=f"[Web search results for '{query}']\n{msg}",
                                    metadata={"type": "web_search"}
                                )
                            except Exception as exc:
                                msg = f"❌ Search failed: {exc}"
                            yield f"data: {json.dumps({'type': 'text', 'content': msg})}\n\n"
                    elif cmd == '/read':
                        url = args[0] if args else ""
                        if not url or not url.startswith("http"):
                            yield f"data: {json.dumps({'type': 'text', 'content': '💡 Usage: `/read <url>`'})}\n\n"
                        else:
                            yield f"data: {json.dumps({'type': 'text', 'content': f'🌐 Fetching: **{url}**...'})}\n\n"
                            try:
                                from dabba.tools.web_tools import fetch_url, WebToolError
                                result = fetch_url(url)
                                content = result.get("text") or result.get("content", "")
                                title = result.get("title") or url
                                truncated = str(content)[:8000]
                                msg = f"🌐 **{title}**\n\nURL: {url}\n\n---\n\n{truncated}"
                                if len(str(content)) > 8000:
                                    msg += f"\n\n*(truncated — {len(str(content))} total chars)*"
                                # Inject URL content into agent context
                                loop_agent = proxy._ensure_agent_loop(req.workspace)
                                loop_agent.context_manager.add_entry(
                                    role="assistant",
                                    content=f"[URL content fetched from {url}]\n{truncated}",
                                    metadata={"type": "url_fetch"}
                                )
                            except Exception as exc:
                                msg = f"❌ Could not fetch URL: {exc}"
                            yield f"data: {json.dumps({'type': 'text', 'content': msg})}\n\n"
                    elif cmd == '/find':
                        keyword = " ".join(args)
                        if not keyword:
                            yield f"data: {json.dumps({'type': 'text', 'content': '💡 Usage: `/find <keyword or phrase>`'})}\n\n"
                        elif not req.workspace:
                            yield f"data: {json.dumps({'type': 'text', 'content': '❌ No workspace open. Open a folder in VS Code first.'})}\n\n"
                        else:
                            try:
                                result = subprocess.run(
                                    ["grep", "-rn", "--include=*.py", "--include=*.ts",
                                     "--include=*.js", "--include=*.go", "--include=*.java",
                                     "--include=*.rs", "--include=*.cpp", "--include=*.c",
                                     "--include=*.md", "-l", keyword, req.workspace],
                                    capture_output=True, text=True, timeout=15
                                )
                                files_with_matches = [f for f in result.stdout.strip().split("\n") if f]
                                if not files_with_matches:
                                    msg = f"No matches found for `{keyword}` in workspace."
                                else:
                                    # Get line snippets from top 8 files
                                    lines = [f"🔍 **Found `{keyword}` in {len(files_with_matches)} file(s):**\n"]
                                    for fpath in files_with_matches[:8]:
                                        rel = fpath.replace(req.workspace, "").lstrip("/")
                                        grep2 = subprocess.run(
                                            ["grep", "-n", keyword, fpath],
                                            capture_output=True, text=True, timeout=5
                                        )
                                        for line in grep2.stdout.strip().split("\n")[:3]:
                                            if ":" in line:
                                                lineno, snippet = line.split(":", 1)
                                                lines.append(f"📄 `{rel}:{lineno}` — `{snippet.strip()[:100]}`")
                                    if len(files_with_matches) > 8:
                                        lines.append(f"\n…and {len(files_with_matches) - 8} more files")
                                    msg = "\n".join(lines)
                            except subprocess.TimeoutExpired:
                                msg = "❌ Search timed out. Try a more specific keyword."
                            except Exception as exc:
                                msg = f"❌ Search failed: {exc}"
                            yield f"data: {json.dumps({'type': 'text', 'content': msg})}\n\n"
                    elif cmd == '/remember':
                        fact = " ".join(args)
                        if not fact:
                            yield f"data: {json.dumps({'type': 'text', 'content': '💡 Usage: `/remember <fact to save>`'})}\n\n"
                        else:
                            try:
                                _memory_manager.add(fact)
                                count = len(_memory_manager)
                                plural = 'ies' if count != 1 else 'y'
                                confirm_msg = f'✅ Remembered: *{fact}*\n\n({count} total memor{plural} saved)'
                                yield f"data: {__import__('json').dumps({'type': 'text', 'content': confirm_msg})}\n\n"
                            except ValueError as e:
                                yield f"data: {json.dumps({'type': 'text', 'content': f'⚠ {e}'})}\n\n"
                    elif cmd == '/memories':
                        memories = _memory_manager.list()
                        if not memories:
                            yield f"data: {json.dumps({'type': 'text', 'content': '📭 No memories saved yet. Use `/remember <fact>` to save one.'})}\n\n"
                        else:
                            lines = [f"🧠 **Saved Memories ({len(memories)}):**\n"]
                            for i, m in enumerate(memories, 1):
                                lines.append(f"{i}. {m['fact']}")
                            lines.append("\n*Use `/forget <number>` to delete a memory.*")
                            yield f"data: {json.dumps({'type': 'text', 'content': chr(10).join(lines)})}\n\n"
                    elif cmd == '/forget':
                        arg = " ".join(args)
                        if not arg:
                            yield f"data: {json.dumps({'type': 'text', 'content': '💡 Usage: `/forget <number>` or `/forget <text>`'})}\n\n"
                        else:
                            if arg.isdigit():
                                removed = _memory_manager.remove_by_index(int(arg))
                            else:
                                removed = _memory_manager.remove_by_text(arg)
                            if removed:
                                yield f"data: {json.dumps({'type': 'text', 'content': f'🗑 Forgot: *{removed}*'})}\n\n"
                            else:
                                yield f"data: {json.dumps({'type': 'text', 'content': f'❌ Memory not found: `{arg}`. Use `/memories` to list them.'})}\n\n"
                    elif cmd == '/model':
                        if args:
                            new_model = args[0]
                            proxy.cli_config.default_model = new_model
                            proxy.cli_config.save()
                            yield f"data: {json.dumps({'type': 'text', 'content': f'🔄 Model changed to: `{new_model}`'})}\n\n"
                        else:
                            yield f"data: {json.dumps({'type': 'text', 'content': '💡 Usage: `/model <model_id>` to switch models, or select the model chip below.'})}\n\n"
                    elif cmd == '/help':
                        help_text = (
                            "💡 **Available Slash Commands:**\n\n"
                            "**Code actions** (need a selection or open file):\n"
                            "- `/explain`: Explain the selected code.\n"
                            "- `/fix`: Fix bugs in the selected code.\n"
                            "- `/test`: Generate unit tests for the active file.\n"
                            "- `/review`: Review the active file for issues.\n\n"
                            "**Web & Search:**\n"
                            "- `/search <query>`: Search the web and inject results as context.\n"
                            "- `/read <url>`: Fetch a URL and inject its content as context.\n"
                            "- `/find <keyword>`: Search workspace files for a keyword.\n\n"
                            "**Memory:**\n"
                            "- `/remember <fact>`: Save a fact to persistent memory (survives restarts).\n"
                            "- `/memories`: View all saved memories.\n"
                            "- `/forget <number or text>`: Delete a memory.\n\n"
                            "**Session:**\n"
                            "- `/help`: Show this help message.\n"
                            "- `/clear` / `/new-session`: Clear the conversation and reset the agent.\n"
                            "- `/usage`: View token usage, steps, and active configuration.\n"
                            "- `/memory`: View active context and attached files.\n"
                            "- `/compact`: Summarize/trim the conversation to save context.\n\n"
                            "**Config:**\n"
                            "- `/model <model_id>`: Set/change the default model.\n"
                            "- `/effort <tier>`: Set reasoning effort (low/medium/high/xhigh/max).\n"
                            "- `/keys`: Show which providers have API keys set.\n\n"
                            "**Tools:**\n"
                            "- `/plan <goal>`: Ask the agent to plan steps before executing.\n"
                            "- `/diff`: How to view the last file diff.\n"
                            "- `/tools`: List all tools the agent can call.\n"
                            "- `/mcp`: List connected MCP servers and their tools.\n"
                            "- `/git <status|diff|log|branch|commit \"msg\">`: Run git commands."
                        )
                        yield f"data: {json.dumps({'type': 'text', 'content': help_text})}\n\n"
                    else:
                        # Unknown slash command — route to agent as a normal message
                        req.message = msg_stripped
                        prompt = _build_prompt(req)
                        async def route_to_agent():
                            steps = 0
                            loop_agent = proxy._ensure_agent_loop(req.workspace)
                            gen = loop_agent.stream_chat(prompt)
                            try:
                                while True:
                                    try:
                                        chunk = await gen.__anext__()
                                    except StopAsyncIteration:
                                        break
                                    if await request.is_disconnected():
                                        await gen.aclose()
                                        break
                                    yield f"data: {json.dumps(chunk)}\n\n"
                                proxy.save_session(req.workspace)
                                yield f"data: {json.dumps({'type': 'done', 'content': {'steps': steps}})}\n\n"
                            except Exception as exc:
                                proxy.save_session(req.workspace)
                                yield f"data: {json.dumps({'type': 'error', 'content': str(exc)})}\n\n"
                        async for chunk in route_to_agent():
                            yield chunk
                        return

                    yield f"data: {json.dumps({'type': 'done', 'content': {'steps': 0}})}\n\n"
                except Exception as exc:
                    yield f"data: {json.dumps({'type': 'error', 'content': str(exc)})}\n\n"

            return StreamingResponse(
                command_event_gen(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        if _is_likely_command(msg_stripped):
            return _exec_shell_response(msg_stripped)

        prompt = _build_prompt(req)

        async def event_gen():
            steps = 0
            loop_agent = proxy._ensure_agent_loop(req.workspace)
            gen = loop_agent.stream_chat(prompt)
            try:
                while True:
                    try:
                        chunk = await gen.__anext__()
                    except StopAsyncIteration:
                        break

                    if await request.is_disconnected():
                        await gen.aclose()
                        break

                    ctype = chunk.get("type", "")
                    if ctype == "tool_call":
                        steps += 1
                        content = chunk.get("content", {}) or {}
                        tool_name = content.get("name", "")
                        call_id = content.get("call_id", "")

                        yield f"data: {json.dumps(chunk)}\n\n"

                        if req.permission_mode == "ask" and _requires_approval(tool_name) and call_id:
                            # Genuinely pause here — the underlying async generator has not
                            # advanced past this yield, so AgentLoop._execute_tool_calls has
                            # NOT run yet. Nothing executes until this future resolves.
                            fut: asyncio.Future = asyncio.get_event_loop().create_future()
                            _pending_approvals[call_id] = fut
                            try:
                                approved = await asyncio.wait_for(fut, timeout=APPROVAL_TIMEOUT_SECONDS)
                            except asyncio.TimeoutError:
                                approved = False
                            finally:
                                _pending_approvals.pop(call_id, None)

                            if not approved:
                                yield f"data: {json.dumps({'type': 'tool_denied', 'content': {'call_id': call_id, 'name': tool_name}})}\n\n"
                                yield f"data: {json.dumps({'type': 'text', 'content': f'Tool call `{tool_name}` was denied — stopping this turn.'})}\n\n"
                                await gen.aclose()
                                break
                        continue  # tool_call line already yielded above

                    yield f"data: {json.dumps(chunk)}\n\n"

                proxy.save_session(req.workspace)
                yield f"data: {json.dumps({'type': 'done', 'content': {'steps': steps}})}\n\n"
            except Exception as exc:
                proxy.save_session(req.workspace)
                yield f"data: {json.dumps({'type': 'error', 'content': str(exc)})}\n\n"

        return StreamingResponse(
            event_gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @router.post("/v1/agent/reset")
    async def agent_reset():
        proxy = _get_agent_proxy()
        proxy.reset()
        return {"status": "ok"}

    @router.post("/v1/agent/approve")
    async def agent_approve(req: ApprovalRequest):
        """
        Resolve a pending tool-call approval. The matching /v1/agent request
        is genuinely blocked (its async generator hasn't advanced) until this
        arrives — a click here really does gate execution, not just display.
        """
        fut = _pending_approvals.get(req.call_id)
        if fut is None:
            return {"status": "not_found"}
        if not fut.done():
            fut.set_result(req.approved)
        return {"status": "ok"}

    @router.get("/v1/agent/models")
    async def agent_models():
        """List all available models grouped by provider — for the extension model picker."""
        proxy = _get_agent_proxy()
        registry = proxy._get_provider_registry()
        keys = getattr(proxy.cli_config, "api_keys", {}) or {}
        models = []
        for m in registry.list_all_models():
            models.append({
                "id": m.id,
                "name": m.name,
                "provider": m.provider,
                "tier": m.tier,
                "description": m.description,
                "has_key": bool(keys.get(m.provider)) or not m.requires_key,
            })
        return {
            "models": models,
            "current": proxy.cli_config.default_model,
            "effort": getattr(proxy.cli_config, "effort", "medium"),
        }

    @router.get("/v1/agent/keys")
    async def list_api_keys():
        """
        Which providers have a key configured — same status the model picker's
        "has_key" flag is derived from. Never returns the key values
        themselves, only whether one is set, for the web UI's key-management
        settings page.
        """
        proxy = _get_agent_proxy()
        keys = getattr(proxy.cli_config, "api_keys", {}) or {}
        return {
            "providers": [
                {"provider": p, "hasKey": bool(keys.get(p))}
                for p in sorted(VALID_KEY_PROVIDERS)
            ]
        }

    @router.post("/v1/agent/keys")
    async def set_api_key(req: SetApiKeyRequest):
        """
        Sets a provider API key — same effect as the CLI's `/keys set <provider> <key>`
        (see cli/session.py's _cmd_keys). Persists to cli_config.yaml and takes
        effect immediately: providers read cli_config.api_keys fresh on every
        request, no server restart needed.
        """
        provider = req.provider.strip().lower()
        if provider not in VALID_KEY_PROVIDERS:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown provider '{provider}'. Valid: {', '.join(sorted(VALID_KEY_PROVIDERS))}",
            )
        key = req.key.strip()
        if not key:
            raise HTTPException(status_code=400, detail="key cannot be empty")

        proxy = _get_agent_proxy()
        api_keys = dict(getattr(proxy.cli_config, "api_keys", None) or {})
        api_keys[provider] = key
        proxy.cli_config.api_keys = api_keys
        proxy.cli_config.save()
        return {"provider": provider, "hasKey": True}

    @router.delete("/v1/agent/keys/{provider}")
    async def delete_api_key(provider: str):
        provider = provider.strip().lower()
        proxy = _get_agent_proxy()
        api_keys = dict(getattr(proxy.cli_config, "api_keys", {}) or {})
        if provider not in api_keys:
            raise HTTPException(status_code=404, detail=f"No key set for '{provider}'")
        del api_keys[provider]
        proxy.cli_config.api_keys = api_keys
        proxy.cli_config.save()
        return {"provider": provider, "hasKey": False}

    @router.get("/v1/mcp/status")
    async def mcp_status():
        """Every server in mcp_servers.json plus its live connection state — for the extension's MCP panel."""
        proxy = _get_agent_proxy()
        proxy._get_registry()  # ensures connect() has run at least once this process
        from dabba.agent.mcp_client import load_mcp_config

        configured = load_mcp_config()
        live = proxy.mcp_manager.status()
        servers = [
            {
                "name": name,
                "command": cfg.command,
                "args": cfg.args,
                "connected": name in live["servers"],
                "tools": live["tools_by_server"].get(name, []),
            }
            for name, cfg in configured.items()
        ]
        return {"servers": servers}

    @router.post("/v1/mcp/reload")
    async def mcp_reload():
        """
        Re-read mcp_servers.json and connect any newly-added servers without
        a full process restart. Editing or removing an already-connected
        server still needs a restart — McpClientManager.connect() only adds
        new sessions, it can't tear down or reconfigure a live one.
        """
        proxy = _get_agent_proxy()
        from dabba.agent.mcp_client import load_mcp_config, register_mcp_tools

        configs = load_mcp_config()
        summary = proxy.mcp_manager.connect(configs)
        added = register_mcp_tools(proxy._get_registry(), proxy.mcp_manager)
        return {**summary, "tools_added": added}

    @router.post("/v1/mcp/servers")
    async def add_mcp_server(req: AddMcpServerRequest):
        """
        Adds a new MCP server to mcp_servers.json and connects it immediately
        (no restart needed — same connect() used by /v1/mcp/reload, which only
        ever *adds* new sessions). This is how the web UI's "Add connector"
        form and the VSCode extension's MCP panel both create servers.
        """
        from dabba.agent.mcp_client import load_mcp_config, save_mcp_config, register_mcp_tools, McpServerConfig

        name = req.name.strip()
        command = req.command.strip()
        if not name:
            raise HTTPException(status_code=400, detail="name is required")
        if not command:
            raise HTTPException(status_code=400, detail="command is required")

        configs = load_mcp_config()
        if name in configs:
            raise HTTPException(status_code=409, detail=f"A connector named '{name}' already exists")

        configs[name] = McpServerConfig(name=name, command=command, args=req.args, env=req.env)
        save_mcp_config(configs)

        proxy = _get_agent_proxy()
        summary = proxy.mcp_manager.connect(configs)
        added = register_mcp_tools(proxy._get_registry(), proxy.mcp_manager)
        return {**summary, "tools_added": added}

    @router.delete("/v1/mcp/servers/{name}")
    async def delete_mcp_server(name: str):
        """
        Removes a server from mcp_servers.json. If it was already connected
        this process, the live session keeps running until restart — matches
        the existing reload endpoint's documented limitation (connect() can
        add sessions but McpClientManager has no live disconnect path).
        """
        from dabba.agent.mcp_client import load_mcp_config, save_mcp_config

        configs = load_mcp_config()
        if name not in configs:
            raise HTTPException(status_code=404, detail=f"No connector named '{name}'")

        del configs[name]
        save_mcp_config(configs)
        return {"deleted": name}

    return router
