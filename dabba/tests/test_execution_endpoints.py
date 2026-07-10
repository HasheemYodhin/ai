import shutil

import pytest

from dabba.api.execution_endpoints import ExecutionRequest, execute_code, normalize_language


def test_language_aliases_are_normalized():
    assert normalize_language("py") == "python"
    assert normalize_language("js") == "javascript"
    assert normalize_language("c++") == "cpp"


def test_unknown_language_is_rejected():
    with pytest.raises(ValueError, match="Unsupported language"):
        normalize_language("brainfuck")


@pytest.mark.skipif(shutil.which("python3") is None, reason="python3 not installed")
def test_python_execution_captures_stdin_and_stdout():
    result = execute_code(ExecutionRequest(
        language="python",
        code="name = input()\nprint(f'Hello, {name}!')",
        stdin="Dabba\n",
    ))

    assert result["exitCode"] == 0
    assert result["stdout"] == "Hello, Dabba!\n"
    assert result["stderr"] == ""


@pytest.mark.skipif(shutil.which("python3") is None, reason="python3 not installed")
def test_execution_timeout_is_reported():
    result = execute_code(ExecutionRequest(
        language="python",
        code="while True: pass",
        timeout=1,
    ))

    assert result["timedOut"] is True
    assert result["exitCode"] is None


@pytest.mark.skipif(shutil.which("gcc") is None, reason="gcc not installed")
def test_compiled_c_execution():
    result = execute_code(ExecutionRequest(
        language="c",
        code='#include <stdio.h>\nint main(void) { puts("compiled"); return 0; }',
    ))

    assert result["exitCode"] == 0
    assert result["stdout"] == "compiled\n"
