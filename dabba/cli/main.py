"""
CLI entry point for the dabba terminal agent.

Provides the `dabba` command with subcommands for interactive chat,
one-shot execution, session management, and configuration.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, Dict, List, Optional

from dabba import __version__
from dabba.cli.config import CliConfig


def _get_logger():
    """Lazy logger to avoid importing torch through dabba.utils."""
    from dabba.utils.logging import get_logger
    return get_logger("dabba.cli.main")


def _setup_logger(level: str = "info"):
    """Lazy logger setup."""
    from dabba.utils.logging import setup_logger
    setup_logger(level=level)


def build_parser() -> argparse.ArgumentParser:
    """
    Build the argument parser for the dabba CLI.

    Returns:
        Configured ArgumentParser instance.
    """
    parser = argparse.ArgumentParser(
        prog="dabba",
        description="Dabba CLI Agent — AI-powered terminal assistant",
        epilog="See 'dabba <command> --help' for more information.",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"dabba {__version__}",
        help="Show version and exit.",
    )

    parser.add_argument(
        "--endpoint",
        type=str,
        default=None,
        help="API endpoint URL (overrides config).",
    )

    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Model name (overrides config).",
    )

    parser.add_argument(
        "--no-stream",
        action="store_true",
        help="Disable streaming output.",
    )

    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colored output.",
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging.",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        title="Commands",
        description="Available subcommands",
        help="Use 'dabba <command> --help' for details.",
    )

    _add_chat_parser(subparsers)
    _add_run_parser(subparsers)
    _add_session_parser(subparsers)
    _add_config_parser(subparsers)

    return parser


def _add_chat_parser(subparsers: Any) -> None:
    """Add the 'chat' subcommand parser."""
    chat_parser = subparsers.add_parser(
        "chat",
        aliases=["c", "interactive"],
        help="Start an interactive chat session.",
        description="Start an interactive multi-turn conversation with the dabba agent.",
    )
    chat_parser.add_argument(
        "--resume",
        type=str,
        metavar="PATH",
        help="Resume a previous session from a history file.",
    )
    chat_parser.add_argument(
        "--no-watch",
        action="store_true",
        help="Disable file watching.",
    )


def _add_run_parser(subparsers: Any) -> None:
    """Add the 'run' subcommand parser."""
    run_parser = subparsers.add_parser(
        "run",
        aliases=["r", "exec", "one-shot"],
        help="Execute a single prompt.",
        description="Execute a single prompt and print the response (one-shot mode).",
    )
    run_parser.add_argument(
        "prompt",
        type=str,
        nargs="?",
        help="The prompt to execute. If omitted, reads from stdin.",
    )
    run_parser.add_argument(
        "--file",
        "-f",
        type=str,
        metavar="PATH",
        help="Read prompt from a file.",
    )


def _add_session_parser(subparsers: Any) -> None:
    """Add the 'session' subcommand parser."""
    session_parser = subparsers.add_parser(
        "session",
        aliases=["s"],
        help="Manage sessions.",
        description="List, resume, or manage previous sessions.",
    )
    session_parser.add_argument(
        "--resume",
        type=str,
        metavar="PATH",
        help="Resume a session from a history file.",
    )
    session_parser.add_argument(
        "--list",
        action="store_true",
        help="List available saved sessions.",
    )


def _add_config_parser(subparsers: Any) -> None:
    """Add the 'config' subcommand parser."""
    config_parser = subparsers.add_parser(
        "config",
        aliases=["cfg"],
        help="Manage configuration.",
        description="View or modify dabba CLI configuration.",
    )
    config_parser.add_argument(
        "--set",
        type=str,
        metavar="KEY=VALUE",
        help="Set a configuration value (e.g., --set temperature=0.8).",
    )
    config_parser.add_argument(
        "--get",
        type=str,
        metavar="KEY",
        help="Get a configuration value.",
    )
    config_parser.add_argument(
        "--show",
        action="store_true",
        help="Show all configuration values.",
    )
    config_parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset configuration to defaults.",
    )


def cmd_chat(args: argparse.Namespace) -> int:
    """
    Handle the 'chat' subcommand.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code (0 on success).
    """
    from dabba.cli.agent_proxy import AgentProxy
    from dabba.cli.session import InteractiveSession

    config = _build_config(args)
    output = _build_output(args, config)
    permissions = _build_permissions(config)

    if args.no_watch:
        config.watch_files = False

    agent = AgentProxy(
        cli_config=config,
        output=output,
        permissions=permissions,
    )

    session = InteractiveSession(
        agent=agent,
        output=output,
        config=config,
        permissions=permissions,
        resume_path=args.resume,
    )
    session.start()
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """
    Handle the 'run' subcommand.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code (0 on success).
    """
    from dabba.cli.agent_proxy import AgentProxy

    prompt = _resolve_prompt(args)
    if not prompt:
        print("Error: No prompt provided. Use 'dabba run \"your prompt\"' or --file.", file=sys.stderr)
        return 1

    config = _build_config(args)
    output = _build_output(args, config)
    permissions = _build_permissions(config)

    agent = AgentProxy(
        cli_config=config,
        output=output,
        permissions=permissions,
    )

    if config.stream_output and not args.no_stream:
        response = agent.stream_sync(prompt)
    else:
        response = agent.run(prompt)
        output.assistant_message(response)

    return 0


def cmd_session(args: argparse.Namespace) -> int:
    """
    Handle the 'session' subcommand.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code (0 on success).
    """
    from dabba.cli.agent_proxy import AgentProxy
    from dabba.cli.session import InteractiveSession

    config = _build_config(args)
    output = _build_output(args, config)
    permissions = _build_permissions(config)

    if args.list:
        _list_sessions(config, output)
        return 0

    if args.resume:
        agent = AgentProxy(
            cli_config=config,
            output=output,
            permissions=permissions,
        )
        session = InteractiveSession(
            agent=agent,
            output=output,
            config=config,
            permissions=permissions,
            resume_path=args.resume,
        )
        session.start()
        return 0

    print("Use --resume <path> to resume a session, or --list to see available sessions.", file=sys.stderr)
    return 1


def cmd_config(args: argparse.Namespace) -> int:
    """
    Handle the 'config' subcommand.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code (0 on success).
    """
    config = CliConfig.load()
    output = _build_output(args, config)

    if args.reset:
        config = CliConfig()
        config.save()
        output.info("Configuration reset to defaults.")
        return 0

    if args.set:
        if "=" not in args.set:
            print("Error: Use --set key=value format.", file=sys.stderr)
            return 1
        key, value = args.set.split("=", 1)
        try:
            config.set(key.strip(), value.strip())
            output.info(f"Set {key} = {value}")
        except (KeyError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        return 0

    if args.get:
        if not hasattr(config, args.get):
            print(f"Error: Unknown key '{args.get}'", file=sys.stderr)
            return 1
        value = getattr(config, args.get)
        output.write(f"{args.get} = {value}")
        return 0

    if args.show:
        output.table(
            ["Key", "Value"],
            [[k, str(getattr(config, k))] for k in config.__dataclass_fields__],
        )
        return 0

    output.table(
        ["Key", "Value"],
        [[k, str(getattr(config, k))] for k in config.__dataclass_fields__],
    )
    return 0


def _build_config(args: argparse.Namespace) -> CliConfig:
    """
    Build a CliConfig from parsed arguments, overlaying CLI overrides.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Configured CliConfig instance.
    """
    config = CliConfig.load()

    if getattr(args, "endpoint", None):
        config.api_endpoint = args.endpoint
    elif "8000" in config.api_endpoint:
        config.api_endpoint = "http://localhost:8080"
    if getattr(args, "model", None):
        config.default_model = args.model
    if getattr(args, "no_stream", False):
        config.stream_output = False

    return config


def _build_output(args: argparse.Namespace, config: CliConfig):
    """
    Build an OutputHandler, respecting --no-color.

    Args:
        args: Parsed command-line arguments.
        config: CLI configuration.

    Returns:
        OutputHandler instance.
    """
    from dabba.cli.output_handler import OutputHandler  # noqa: F811
    return OutputHandler(
        config=config,
        no_color=getattr(args, "no_color", False),
    )


def _build_permissions(config: CliConfig):
    """
    Build a PermissionManager from configuration.

    Args:
        config: CLI configuration.

    Returns:
        PermissionManager instance.
    """
    from dabba.cli.permissions import PermissionManager  # noqa: F811
    return PermissionManager(mode=config.permission_mode)


def _resolve_prompt(args: argparse.Namespace) -> Optional[str]:
    """
    Resolve the prompt from arguments, file, or stdin.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Prompt string, or None if unavailable.
    """
    if args.prompt:
        return args.prompt

    if getattr(args, "file", None):
        try:
            with open(args.file, "r") as f:
                return f.read().strip()
        except OSError as exc:
            print(f"Error reading file: {exc}", file=sys.stderr)
            return None

    if not sys.stdin.isatty():
        return sys.stdin.read().strip()

    return None


def _list_sessions(config: CliConfig, output) -> None:
    """
    List available saved sessions.

    Args:
        config: CLI configuration.
        output: OutputHandler instance.
    """
    from pathlib import Path

    config_path = Path(config.history_file)
    parent = config_path.parent
    if not parent.exists():
        output.info("No saved sessions found.")
        return

    history_files = sorted(
        parent.glob("session_*.jsonl"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )

    if not history_files:
        output.info("No saved sessions found.")
        return

    rows = []
    for f in history_files[:20]:
        try:
            size = f.stat().st_size
            entries = sum(1 for _ in f.open() if _.strip())
            rows.append([f.name, str(entries), f"{size / 1024:.1f} KB"])
        except OSError:
            continue

    output.table(["Session File", "Entries", "Size"], rows)


def main(argv: Optional[List[str]] = None) -> int:
    """
    Main entry point for the dabba CLI.

    Args:
        argv: Command-line arguments (defaults to sys.argv[1:]).

    Returns:
        Exit code (0 on success, non-zero on error).
    """
    import logging
    # Suppress all logs by default unless --verbose
    logging.disable(logging.CRITICAL)

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.verbose:
        logging.disable(logging.NOTSET)
        _setup_logger(level="debug")

    command_handlers = {
        "chat": cmd_chat,
        "run": cmd_run,
        "session": cmd_session,
        "config": cmd_config,
    }

    handler = command_handlers.get(args.command)
    if handler:
        return handler(args)

    if args.command is None:
        # Default: launch interactive chat (like Claude Code)
        args.resume = None
        args.no_watch = False
        return cmd_chat(args)

    print(f"Unknown command: {args.command}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
