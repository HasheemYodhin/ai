import logging

import pytest

from dabba.agent.mcp_client import McpClientManager
from dabba.utils.logging import setup_logger


def test_mcp_supervisor_accepts_cross_thread_requests():
    manager = McpClientManager()
    try:
        future = manager._submit("unsupported", None)
        with pytest.raises(ValueError, match="Unknown supervisor request kind"):
            future.result(timeout=2)
    finally:
        manager.close()


def test_dabba_logs_use_stderr_not_mcp_stdout(capsys):
    name = "dabba.tests.mcp_stdio"
    logger = logging.getLogger(name)
    logger.handlers.clear()
    setup_logger(name).info("protocol-safe diagnostic")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "protocol-safe diagnostic" in captured.err
