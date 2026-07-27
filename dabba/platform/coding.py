"""Code indexing, verification, worktree isolation, and browser validation."""

from __future__ import annotations

import ast
import concurrent.futures
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from dabba.platform.core import PlatformStore, get_platform_store, json_dumps, json_loads, utc_ms


class CodeIndexService:
    """Lightweight symbol and dependency index without a language server."""

    EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs"}
    EXCLUDED = {".git", ".venv", "venv", "node_modules", "dist", "build", "__pycache__"}

    def __init__(self, store: Optional[PlatformStore] = None):
        self.store = store or get_platform_store()

    def index(self, workspace_id: str, root: str) -> Dict[str, Any]:
        root_path = Path(root).expanduser().resolve()
        records = []
        for path in root_path.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in self.EXTENSIONS:
                continue
            if any(part in self.EXCLUDED for part in path.parts):
                continue
            try:
                records.extend(self._parse(path, root_path))
            except (OSError, SyntaxError, UnicodeError):
                continue
        now = utc_ms()
        with self.store.transaction() as conn:
            conn.execute("DELETE FROM code_symbols WHERE workspace_id=?", (workspace_id,))
            conn.executemany(
                """
                INSERT INTO code_symbols
                    (workspace_id, path, language, symbol, kind, line,
                     signature, dependencies_json, indexed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        workspace_id,
                        record["path"],
                        record["language"],
                        record["symbol"],
                        record["kind"],
                        record["line"],
                        record.get("signature"),
                        json_dumps(record.get("dependencies", [])),
                        now,
                    )
                    for record in records
                ],
            )
        return {
            "workspaceId": workspace_id,
            "files": len({record["path"] for record in records}),
            "symbols": len(records),
            "indexedAt": now,
        }

    def search(self, workspace_id: str, query: str, limit: int = 50) -> list[Dict[str, Any]]:
        rows = self.store.fetchall(
            """
            SELECT * FROM code_symbols
            WHERE workspace_id=? AND (symbol LIKE ? OR path LIKE ?)
            ORDER BY CASE WHEN symbol=? THEN 0 ELSE 1 END, symbol
            LIMIT ?
            """,
            (workspace_id, f"%{query}%", f"%{query}%", query, max(1, min(limit, 200))),
        )
        return [
            {
                "path": row["path"],
                "language": row["language"],
                "symbol": row["symbol"],
                "kind": row["kind"],
                "line": row["line"],
                "signature": row["signature"],
                "dependencies": json_loads(row["dependencies_json"], []),
            }
            for row in rows
        ]

    def _parse(self, path: Path, root: Path) -> list[Dict[str, Any]]:
        text = path.read_text(encoding="utf-8")
        relative = str(path.relative_to(root))
        language = path.suffix.lower().lstrip(".")
        if path.suffix.lower() == ".py":
            tree = ast.parse(text)
            dependencies = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    dependencies.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    dependencies.append(node.module or "")
            records = []
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    kind = "class" if isinstance(node, ast.ClassDef) else "function"
                    records.append(
                        {
                            "path": relative,
                            "language": "python",
                            "symbol": node.name,
                            "kind": kind,
                            "line": node.lineno,
                            "signature": ast.get_source_segment(text, node).splitlines()[0][:300]
                            if ast.get_source_segment(text, node)
                            else None,
                            "dependencies": dependencies,
                        }
                    )
            return records

        dependency_pattern = re.compile(
            r"(?:from|import|require\()\s*['\"]?([^'\"\s;)]+)"
        )
        dependencies = dependency_pattern.findall(text)
        symbol_pattern = re.compile(
            r"^\s*(?:export\s+)?(?:async\s+)?"
            r"(class|function|interface|type|enum|struct|trait|func|fn)\s+([A-Za-z_]\w*)",
            re.MULTILINE,
        )
        return [
            {
                "path": relative,
                "language": language,
                "symbol": match.group(2),
                "kind": match.group(1),
                "line": text.count("\n", 0, match.start()) + 1,
                "signature": match.group(0).strip()[:300],
                "dependencies": dependencies,
            }
            for match in symbol_pattern.finditer(text)
        ]


class VerificationService:
    """Detect and run project formatting, diagnostics, build, and tests."""

    def commands(self, root: str) -> list[tuple[str, list[str]]]:
        path = Path(root)
        commands: list[tuple[str, list[str]]] = []
        if (path / "frontend" / "package.json").exists():
            commands.extend([
                ("frontend-build", ["npm", "run", "build", "--prefix", "frontend"]),
                ("frontend-lint", ["npm", "run", "lint", "--prefix", "frontend"]),
            ])
        elif (path / "package.json").exists():
            commands.extend([("build", ["npm", "run", "build"]), ("test", ["npm", "test", "--", "--run"])])
        if any(path.glob("**/test_*.py")):
            commands.append(("python-tests", ["python3", "-m", "pytest", "-q"]))
        if (path / "Cargo.toml").exists():
            commands.extend([("cargo-check", ["cargo", "check"]), ("cargo-test", ["cargo", "test"])])
        if (path / "go.mod").exists():
            commands.append(("go-test", ["go", "test", "./..."]))
        return commands

    def run(self, root: str, timeout_seconds: int = 600) -> Dict[str, Any]:
        root_path = Path(root).expanduser().resolve()
        results = []
        for name, command in self.commands(str(root_path)):
            try:
                completed = subprocess.run(
                    command,
                    cwd=root_path,
                    text=True,
                    capture_output=True,
                    timeout=timeout_seconds,
                    check=False,
                )
                results.append(
                    {
                        "name": name,
                        "command": command,
                        "exitCode": completed.returncode,
                        "stdout": completed.stdout[-20_000:],
                        "stderr": completed.stderr[-20_000:],
                        "success": completed.returncode == 0,
                    }
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                results.append(
                    {
                        "name": name,
                        "command": command,
                        "exitCode": None,
                        "stdout": "",
                        "stderr": str(exc),
                        "success": False,
                    }
                )
        return {"success": bool(results) and all(item["success"] for item in results), "results": results}


class WorktreeService:
    """Create isolated Git worktrees for background coding tasks."""

    def create(self, repository: str, destination: str, branch: str) -> Dict[str, Any]:
        repo = Path(repository).expanduser().resolve()
        target = Path(destination).expanduser().resolve()
        if target.exists():
            raise ValueError(f"Worktree destination already exists: {target}")
        completed = subprocess.run(
            ["git", "worktree", "add", "-b", branch, str(target)],
            cwd=repo,
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode:
            raise RuntimeError(completed.stderr.strip() or "Could not create worktree")
        return {"repository": str(repo), "path": str(target), "branch": branch}

    def list(self, repository: str) -> list[Dict[str, str]]:
        completed = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=Path(repository).expanduser().resolve(),
            text=True,
            capture_output=True,
            check=True,
        )
        worktrees = []
        current: Dict[str, str] = {}
        for line in completed.stdout.splitlines():
            if not line:
                if current:
                    worktrees.append(current)
                    current = {}
            elif " " in line:
                key, value = line.split(" ", 1)
                current[key] = value
        if current:
            worktrees.append(current)
        return worktrees


class SchemaValidationError(ValueError):
    """A pipeline stage's output didn't match its declared output_schema."""


class SubagentCoordinator:
    """Bounded parallel role runner; callers provide the actual agent function."""

    def run(
        self,
        assignments: Dict[str, str],
        runner: Callable[[str, str], Any],
        *,
        max_workers: int = 4,
    ) -> Dict[str, Any]:
        results: Dict[str, Any] = {}
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, min(max_workers, len(assignments) or 1))
        ) as executor:
            futures = {
                executor.submit(runner, role, prompt): role
                for role, prompt in assignments.items()
            }
            for future in concurrent.futures.as_completed(futures):
                role = futures[future]
                try:
                    results[role] = {"success": True, "result": future.result()}
                except Exception as exc:
                    results[role] = {"success": False, "error": str(exc)}
        return results

    def pipeline(
        self,
        stages: List[Dict[str, Any]],
        runner: Callable[[str, str], Any],
        *,
        initial_input: str = "",
    ) -> List[Dict[str, Any]]:
        """
        Run stages sequentially, each stage's output feeding the next.

        Each stage is {"role": str, "prompt_template": str, "output_schema":
        Optional[dict]}. prompt_template must contain "{input}", replaced
        with the previous stage's output (or initial_input for the first
        stage). When output_schema is given, the stage's result is parsed as
        JSON and validated against it (see validate_json_schema) before
        being used as the next stage's input — a stage that returns
        malformed JSON or fails validation stops the pipeline there, since
        downstream stages can't meaningfully consume broken input.

        Returns one result dict per stage actually run, in order:
        {"role", "success", "result"} or {"role", "success", "error"}.
        """
        results: List[Dict[str, Any]] = []
        current_input = initial_input
        for stage in stages:
            role = stage["role"]
            prompt = stage["prompt_template"].format(input=current_input)
            try:
                raw = runner(role, prompt)
                schema = stage.get("output_schema")
                if schema is not None:
                    parsed = raw if not isinstance(raw, str) else json.loads(raw)
                    validate_json_schema(parsed, schema)
                    value = parsed
                else:
                    value = raw
                results.append({"role": role, "success": True, "result": value})
                current_input = value if isinstance(value, str) else json.dumps(value)
            except Exception as exc:
                results.append({"role": role, "success": False, "error": str(exc)})
                break
        return results


def validate_json_schema(data: Any, schema: Dict[str, Any]) -> None:
    """
    Minimal JSON-Schema-subset validator (object/array/string/number/integer/
    boolean/null types, "properties", "required", "items") — no external
    dependency, covers the structured-output shapes a pipeline stage
    realistically needs. Raises SchemaValidationError on the first mismatch.
    """
    _validate_node(data, schema, path="$")


_TYPE_MAP = {
    "object": dict, "array": list, "string": str,
    "number": (int, float), "integer": int, "boolean": bool, "null": type(None),
}


def _validate_node(data: Any, schema: Dict[str, Any], path: str) -> None:
    expected = schema.get("type")
    if expected is not None:
        py_type = _TYPE_MAP.get(expected)
        if py_type is not None and not isinstance(data, py_type):
            raise SchemaValidationError(f"{path}: expected type '{expected}', got {type(data).__name__}")

    if expected == "object" or (expected is None and isinstance(data, dict)):
        if not isinstance(data, dict):
            return
        for required_key in schema.get("required", []):
            if required_key not in data:
                raise SchemaValidationError(f"{path}: missing required property '{required_key}'")
        properties = schema.get("properties", {})
        for key, subschema in properties.items():
            if key in data:
                _validate_node(data[key], subschema, path=f"{path}.{key}")

    elif expected == "array" or (expected is None and isinstance(data, list)):
        if not isinstance(data, list):
            return
        item_schema = schema.get("items")
        if item_schema is not None:
            for i, item in enumerate(data):
                _validate_node(item, item_schema, path=f"{path}[{i}]")


class BrowserAutomation:
    """Optional Playwright browser run with visual and runtime evidence."""

    def inspect(self, url: str, screenshot_path: str) -> Dict[str, Any]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Browser automation requires the optional Playwright dependency"
            ) from exc
        console_errors = []
        failed_requests = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.on(
                "console",
                lambda message: console_errors.append(message.text)
                if message.type == "error"
                else None,
            )
            page.on(
                "requestfailed",
                lambda request: failed_requests.append(
                    {"url": request.url, "failure": request.failure}
                ),
            )
            response = page.goto(url, wait_until="networkidle")
            destination = Path(screenshot_path).expanduser().resolve()
            destination.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(destination), full_page=True)
            title = page.title()
            browser.close()
        return {
            "url": url,
            "status": response.status if response else None,
            "title": title,
            "screenshot": str(destination),
            "consoleErrors": console_errors,
            "failedRequests": failed_requests,
        }
