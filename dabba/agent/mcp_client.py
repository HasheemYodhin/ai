"""
Real Model Context Protocol (MCP) client for the dabba agent.

`dabba.agent.mcp_handler.McpHandler` is NOT this — it's an in-house
<tool_call> JSON parser used to drive dabba's own built-in tools, named
after MCP but never actually speaking the protocol or talking to any
external server. This module is the real thing: it connects to
externally-configured MCP servers (stdio subprocesses, e.g.
`npx @modelcontextprotocol/server-filesystem`) using the official `mcp`
SDK, and exposes each server's tools through the same ToolRegistry that
file_write/shell_exec/etc. are registered on.

Connections are long-lived — an MCP session is a JSON-RPC conversation
over a subprocess's stdin/stdout, so it must stay open for the process's
lifetime rather than being reconnected per call. dabba's callers run a
mix of short-lived `asyncio.new_event_loop()` wrappers (CLI) and one
long-lived uvicorn loop (API server), so instead of binding connections
to whichever loop happens to be active when they're created, this runs
its own dedicated background thread with a persistent event loop and
exposes plain synchronous methods (`connect`, `call_tool`) that bridge
into it via `asyncio.run_coroutine_threadsafe`. That keeps every existing
call site (which expects `ToolRegistry.register`/tool handlers to be
ordinary sync-callable-or-awaitable) unchanged.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from dabba.agent.tool_schema import ToolDefinition, ToolParameter
from dabba.utils.logging import get_logger
from dabba.utils.paths import get_dabba_config_dir

logger = get_logger("dabba.agent.mcp_client")

# Same on-disk location convention as dabba/cli/permissions.py's PERMISSIONS_FILE.
MCP_CONFIG_PATH = get_dabba_config_dir() / "mcp_servers.json"
MCP_CALL_TIMEOUT_SECONDS = 60
MCP_CONNECT_TIMEOUT_SECONDS = 30


@dataclass
class McpServerConfig:
    """One entry from mcp_servers.json — a stdio-launched MCP server."""

    name: str
    command: str
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)


def load_mcp_config(path: Optional[Path] = None) -> Dict[str, McpServerConfig]:
    """
    Load MCP server definitions from a Claude-Desktop-style config file:

        {"mcpServers": {"filesystem": {"command": "npx",
                                        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                                        "env": {}}}}

    Args:
        path: Override config path (defaults to ~/.config/dabba/mcp_servers.json).

    Returns:
        Dict of server name -> McpServerConfig. Empty (not an error) if the
        file doesn't exist — MCP servers are opt-in.
    """
    cfg_path = path or MCP_CONFIG_PATH
    if not cfg_path.exists():
        return {}
    try:
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("Failed to read MCP config %s: %s", cfg_path, exc)
        return {}

    servers: Dict[str, McpServerConfig] = {}
    for name, spec in (raw.get("mcpServers") or {}).items():
        if not isinstance(spec, dict) or not spec.get("command"):
            logger.warning("Skipping MCP server '%s': missing 'command'", name)
            continue
        servers[name] = McpServerConfig(
            name=name,
            command=spec["command"],
            args=list(spec.get("args", [])),
            env=dict(spec.get("env", {})),
        )
    return servers


def save_mcp_config(servers: Dict[str, McpServerConfig], path: Optional[Path] = None) -> None:
    """
    Write server definitions back to mcp_servers.json in the same shape
    load_mcp_config() reads. Shared by every place that lets a user edit
    the config (currently the TUI's /mcp modal and the VSCode extension,
    which writes the file directly in Node rather than through this
    function — keep the JSON shape in sync if either side changes it).

    Args:
        servers: The full set of server definitions to write (not a diff —
            callers load, mutate, then pass the whole dict back).
        path: Override config path (defaults to ~/.config/dabba/mcp_servers.json).
    """
    cfg_path = path or MCP_CONFIG_PATH
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "mcpServers": {
            name: {"command": cfg.command, "args": cfg.args, **({"env": cfg.env} if cfg.env else {})}
            for name, cfg in servers.items()
        }
    }
    cfg_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _json_schema_to_parameters(schema: Optional[Dict[str, Any]]) -> List[ToolParameter]:
    """Convert an MCP tool's JSON Schema inputSchema into dabba ToolParameters."""
    schema = schema or {}
    props = schema.get("properties", {}) or {}
    required = set(schema.get("required", []) or [])
    params: List[ToolParameter] = []
    for pname, pinfo in props.items():
        pinfo = pinfo or {}
        params.append(
            ToolParameter(
                name=pname,
                type=pinfo.get("type", "string"),
                description=pinfo.get("description", ""),
                required=pname in required,
                default=pinfo.get("default"),
            )
        )
    return params


class McpClientManager:
    """
    Owns connections to every configured MCP server for the life of the
    process, and exposes their tools as callables a ToolRegistry can
    register exactly like a built-in tool.

    Tool names are namespaced as "mcp__<server>__<tool>" so two servers
    (or a server and a built-in tool) exposing the same tool name can't
    collide in the registry.
    """

    def __init__(self) -> None:
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._queue: Optional[asyncio.Queue] = None  # created on, and only touched from, the bg loop
        self._supervisor_started = False
        self._sessions: Dict[str, Any] = {}  # server name -> ClientSession
        self._connected_tools: Dict[str, Dict[str, Any]] = {}  # namespaced name -> info
        self._lock = threading.Lock()

    # -- background loop + supervisor task --------------------------------
    #
    # anyio (which the mcp SDK's stdio_client/ClientSession are built on)
    # ties its cancel scopes to the asyncio Task that entered them. Every
    # `asyncio.run_coroutine_threadsafe(coro, loop)` call schedules `coro`
    # as a brand-new Task — so connecting in one call and closing in
    # another, even on the same loop, trips anyio's "exit cancel scope in a
    # different task than it was entered in" error and skips real cleanup.
    # The fix is a single long-lived supervisor task that owns the
    # AsyncExitStack for the manager's whole life; connect/call requests
    # are relayed into it over a queue instead of being scheduled as their
    # own tasks.

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is not None:
            return self._loop
        with self._lock:
            if self._loop is not None:
                return self._loop
            ready = threading.Event()
            loop_box: Dict[str, asyncio.AbstractEventLoop] = {}

            def _run() -> None:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop_box["loop"] = loop
                ready.set()
                loop.run_forever()

            self._thread = threading.Thread(target=_run, name="dabba-mcp-loop", daemon=True)
            self._thread.start()
            ready.wait(timeout=5)
            self._loop = loop_box["loop"]
            return self._loop

    def _ensure_supervisor(self) -> asyncio.AbstractEventLoop:
        loop = self._ensure_loop()
        with self._lock:
            if self._supervisor_started:
                return loop
            self._supervisor_started = True
            init_done: "concurrent.futures.Future[None]" = concurrent.futures.Future()

            async def _start() -> None:
                self._queue = asyncio.Queue()
                init_done.set_result(None)
                await self._supervisor_loop()

            asyncio.run_coroutine_threadsafe(_start(), loop)
            init_done.result(timeout=5)
            return loop

    async def _supervisor_loop(self) -> None:
        """The one task every MCP context manager is entered and exited from."""
        from contextlib import AsyncExitStack

        exit_stack = AsyncExitStack()
        try:
            while True:
                kind, payload, result_future = await self._queue.get()
                if kind == "shutdown":
                    result_future.set_result(None)
                    break
                try:
                    if kind == "connect":
                        result = await self._do_connect(exit_stack, payload)
                    elif kind == "call":
                        result = await self._do_call(payload)
                    else:
                        raise ValueError(f"Unknown supervisor request kind: {kind}")
                    result_future.set_result(result)
                except Exception as exc:
                    result_future.set_exception(exc)
        finally:
            await exit_stack.aclose()

    def _submit(self, kind: str, payload: Any) -> "concurrent.futures.Future[Any]":
        loop = self._ensure_supervisor()
        result_future: "concurrent.futures.Future[Any]" = concurrent.futures.Future()

        def _enqueue() -> None:
            self._queue.put_nowait((kind, payload, result_future))

        loop.call_soon_threadsafe(_enqueue)
        return result_future

    # -- connecting --------------------------------------------------------

    def connect(self, configs: Optional[Dict[str, McpServerConfig]] = None) -> Dict[str, Any]:
        """
        Connect to every configured MCP server not already connected.

        Safe to call repeatedly (e.g. once per _get_registry() call) —
        already-connected servers are skipped rather than reconnected.

        Returns:
            {"connected": [server names], "failed": {server name: reason}}
        """
        configs = configs if configs is not None else load_mcp_config()
        if not configs:
            return {"connected": [], "failed": {}}

        fut = self._submit("connect", configs)
        try:
            return fut.result(timeout=MCP_CONNECT_TIMEOUT_SECONDS)
        except Exception as exc:
            logger.error("MCP connect failed: %s", exc)
            return {"connected": [], "failed": {n: str(exc) for n in configs if n not in self._sessions}}

    async def _do_connect(self, exit_stack, configs: Dict[str, McpServerConfig]) -> Dict[str, Any]:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        connected: List[str] = []
        failed: Dict[str, str] = {}

        for name, cfg in configs.items():
            if name in self._sessions:
                connected.append(name)
                continue
            try:
                params = StdioServerParameters(
                    command=cfg.command, args=cfg.args, env=cfg.env or None
                )
                read, write = await exit_stack.enter_async_context(stdio_client(params))
                session = await exit_stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                tools_result = await session.list_tools()

                self._sessions[name] = session
                for tool in tools_result.tools:
                    namespaced = f"mcp__{name}__{tool.name}"
                    self._connected_tools[namespaced] = {
                        "server": name,
                        "tool": tool.name,
                        "description": tool.description or "",
                        "input_schema": tool.inputSchema or {},
                    }
                connected.append(name)
                logger.info("Connected MCP server '%s' (%d tools)", name, len(tools_result.tools))
            except Exception as exc:
                failed[name] = str(exc)
                logger.error("Failed to connect MCP server '%s': %s", name, exc)

        return {"connected": connected, "failed": failed}

    # -- calling tools -----------------------------------------------------

    def call_tool(self, namespaced_name: str, arguments: Dict[str, Any]) -> Any:
        """
        Execute one MCP tool call and block until the result comes back.

        Args:
            namespaced_name: The "mcp__<server>__<tool>" name this manager
                registered the tool under.
            arguments: Tool arguments, already validated against the
                registered ToolDefinition's parameters.

        Returns:
            The tool's output, flattened to text (or the raw content list
            if it isn't plain text).

        Raises:
            ValueError: Unknown tool name.
            RuntimeError: Server not connected, or the MCP call itself failed.
        """
        if namespaced_name not in self._connected_tools:
            raise ValueError(f"Unknown MCP tool: '{namespaced_name}'")
        fut = self._submit("call", (namespaced_name, arguments))
        return fut.result(timeout=MCP_CALL_TIMEOUT_SECONDS)

    async def _do_call(self, payload) -> Any:
        namespaced_name, arguments = payload
        info = self._connected_tools.get(namespaced_name)
        if info is None:
            raise ValueError(f"Unknown MCP tool: '{namespaced_name}'")
        session = self._sessions.get(info["server"])
        if session is None:
            raise RuntimeError(f"MCP server '{info['server']}' is not connected")
        result = await session.call_tool(info["tool"], arguments)
        return self._format_call_result(result)

    @staticmethod
    def _format_call_result(result: Any) -> Any:
        """Flatten an MCP CallToolResult's content blocks into text dabba's tool pipeline expects."""
        if getattr(result, "isError", False):
            texts = [getattr(c, "text", str(c)) for c in getattr(result, "content", [])]
            raise RuntimeError("; ".join(t for t in texts if t) or "MCP tool call failed")
        content = getattr(result, "content", None)
        if not content:
            return ""
        parts = [getattr(block, "text", None) or str(block) for block in content]
        return parts[0] if len(parts) == 1 else "\n".join(parts)

    # -- introspection -------------------------------------------------------

    def list_tools(self) -> Dict[str, Dict[str, Any]]:
        """Namespaced tool name -> {server, tool, description, input_schema}."""
        return dict(self._connected_tools)

    def status(self) -> Dict[str, Any]:
        """Summary for display in /mcp — connected servers and their tool counts."""
        by_server: Dict[str, List[str]] = {}
        for info in self._connected_tools.values():
            by_server.setdefault(info["server"], []).append(info["tool"])
        return {"servers": list(self._sessions.keys()), "tools_by_server": by_server}

    def close(self) -> None:
        """Tear down every server connection. Best-effort — used at process shutdown."""
        if self._loop is None:
            return
        if self._supervisor_started:
            fut = self._submit("shutdown", None)
            try:
                fut.result(timeout=10)
            except Exception as exc:
                logger.warning("Error closing MCP connections: %s", exc)
        self._loop.call_soon_threadsafe(self._loop.stop)


def register_mcp_tools(registry, manager: McpClientManager) -> int:
    """
    Register every tool the manager has discovered so far into a ToolRegistry.

    Args:
        registry: The ToolRegistry to register into (same one file_write etc. use).
        manager: A McpClientManager that has already had connect() called.

    Returns:
        Number of tools registered.
    """
    count = 0
    for namespaced_name, info in manager.list_tools().items():
        if namespaced_name in registry.tools:
            continue  # already registered from a prior _get_registry() call

        def _make_handler(bound_name: str):
            def _handler(**kwargs: Any) -> Any:
                return manager.call_tool(bound_name, kwargs)
            return _handler

        registry.register(
            ToolDefinition(
                name=namespaced_name,
                description=f"[MCP:{info['server']}] {info['description']}",
                parameters=_json_schema_to_parameters(info.get("input_schema")),
                handler=_make_handler(namespaced_name),
                handler_sync=True,
                category="mcp",
            )
        )
        count += 1
    return count
