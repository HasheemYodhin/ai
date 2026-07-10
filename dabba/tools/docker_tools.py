"""
Containerized (Docker) execution tools for the dabba agent.

Shells out to the `docker` CLI. Kept as a separate, explicitly-scoped tool
rather than allowing "docker" through shell_exec — shell_tools.py's
DEFAULT allowed_commands intentionally excludes it, since unrestricted
docker access from a shell string is equivalent to root on the host.

Both exec (into an existing container) and run (ephemeral container from an
image) are allowlisted independently via CliConfig.allowed_docker_containers
/ allowed_docker_images, empty by default (deny all).
"""

from __future__ import annotations

import asyncio
import shlex
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from dabba.agent.tool_schema import ToolDefinition, ToolParameter
from dabba.agent.tool_registry import ToolRegistry
from dabba.utils.logging import get_logger

logger = get_logger("dabba.tools.docker_tools")


@dataclass
class DockerPermissionManager:
    """
    Allowlists for Docker exec/run targets.

    Args:
        allowed_containers: Container names/IDs permitted for docker_exec.
        allowed_images: Image references permitted for docker_run.
    """

    allowed_containers: Set[str] = field(default_factory=set)
    allowed_images: Set[str] = field(default_factory=set)

    def is_container_allowed(self, container: str) -> bool:
        return container in self.allowed_containers

    def is_image_allowed(self, image: str) -> bool:
        return image in self.allowed_images

    @classmethod
    def from_cli_config(cls) -> "DockerPermissionManager":
        from dabba.cli.config import CliConfig
        config = CliConfig.load()
        return cls(
            allowed_containers=set(getattr(config, "allowed_docker_containers", []) or []),
            allowed_images=set(getattr(config, "allowed_docker_images", []) or []),
        )


DEFAULT_DOCKER_PERMISSION_MANAGER = DockerPermissionManager.from_cli_config()


async def _run_argv(argv: List[str], timeout: int) -> Dict[str, object]:
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return {
            "returncode": proc.returncode or 0,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "timed_out": False,
        }
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return {"returncode": -1, "stdout": "", "stderr": f"Timed out after {timeout}s", "timed_out": True}


async def docker_exec(
    container: str,
    command: str,
    timeout: int = 60,
    permission_manager: Optional[DockerPermissionManager] = None,
) -> Dict[str, object]:
    """
    Execute a command inside an already-running container.

    Args:
        container: Container name or ID. Must be in the allowlist.
        command: Command to run inside the container.
        timeout: Max execution time in seconds.
        permission_manager: Container allowlist checker.

    Returns:
        Dict with keys: container, command, returncode, stdout, stderr, timed_out.

    Raises:
        PermissionError: If the container is not in the allowlist.
        ValueError: If container or command is empty.
    """
    pm = permission_manager or DEFAULT_DOCKER_PERMISSION_MANAGER
    if not container or not container.strip():
        raise ValueError("Container cannot be empty")
    if not command or not command.strip():
        raise ValueError("Command cannot be empty")
    if not pm.is_container_allowed(container):
        raise PermissionError(
            f"Container '{container}' is not in the allowlist. "
            "Add it to CliConfig.allowed_docker_containers to permit exec."
        )

    argv = ["docker", "exec", container, "sh", "-c", command]
    logger.info("docker exec on '%s': %s", container, command[:100])
    result = await _run_argv(argv, timeout)
    return {"container": container, "command": command, **result}


async def docker_run(
    image: str,
    command: str,
    timeout: int = 120,
    volumes: Optional[List[str]] = None,
    network: str = "none",
    permission_manager: Optional[DockerPermissionManager] = None,
) -> Dict[str, object]:
    """
    Run a command in a fresh, disposable container for isolation.

    Args:
        image: Image reference (e.g. "python:3.12-slim"). Must be allowlisted.
        command: Command to run inside the container.
        timeout: Max execution time in seconds.
        volumes: Bind mounts as "host_path:container_path" strings.
        network: Docker network mode; defaults to "none" (no network access)
            for isolation — pass "bridge" explicitly if the command needs it.
        permission_manager: Image allowlist checker.

    Returns:
        Dict with keys: image, command, returncode, stdout, stderr, timed_out.

    Raises:
        PermissionError: If the image is not in the allowlist.
        ValueError: If image or command is empty.
    """
    pm = permission_manager or DEFAULT_DOCKER_PERMISSION_MANAGER
    if not image or not image.strip():
        raise ValueError("Image cannot be empty")
    if not command or not command.strip():
        raise ValueError("Command cannot be empty")
    if not pm.is_image_allowed(image):
        raise PermissionError(
            f"Image '{image}' is not in the allowlist. "
            "Add it to CliConfig.allowed_docker_images to permit docker_run."
        )

    argv = ["docker", "run", "--rm", "--network", network]
    for vol in (volumes or []):
        argv += ["-v", vol]
    argv += [image, "sh", "-c", command]

    logger.info("docker run '%s': %s", image, command[:100])
    result = await _run_argv(argv, timeout)
    return {"image": image, "command": command, **result}


async def docker_list_containers(timeout: int = 15) -> Dict[str, object]:
    """
    List running containers (`docker ps`). Read-only, no allowlist required.

    Args:
        timeout: Max execution time in seconds.

    Returns:
        Dict with keys: returncode, stdout, stderr, timed_out.
    """
    return await _run_argv(["docker", "ps", "--format", "{{.ID}}\t{{.Image}}\t{{.Names}}\t{{.Status}}"], timeout)


def register_docker_tools(registry: ToolRegistry) -> None:
    """
    Register Docker execution tools with a ToolRegistry.

    Args:
        registry: The tool registry to register with.
    """
    registry.register(
        ToolDefinition(
            name="docker_exec",
            description="Execute a command inside a running container. Container must be pre-approved in the allowlist.",
            parameters=[
                ToolParameter(name="container", type="string", description="Container name or ID."),
                ToolParameter(name="command", type="string", description="Command to run inside the container."),
                ToolParameter(name="timeout", type="integer", description="Max execution time in seconds.", required=False, default=60),
            ],
            handler=docker_exec,
            handler_sync=False,
            category="container",
        )
    )
    registry.register(
        ToolDefinition(
            name="docker_run",
            description="Run a command in a fresh, disposable container for isolation. Image must be pre-approved in the allowlist.",
            parameters=[
                ToolParameter(name="image", type="string", description="Image reference, e.g. 'python:3.12-slim'."),
                ToolParameter(name="command", type="string", description="Command to run inside the container."),
                ToolParameter(name="timeout", type="integer", description="Max execution time in seconds.", required=False, default=120),
                ToolParameter(
                    name="volumes", type="array", description="Bind mounts as 'host_path:container_path'.",
                    required=False, default=None, items=ToolParameter(name="volume", type="string"),
                ),
                ToolParameter(name="network", type="string", description="Docker network mode (default 'none' = isolated).", required=False, default="none"),
            ],
            handler=docker_run,
            handler_sync=False,
            category="container",
        )
    )
    registry.register(
        ToolDefinition(
            name="docker_list_containers",
            description="List running Docker containers (read-only).",
            parameters=[
                ToolParameter(name="timeout", type="integer", description="Max execution time in seconds.", required=False, default=15),
            ],
            handler=docker_list_containers,
            handler_sync=False,
            category="container",
        )
    )
