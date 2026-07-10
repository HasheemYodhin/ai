"""
Code analysis tools for the dabba agent.

Provides code analysis, formatting, and explanation capabilities,
with language detection and syntax awareness.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from dabba.agent.tool_schema import ToolDefinition, ToolParameter
from dabba.agent.tool_registry import ToolRegistry
from dabba.utils.logging import get_logger

logger = get_logger("dabba.tools.code_tools")

_LANGUAGE_ALIASES = {
    "py": "python",
    "js": "javascript",
    "ts": "typescript",
    "jsx": "javascript",
    "tsx": "typescript",
    "rb": "ruby",
    "go": "golang",
    "rs": "rust",
    "c": "c",
    "cpp": "cpp",
    "h": "c",
    "hpp": "cpp",
    "java": "java",
    "kt": "kotlin",
    "swift": "swift",
    "r": "r",
    "m": "objective-c",
    "mm": "objective-c",
    "sh": "bash",
    "bash": "bash",
    "zsh": "bash",
    "yaml": "yaml",
    "yml": "yaml",
    "json": "json",
    "md": "markdown",
    "html": "html",
    "css": "css",
    "scss": "scss",
    "sql": "sql",
}


def _normalize_language(language: str) -> str:
    """Normalize a language name or file extension to a standard form."""
    lang = language.lower().strip().lstrip(".")
    return _LANGUAGE_ALIASES.get(lang, lang)


def analyze_code(code: str = "", language: str = "", path: str = "") -> Dict[str, Any]:
    """
    Analyze source code and return structural information.

    Performs static analysis including:
      - Function and class definitions
      - Import statements
      - Line count and complexity metrics
      - Syntax validation (for supported languages)

    Args:
        code: The source code to analyze. Omit this and pass `path` instead
            to analyze a file directly without reading it yourself first.
        language: Programming language (auto-detected if empty).
        path: Path to a file to read and analyze, used when `code` is empty.

    Returns:
        Dictionary with analysis results including language detection,
        structure, metrics, and any errors found.
    """
    if not code and path:
        file_path = Path(path).expanduser().resolve()
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        code = file_path.read_text(encoding="utf-8", errors="replace")
        if not language:
            language = file_path.suffix.lstrip(".")

    analysis: Dict[str, Any] = {
        "language": language or _detect_language(code),
        "line_count": len(code.splitlines()),
        "char_count": len(code),
        "functions": [],
        "classes": [],
        "imports": [],
        "complexity": {},
        "errors": [],
    }

    lang = _normalize_language(analysis["language"])

    if lang == "python":
        _analyze_python(code, analysis)
    elif lang in ("javascript", "typescript"):
        _analyze_js_ts(code, analysis)
    else:
        _generic_analyze(code, analysis)

    analysis["complexity"]["avg_line_length"] = (
        analysis["char_count"] / max(analysis["line_count"], 1)
    )
    analysis["complexity"]["empty_lines_pct"] = (
        _count_empty_lines(code) / max(analysis["line_count"], 1) * 100
    )

    return analysis


def _detect_language(code: str) -> str:
    """Detect the programming language from code content."""
    heuristics = [
        (r"^\s*(import |from \S+ import |def |class |async def |@\w+)", "python"),
        (r"^\s*(function |const |let |var |import |export |interface |type |=>)", "javascript"),
        (r"^\s*(#include|int main|void main|printf|scanf)", "c"),
        (r"^\s*(#include\s*<iostream>|std::|cout|cin|template)", "cpp"),
        (r"^\s*(import java\.|public class|private |protected |void main)", "java"),
        (r"^\s*(package main|import \(\"fmt\"\)|func |fmt\.)", "golang"),
        (r"^\s*(fn |pub fn|let mut|impl |struct |trait |enum )", "rust"),
        (r"^\s*(def |require|puts |print |#\{)", "ruby"),
        (r"^\s*(import Swift|func |var |let |class )", "swift"),
        (r"^\s*(defn |defun |->|\(ns )", "clojure"),
    ]

    for pattern, lang in heuristics:
        if re.search(pattern, code, re.MULTILINE):
            return lang

    if re.search(r"^\s*<\?php", code, re.MULTILINE):
        return "php"
    if re.search(r"^\s*(SELECT|FROM|WHERE|INSERT|CREATE|ALTER)", code, re.IGNORECASE | re.MULTILINE):
        return "sql"
    if re.search(r"^\s*#!/", code, re.MULTILINE):
        return "bash"

    return "unknown"


def _analyze_python(code: str, analysis: Dict[str, Any]) -> None:
    """Perform detailed Python analysis using the AST module."""
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                func_info = {
                    "name": node.name,
                    "line": node.lineno,
                    "args": [a.arg for a in node.args.args],
                    "decorators": [
                        d.id if isinstance(d, ast.Name) else ast.dump(d)
                        for d in node.decorator_list
                    ],
                    "docstring": ast.get_docstring(node) or "",
                }
                analysis["functions"].append(func_info)
            elif isinstance(node, ast.AsyncFunctionDef):
                func_info = {
                    "name": node.name,
                    "line": node.lineno,
                    "args": [a.arg for a in node.args.args],
                    "decorators": [
                        d.id if isinstance(d, ast.Name) else ast.dump(d)
                        for d in node.decorator_list
                    ],
                    "async": True,
                    "docstring": ast.get_docstring(node) or "",
                }
                analysis["functions"].append(func_info)
            elif isinstance(node, ast.ClassDef):
                class_info = {
                    "name": node.name,
                    "line": node.lineno,
                    "bases": [
                        b.id if isinstance(b, ast.Name) else ast.dump(b)
                        for b in node.bases
                    ],
                    "methods": [
                        n.name for n in node.body
                        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    ],
                    "docstring": ast.get_docstring(node) or "",
                }
                analysis["classes"].append(class_info)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        analysis["imports"].append(alias.name)
                else:
                    module = node.module or ""
                    for alias in node.names:
                        full = f"{module}.{alias.name}" if module else alias.name
                        analysis["imports"].append(full)

        analysis["complexity"]["num_functions"] = len(analysis["functions"])
        analysis["complexity"]["num_classes"] = len(analysis["classes"])
        analysis["complexity"]["num_imports"] = len(analysis["imports"])
        analysis["valid_syntax"] = True

    except SyntaxError as e:
        analysis["errors"].append(f"Syntax error at line {e.lineno}: {e.msg}")
        analysis["valid_syntax"] = False
        _generic_analyze(code, analysis)


def _analyze_js_ts(code: str, analysis: Dict[str, Any]) -> None:
    """Perform lightweight JavaScript/TypeScript analysis."""
    func_pattern = re.compile(
        r"(?:async\s+)?function\s+\*?\s*(\w+)\s*\(|"
        r"(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:function\s*)?\(|"
        r"(\w+)\s*\([^)]*\)\s*{"
    )
    class_pattern = re.compile(r"class\s+(\w+)")
    import_pattern = re.compile(
        r"(?:import\s+(?:\w+\s*,?\s*)?(?:{[^}]*})?\s*from\s+['\"]([^'\"]+)['\"]"
        r"|require\(['\"]([^'\"]+)['\"]\))"
    )

    for match in func_pattern.finditer(code):
        name = next(g for g in match.groups() if g)
        if name:
            analysis["functions"].append({"name": name})

    for match in class_pattern.finditer(code):
        analysis["classes"].append({"name": match.group(1)})

    for match in import_pattern.finditer(code):
        lib = match.group(1) or match.group(2)
        if lib:
            analysis["imports"].append(lib)

    analysis["complexity"]["num_functions"] = len(analysis["functions"])
    analysis["complexity"]["num_classes"] = len(analysis["classes"])
    analysis["complexity"]["num_imports"] = len(analysis["imports"])


def _generic_analyze(code: str, analysis: Dict[str, Any]) -> None:
    """Generic code analysis for unrecognized languages."""
    func_pattern = re.compile(
        r"(?:def |function |fun |func |fn |defn |void |int |string |"
        r"float |bool |public |private |protected |static )\s*(\w+)\s*\("
    )
    class_pattern = re.compile(
        r"(?:class |struct |trait |interface |type |enum )\s+(\w+)"
    )
    import_pattern = re.compile(
        r"(?:import |include |require |use |from )[\"'<]?(\S+?)[\"'>]?"
    )

    for match in func_pattern.finditer(code):
        analysis["functions"].append({"name": match.group(1)})
    for match in class_pattern.finditer(code):
        analysis["classes"].append({"name": match.group(1)})
    for match in import_pattern.finditer(code):
        analysis["imports"].append(match.group(1))

    analysis["complexity"]["num_functions"] = len(analysis["functions"])
    analysis["complexity"]["num_classes"] = len(analysis["classes"])
    analysis["complexity"]["num_imports"] = len(analysis["imports"])


def _count_empty_lines(code: str) -> int:
    """Count blank/empty lines in code."""
    return sum(1 for line in code.splitlines() if not line.strip())


def format_code(code: str, language: str = "") -> str:
    """
    Format source code according to language conventions.

    Supports Python (autopep8/black) and general formatting.
    Falls back to basic whitespace normalization if no formatter is available.

    Args:
        code: Source code to format.
        language: Programming language for formatter selection.

    Returns:
            Formatted source code.

    Raises:
        ValueError: If the formatter tool is not installed or fails.
    """
    lang = _normalize_language(language) if language else _detect_language(code)

    if lang == "python":
        return _format_python(code)
    elif lang in ("javascript", "typescript", "json"):
        return _format_with_prettier(code, lang)
    elif lang in ("html", "css", "scss", "markdown", "yaml"):
        return _format_with_prettier(code, lang)
    else:
        return _basic_format(code)


def _format_python(code: str) -> str:
    """Format Python code using autopep8 or black."""
    try:
        result = subprocess.run(
            ["black", "--quiet", "--fast", "-"],
            input=code,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout

        result = subprocess.run(
            ["autopep8", "--aggressive", "--aggressive", "-"],
            input=code,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout

        import ast
        try:
            tree = ast.parse(code)
            if tree:
                logger.info("Python code is syntactically valid; no formatter applied")
                return code
        except SyntaxError:
            pass

        raise ValueError(
            "Could not format Python code. Install black or autopep8."
        )

    except FileNotFoundError:
        return _basic_format(code)
    except subprocess.TimeoutExpired:
        logger.warning("Formatter timed out; returning code unchanged")
        return code


def _format_with_prettier(code: str, language: str) -> str:
    """Format code using prettier."""
    parser_map = {
        "javascript": "babel",
        "typescript": "typescript",
        "json": "json",
        "html": "html",
        "css": "css",
        "scss": "scss",
        "markdown": "markdown",
        "yaml": "yaml",
    }
    parser = parser_map.get(language, "babel")

    try:
        result = subprocess.run(
            ["prettier", "--parser", parser, "--stdin-filepath", f"file.{language}"],
            input=code,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout
        raise ValueError(f"prettier error: {result.stderr.strip()}")
    except FileNotFoundError:
        if language == "json":
            try:
                parsed = json.loads(code)
                return json.dumps(parsed, indent=2)
            except json.JSONDecodeError:
                pass
        return _basic_format(code)
    except subprocess.TimeoutExpired:
        return code


def _basic_format(code: str) -> str:
    """
    Basic whitespace normalization when no formatter is available.

    Strips trailing whitespace and ensures consistent line endings.
    """
    lines = code.splitlines()
    formatted = []
    for line in lines:
        formatted.append(line.rstrip())

    while formatted and not formatted[0].strip():
        formatted.pop(0)
    while formatted and not formatted[-1].strip():
        formatted.pop()

    return "\n".join(formatted) + ("\n" if code.endswith("\n") else "")


def explain_code(code: str, language: str = "") -> str:
    """
    Generate a plain-language explanation of what the code does.

    Uses pattern matching to identify key structures and produce
    a human-readable summary.

    Args:
        code: Source code to explain.
        language: Programming language (auto-detected if empty).

    Returns:
        Natural language explanation of the code.
    """
    lang = language or _detect_language(code)
    lines = code.splitlines()
    num_lines = len(lines)
    analysis = analyze_code(code, lang)

    parts: List[str] = []
    parts.append(f"This is a {lang} source file with {num_lines} lines.")

    if analysis["classes"]:
        class_names = [c["name"] for c in analysis["classes"]]
        parts.append(f"It defines {len(analysis['classes'])} class(es): {', '.join(class_names)}.")

    if analysis["functions"]:
        func_names = [f["name"] for f in analysis["functions"]]
        parts.append(f"It contains {len(analysis['functions'])} function(s): {', '.join(func_names)}.")

    if analysis["imports"]:
        imp = analysis["imports"][:10]
        parts.append(f"It imports from: {', '.join(imp)}.")
        if len(analysis["imports"]) > 10:
            parts.append(f"... and {len(analysis['imports']) - 10} more imports.")

    if analysis["errors"]:
        parts.append(f"⚠ Syntax issues: {'; '.join(analysis['errors'][:3])}")

    docstrings = [
        f.get("docstring", "")
        for f in analysis.get("functions", [])
        if f.get("docstring")
    ] + [
        c.get("docstring", "")
        for c in analysis.get("classes", [])
        if c.get("docstring")
    ]
    if docstrings:
        first_doc = docstrings[0][:200]
        parts.append(f"Summary from docstrings: {first_doc}")

    return "\n".join(parts)


def register_code_tools(registry: ToolRegistry) -> None:
    """
    Register all code analysis tools with a ToolRegistry.

    Args:
        registry: The tool registry to register with.
    """
    registry.register(
        ToolDefinition(
            name="code_analyze",
            description=(
                "Analyze source code structure, extract functions, classes, imports, and metrics. "
                "Pass EITHER 'path' (to analyze a file directly, preferred) OR 'code' (inline source text) — not both."
            ),
            parameters=[
                ToolParameter(name="code", type="string", description="Inline source code to analyze. Omit if using 'path'.", required=False, default=""),
                ToolParameter(name="path", type="string", description="Path to a file to read and analyze. Omit if using 'code'.", required=False, default=""),
                ToolParameter(name="language", type="string", description="Programming language (auto-detected if empty).", required=False, default=""),
            ],
            handler=analyze_code,
            handler_sync=True,
            category="code",
        )
    )
    registry.register(
        ToolDefinition(
            name="code_format",
            description="Format source code using black/autopep8 (Python) or prettier (JS/TS/others).",
            parameters=[
                ToolParameter(name="code", type="string", description="Source code to format."),
                ToolParameter(name="language", type="string", description="Programming language.", required=False, default=""),
            ],
            handler=format_code,
            handler_sync=True,
            category="code",
        )
    )
    registry.register(
        ToolDefinition(
            name="code_explain",
            description="Generate a plain-language explanation of what source code does.",
            parameters=[
                ToolParameter(name="code", type="string", description="Source code to explain."),
                ToolParameter(name="language", type="string", description="Programming language.", required=False, default=""),
            ],
            handler=explain_code,
            handler_sync=True,
            category="code",
        )
    )
