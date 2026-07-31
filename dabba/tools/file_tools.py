"""
File system operation tools for the dabba agent.

Provides read, write, edit, search, and directory listing
capabilities with safety limits and error handling.
"""

from __future__ import annotations

import os
import re
import difflib
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from dabba.agent.tool_schema import ToolDefinition, ToolParameter
from dabba.agent.tool_registry import ToolRegistry
from dabba.utils.logging import get_logger

logger = get_logger("dabba.tools.file_tools")


MAX_READ_SIZE = 1_000_000  # 1 MB
MAX_LIST_ENTRIES = 10_000
MAX_SEARCH_RESULTS = 500


def read_file(path: str, max_size: int = MAX_READ_SIZE) -> str:
    """
    Read the contents of a file.

    Args:
        path: Absolute or relative path to the file.
        max_size: Maximum number of bytes to read (default 1 MB).

    Returns:
        File contents as a string.

    Raises:
        FileNotFoundError: If the file does not exist.
        PermissionError: If the file cannot be read.
        ValueError: If the file is larger than max_size.
    """
    file_path = Path(path).expanduser().resolve()

    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    if not file_path.is_file():
        raise ValueError(f"Not a file: {file_path}")

    file_size = file_path.stat().st_size
    if file_size > max_size:
        raise ValueError(
            f"File size ({file_size} bytes) exceeds max_size ({max_size} bytes). "
            f"Use a larger max_size or read in chunks."
        )

    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except PermissionError:
        raise PermissionError(f"Permission denied reading: {file_path}")

    logger.info("Read file '%s' (%d bytes)", file_path, file_size)
    return content


def write_file(path: str, content: str) -> Dict[str, object]:
    """
    Write content to a file. Creates parent directories if needed.

    Args:
        path: Absolute or relative path to the file.
        content: Text content to write.

    Returns:
        Dict with status/path/size/exists — verified against the filesystem
        after the write, not just assumed from "no exception was raised".

    Raises:
        PermissionError: If the file cannot be written.
        OSError: If the directory cannot be created, or if the write
            reported no error but the file is missing/empty afterward.
    """
    file_path = Path(path).expanduser().resolve()

    if file_path.is_dir():
        raise IsADirectoryError(
            f"'{file_path}' is a directory, not a file. "
            f"Pass a file path inside it, e.g. '{file_path}/notes.txt'."
        )

    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
    except PermissionError:
        raise PermissionError(f"Permission denied writing: {file_path}")

    # Re-check the filesystem rather than trusting that write_text() not
    # raising means the content actually landed (e.g. network/overlay mounts
    # that ack the write call but silently drop it).
    if not file_path.exists():
        raise OSError(f"Write reported no error but file does not exist: {file_path}")
    expected_size = len(content.encode("utf-8"))
    actual_size = file_path.stat().st_size
    if actual_size != expected_size:
        raise OSError(
            f"Write verification failed: expected {expected_size} bytes, "
            f"found {actual_size} bytes at {file_path}"
        )

    logger.info("Wrote file '%s' (%d bytes)", file_path, actual_size)
    return {
        "status": "success",
        "path": str(file_path),
        "size": actual_size,
        "exists": True,
    }


def edit_file(path: str, old_string: str, new_string: str) -> Dict[str, object]:
    """
    Replace occurrences of old_string with new_string in a file.

    Uses exact string matching. Reports how many replacements were made.

    Args:
        path: Absolute or relative path to the file.
        old_string: Text to search for.
        new_string: Replacement text.

    Returns:
        Dict with status/path/replacements/size — verified by re-reading the
        file after the write instead of trusting write_text() not raising.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If old_string is not found in the file.
        OSError: If the write reported no error but the on-disk content
            does not match what was intended.
    """
    file_path = Path(path).expanduser().resolve()

    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    content = file_path.read_text(encoding="utf-8")
    if old_string not in content:
        raise ValueError(
            f"old_string not found in '{file_path}'. "
            "The exact string could not be located."
        )

    count = content.count(old_string)
    new_content = content.replace(old_string, new_string)
    file_path.write_text(new_content, encoding="utf-8")

    on_disk = file_path.read_text(encoding="utf-8")
    if on_disk != new_content:
        raise OSError(
            f"Write verification failed: on-disk content does not match "
            f"the intended edit at {file_path}"
        )

    logger.info("Edited file '%s': %d replacement(s)", file_path, count)
    return {
        "status": "success",
        "path": str(file_path),
        "replacements": count,
        "size": len(on_disk.encode("utf-8")),
    }


def transactional_edit(root: str, edits: List[Dict[str, str]]) -> Dict[str, object]:
    """
    Apply exact replacements across multiple workspace files atomically.

    Every path and old_string is validated before writing. If a write fails,
    all already-written files are restored to their original bytes.
    """
    root_path = Path(root).expanduser().resolve()
    if not root_path.is_dir():
        raise ValueError(f"Workspace root does not exist: {root_path}")
    if not edits:
        raise ValueError("At least one edit is required")

    originals: Dict[Path, bytes] = {}
    replacements: Dict[Path, str] = {}
    diffs: List[Dict[str, str]] = []
    for edit in edits:
        relative = edit.get("path", "")
        old_string = edit.get("old_string", "")
        new_string = edit.get("new_string", "")
        path = (root_path / relative).resolve()
        if path != root_path and root_path not in path.parents:
            raise PermissionError(f"Edit path escapes workspace: {relative}")
        if not path.is_file():
            raise FileNotFoundError(f"File not found: {path}")
        content = path.read_text(encoding="utf-8")
        if not old_string:
            raise ValueError(f"old_string cannot be empty for {relative}")
        if old_string not in content:
            raise ValueError(
                f"old_string not found in {relative}; no files were changed"
            )
        updated = content.replace(old_string, new_string, 1)
        originals[path] = path.read_bytes()
        replacements[path] = updated
        patch = "\n".join(
            difflib.unified_diff(
                content.splitlines(),
                updated.splitlines(),
                fromfile=f"a/{relative}",
                tofile=f"b/{relative}",
                lineterm="",
            )
        )
        diffs.append({"path": relative, "diff": patch})

    written: List[Path] = []
    try:
        for path, updated in replacements.items():
            fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(updated)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_name, path)
            finally:
                Path(temp_name).unlink(missing_ok=True)
            written.append(path)
    except Exception:
        for path in written:
            path.write_bytes(originals[path])
        raise

    return {
        "status": "success",
        "files_changed": len(written),
        "diffs": diffs,
    }


def search_files(
    pattern: str, path: str = ".", regex: bool = False
) -> List[Dict[str, object]]:
    """
    Search for files matching a pattern and containing matching content.

    Args:
        pattern: Glob pattern (default) or regex pattern for file paths.
        path: Root directory to search in.
        regex: If True, treat pattern as a regex instead of glob.

    Returns:
        List of dicts with keys: path, size, modified.

    Raises:
        FileNotFoundError: If the root path does not exist.
    """
    root = Path(path).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"Path not found: {root}")
    if not root.is_dir():
        raise ValueError(f"Not a directory: {root}")

    results: List[Dict[str, object]] = []

    if regex:
        compiled = re.compile(pattern)
        for entry in root.rglob("*"):
            if entry.is_file() and compiled.search(str(entry.relative_to(root))):
                stats = entry.stat()
                results.append(
                    {
                        "path": str(entry),
                        "size": stats.st_size,
                        "modified": stats.st_mtime,
                    }
                )
                if len(results) >= MAX_SEARCH_RESULTS:
                    break
    else:
        for entry in root.glob(pattern):
            if entry.is_file():
                stats = entry.stat()
                results.append(
                    {
                        "path": str(entry),
                        "size": stats.st_size,
                        "modified": stats.st_mtime,
                    }
                )
                if len(results) >= MAX_SEARCH_RESULTS:
                    break

    logger.info(
        "Searched '%s' for '%s': %d matches",
        root,
        pattern,
        len(results),
    )
    return results


def list_directory(path: str = ".") -> List[Dict[str, object]]:
    """
    List entries in a directory.

    Args:
        path: Directory path to list.

    Returns:
        List of dicts with keys: name, path, type (file/dir), size, modified.

    Raises:
        FileNotFoundError: If the path does not exist.
        NotADirectoryError: If the path is not a directory.
    """
    dir_path = Path(path).expanduser().resolve()

    if not dir_path.exists():
        raise FileNotFoundError(f"Path not found: {dir_path}")
    if not dir_path.is_dir():
        raise NotADirectoryError(f"Not a directory: {dir_path}")

    entries: List[Dict[str, object]] = []
    for entry in sorted(dir_path.iterdir()):
        if len(entries) >= MAX_LIST_ENTRIES:
            break
        stats = entry.stat()
        entries.append(
            {
                "name": entry.name,
                "path": str(entry),
                "type": "dir" if entry.is_dir() else "file",
                "size": stats.st_size,
                "modified": stats.st_mtime,
            }
        )

    return entries


def register_file_tools(registry: ToolRegistry) -> None:
    """
    Register all file operation tools with a ToolRegistry.

    Args:
        registry: The tool registry to register with.
    """
    registry.register(
        ToolDefinition(
            name="transactional_edit",
            description=(
                "Atomically apply exact replacements across one or more files under a "
                "workspace root. Validates every edit before writing, returns unified "
                "diffs, and rolls back the whole batch if any write fails."
            ),
            parameters=[
                ToolParameter(
                    name="root",
                    type="string",
                    description="Absolute workspace root containing every edited file.",
                ),
                ToolParameter(
                    name="edits",
                    type="array",
                    description="Edits with path, old_string, and new_string.",
                    items=ToolParameter(
                        name="edit",
                        type="object",
                        properties={
                            "path": ToolParameter(name="path", type="string"),
                            "old_string": ToolParameter(
                                name="old_string", type="string"
                            ),
                            "new_string": ToolParameter(
                                name="new_string", type="string"
                            ),
                        },
                    ),
                ),
            ],
            handler=transactional_edit,
            handler_sync=True,
            category="filesystem",
        )
    )
    registry.register(
        ToolDefinition(
            name="file_read",
            description="Read the contents of a file from the filesystem.",
            parameters=[
                ToolParameter(
                    name="path", type="string", description="Path to the file to read."
                ),
                ToolParameter(
                    name="max_size",
                    type="integer",
                    description="Maximum bytes to read.",
                    required=False,
                    default=MAX_READ_SIZE,
                ),
            ],
            handler=read_file,
            handler_sync=True,
            category="filesystem",
        )
    )
    registry.register(
        ToolDefinition(
            name="file_write",
            description="Write text content to a file, creating parent directories if needed.",
            parameters=[
                ToolParameter(
                    name="path", type="string", description="Path to write to."
                ),
                ToolParameter(
                    name="content", type="string", description="Text content to write."
                ),
            ],
            handler=write_file,
            handler_sync=True,
            category="filesystem",
        )
    )
    registry.register(
        ToolDefinition(
            name="file_edit",
            description="Replace exact occurrences of old_string with new_string in a file.",
            parameters=[
                ToolParameter(
                    name="path", type="string", description="Path to the file to edit."
                ),
                ToolParameter(
                    name="old_string", type="string", description="Text to find."
                ),
                ToolParameter(
                    name="new_string", type="string", description="Replacement text."
                ),
            ],
            handler=edit_file,
            handler_sync=True,
            category="filesystem",
        )
    )
    registry.register(
        ToolDefinition(
            name="file_search",
            description="Search for files by glob or regex pattern in a directory tree.",
            parameters=[
                ToolParameter(
                    name="pattern",
                    type="string",
                    description="Search pattern (glob or regex).",
                ),
                ToolParameter(
                    name="path",
                    type="string",
                    description="Root directory to search.",
                    required=False,
                    default=".",
                ),
                ToolParameter(
                    name="regex",
                    type="boolean",
                    description="Use regex instead of glob.",
                    required=False,
                    default=False,
                ),
            ],
            handler=search_files,
            handler_sync=True,
            category="filesystem",
        )
    )
    registry.register(
        ToolDefinition(
            name="file_list",
            description="List all entries in a directory with metadata.",
            parameters=[
                ToolParameter(
                    name="path",
                    type="string",
                    description="Directory to list.",
                    required=False,
                    default=".",
                ),
            ],
            handler=list_directory,
            handler_sync=True,
            category="filesystem",
        )
    )
