"""
Tool implementations for the dabba agent system.

Provides built-in tools for file operations, shell commands,
web access, code analysis, and RAG queries.
"""

from dabba.tools.file_tools import (
    read_file,
    write_file,
    edit_file,
    search_files,
    list_directory,
    register_file_tools,
)
from dabba.tools.shell_tools import (
    execute_command,
    ShellPermissionManager,
    register_shell_tools,
)
from dabba.tools.web_tools import (
    fetch_url,
    search_web,
    extract_links,
    register_web_tools,
)
from dabba.tools.code_tools import (
    analyze_code,
    format_code,
    explain_code,
    register_code_tools,
)
from dabba.tools.rag_tool import (
    query_knowledge_base,
    register_rag_tools,
)
from dabba.tools.process_tools import (
    start_process,
    list_processes,
    get_process_output,
    stop_process,
    register_process_tools,
)
from dabba.tools.ssh_tools import (
    ssh_exec,
    scp_copy,
    SSHPermissionManager,
    register_ssh_tools,
)
from dabba.tools.docker_tools import (
    docker_exec,
    docker_run,
    docker_list_containers,
    DockerPermissionManager,
    register_docker_tools,
)

__all__ = [
    "read_file",
    "write_file",
    "edit_file",
    "search_files",
    "list_directory",
    "register_file_tools",
    "execute_command",
    "ShellPermissionManager",
    "register_shell_tools",
    "fetch_url",
    "search_web",
    "extract_links",
    "register_web_tools",
    "analyze_code",
    "format_code",
    "explain_code",
    "register_code_tools",
    "query_knowledge_base",
    "register_rag_tools",
    "start_process",
    "list_processes",
    "get_process_output",
    "stop_process",
    "register_process_tools",
    "ssh_exec",
    "scp_copy",
    "SSHPermissionManager",
    "register_ssh_tools",
    "docker_exec",
    "docker_run",
    "docker_list_containers",
    "DockerPermissionManager",
    "register_docker_tools",
]
