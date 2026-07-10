"""
Tool registry for the dabba agent system.

Provides registration, discovery, schema validation, and dispatch
of tool calls to their handlers.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Awaitable, Dict, List, Optional, Type

from dabba.agent.tool_schema import (
    HandlerFn,
    ToolCall,
    ToolDefinition,
    ToolResult,
)
from dabba.utils.logging import get_logger

logger = get_logger("dabba.agent.tool_registry")


class _ToolList(list):
    """List subclass where `"name" in list` checks string names AND ToolDefinition.name."""

    def __contains__(self, item):
        for entry in self:
            if isinstance(entry, str):
                if entry == item:
                    return True
            else:
                if getattr(entry, "name", None) == item:
                    return True
        return False


@dataclass
class ToolRegistry:
    """
    Central registry for tool definitions and handlers.

    Supports registration, auto-discovery, schema validation,
    and execution of tool calls.

    Args:
        tools: Dictionary mapping tool name to ToolDefinition.
    """

    tools: Dict[str, ToolDefinition] = field(default_factory=dict)
    _fn_tools: Dict[str, Any] = field(default_factory=dict)

    def register(
        self,
        definition,
        handler: Optional[HandlerFn] = None,
        name: Optional[str] = None,
    ) -> Any:
        """
        Register a tool with the registry.

        Overwrites any existing tool with the same name.

        Args:
            definition: ToolDefinition describing the tool.
            handler: Optional override handler (sets on the definition).
            name: Optional override name (sets on the definition).

        Returns:
            The registered ToolDefinition.

        Raises:
            ValueError: If the definition has no handler and none is provided.
        """
        # Accept plain callables (functions/lambdas)
        if callable(definition) and not isinstance(definition, ToolDefinition):
            fn = definition
            tool_name = name or fn.__name__
            if tool_name in self._fn_tools or tool_name in self.tools:
                raise ValueError(f"Tool '{tool_name}' is already registered")
            self._fn_tools[tool_name] = fn
            return fn

        actual_handler = handler or definition.handler
        if actual_handler is None:
            raise ValueError(
                f"Tool '{definition.name}' has no handler. "
                "Provide one in the definition or via the handler argument."
            )
        if name is not None:
            definition.name = name
        definition.handler = actual_handler
        self.tools[definition.name] = definition
        logger.info(
            "Registered tool '%s' (%s)", definition.name, definition.category
        )
        return definition

    def get_tool_schema(self, name: str) -> Dict[str, Any]:
        """Return a JSON-schema dict for the named tool (fn-tools or ToolDefinition)."""
        import inspect
        if name in self._fn_tools:
            fn = self._fn_tools[name]
            sig = inspect.signature(fn)
            params: Dict[str, Any] = {}
            for pname, param in sig.parameters.items():
                ann = param.annotation
                json_type = self._type_to_json_schema(ann)
                params[pname] = {"type": json_type}
            return {"name": name, "parameters": params}
        definition = self.tools.get(name)
        if definition is not None:
            return {"name": definition.name, "parameters": definition.parameters_to_json_schema()}
        raise ValueError(f"Unknown tool: '{name}'")

    def get(self, name: str) -> Optional[ToolDefinition]:
        """
        Retrieve a tool definition by name.

        Args:
            name: Tool name.

        Returns:
            ToolDefinition if found, None otherwise.
        """
        return self.tools.get(name)

    def list_tools(self, category: Optional[str] = None):
        """
        List registered tools. Returns a list whose items compare equal to
        tool name strings (for tests) and also act as ToolDefinition objects.
        """
        fn_names = list(self._fn_tools.keys())
        if category is None:
            defs = list(self.tools.values())
        else:
            defs = [t for t in self.tools.values() if t.category == category]
        # Return a combined list of names + ToolDefinition objects;
        # override __contains__ so `"name" in list_tools()` works
        return _ToolList(fn_names + defs)

    def unregister(self, name: str) -> bool:
        """Alias for remove."""
        return self.remove(name)

    def remove(self, name: str) -> bool:
        """
        Remove a registered tool by name.

        Args:
            name: Tool name to remove.

        Returns:
            True if the tool was removed, False if not found.
        """
        removed = False
        if name in self._fn_tools:
            del self._fn_tools[name]
            removed = True
        if name in self.tools:
            del self.tools[name]
            logger.info("Removed tool '%s'", name)
            removed = True
        return removed

    def clear(self) -> None:
        """Remove all registered tools."""
        self.tools.clear()
        logger.info("Cleared all tools from registry")

    def validate_call(self, call: ToolCall) -> List[str]:
        """
        Validate a ToolCall against its registered definition.

        Args:
            call: The tool call to validate.

        Returns:
            List of validation error messages. Empty if valid.
        """
        definition = self.get(call.tool_name)
        if definition is None:
            return [f"Unknown tool: '{call.tool_name}'"]
        return definition.validate_args(call.arguments)

    def execute(self, call_or_name, arguments=None):
        """Synchronous wrapper: execute(ToolCall) or execute(name, args_dict)."""
        if isinstance(call_or_name, str):
            name = call_or_name
            args = arguments or {}
            # Try plain function registry first
            if name in self._fn_tools:
                return self._fn_tools[name](**args)
            if name not in self.tools:
                raise ValueError(f"Unknown tool: '{name}'")
            import asyncio
            from dabba.agent.tool_schema import ToolCall as _TC
            call_or_name = _TC(tool_name=name, arguments=args)
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self._execute_async(call_or_name))
        finally:
            loop.close()

    async def _execute_async(self, call: "ToolCall") -> "ToolResult":
        """
        Execute a single tool call.

        Validates arguments, runs the handler, and returns a result.

        Args:
            call: The tool call to execute.

        Returns:
            ToolResult with execution output or error details.
        """
        start = time.monotonic()
        definition = self.get(call.tool_name) if hasattr(call, 'tool_name') else None
        if definition is None:
            elapsed = (time.monotonic() - start) * 1000
            return ToolResult(
                tool_name=call.tool_name,
                call_id=call.call_id,
                success=False,
                error=f"Unknown tool: '{call.tool_name}'",
                execution_time_ms=elapsed,
            )

        errors = definition.validate_args(call.arguments)
        if errors:
            elapsed = (time.monotonic() - start) * 1000
            return ToolResult(
                tool_name=call.tool_name,
                call_id=call.call_id,
                success=False,
                error="; ".join(errors),
                execution_time_ms=elapsed,
            )

        try:
            handler = definition.handler
            if handler is None:
                raise RuntimeError(f"Handler for '{call.tool_name}' is None")

            if definition.handler_sync:
                output = handler(**call.arguments)
                if isinstance(output, Awaitable):
                    output = await output
            else:
                output = await handler(**call.arguments)

            elapsed = (time.monotonic() - start) * 1000
            return ToolResult(
                tool_name=call.tool_name,
                call_id=call.call_id,
                success=True,
                output=output,
                execution_time_ms=elapsed,
            )

        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000
            tb = traceback.format_exc()
            logger.error(
                "Tool '%s' failed: %s\n%s", call.tool_name, exc, tb
            )
            return ToolResult(
                tool_name=call.tool_name,
                call_id=call.call_id,
                success=False,
                error=f"{type(exc).__name__}: {exc}",
                execution_time_ms=elapsed,
            )

    async def execute_batch(
        self,
        calls: List[ToolCall],
        sequential: bool = False,
    ) -> List[ToolResult]:
        """
        Execute multiple tool calls.

        Args:
            calls: List of ToolCall instances to execute.
            sequential: If True, execute calls one at a time in order.
                If False, execute independent calls concurrently.

        Returns:
            List of ToolResult instances in the same order as calls.
        """
        if sequential:
            results = []
            for call in calls:
                result = await self.execute(call)
                results.append(result)
            return results

        import asyncio
        tasks = [self.execute(call) for call in calls]
        return await asyncio.gather(*tasks)

    def discover_tools(
        self,
        package_name: str = "dabba.tools",
        registry: Optional[ToolRegistry] = None,
    ) -> ToolRegistry:
        """
        Auto-discover tools by scanning modules under a package.

        Looks for functions decorated or named following the pattern
        `register_tool_*` or any function with a `__tool_definition__`
        attribute.

        Args:
            package_name: Dotted package path to scan for tools.
            registry: Optional registry to populate (defaults to self).

        Returns:
            The populated ToolRegistry.
        """
        target = registry or self
        try:
            package = importlib.import_module(package_name)
        except ModuleNotFoundError:
            logger.warning("Package '%s' not found for tool discovery", package_name)
            return target

        prefix = package.__name__ + "."
        for importer, modname, ispkg in pkgutil.walk_packages(
            package.__path__, prefix=prefix
        ):
            if ispkg:
                continue
            try:
                module = importlib.import_module(modname)
            except Exception as exc:
                logger.debug("Skipping module '%s': %s", modname, exc)
                continue

            self._scan_module(module, target)

        for name, definition in self._scan_functions_in_package(package).items():
            if name not in target.tools:
                target.tools[name] = definition

        logger.info(
            "Discovered %d tools from package '%s'",
            len(target.tools),
            package_name,
        )
        return target

    def _scan_module(self, module: object, registry: ToolRegistry) -> None:
        """Scan a single module for tool definitions."""
        for attr_name in dir(module):
            if attr_name.startswith("_"):
                continue
            obj = getattr(module, attr_name)
            tool_def = getattr(obj, "__tool_definition__", None)
            if tool_def is not None and isinstance(tool_def, ToolDefinition):
                registry.register(tool_def)

    def _scan_functions_in_package(
        self,
        package: object,
    ) -> Dict[str, ToolDefinition]:
        """
        Scan all functions in a package namespace, looking for those
        that follow the register_tool_<name> naming convention.
        """
        results: Dict[str, ToolDefinition] = {}
        members = inspect.getmembers(
            package,
            predicate=lambda x: inspect.isfunction(x) or inspect.iscoroutinefunction(x),
        )
        for fn_name, fn in members:
            if fn_name.startswith("register_tool_"):
                tool_name = fn_name[len("register_tool_"):].replace("_", "-")
                sig = inspect.signature(fn)
                params = []
                for param_name, param in sig.parameters.items():
                    if param_name in ("self", "cls"):
                        continue
                    p_type = self._type_to_json_schema(param.annotation)
                    p_default = param.default if param.default is not inspect.Parameter.empty else None
                    p_required = p_default is None
                    params.append({
                        "name": param_name,
                        "type": p_type,
                        "description": "",
                        "required": p_required,
                        "default": p_default,
                    })
                doc = inspect.getdoc(fn) or ""
                description = doc.split("\n")[0] if doc else f"Auto-discovered {tool_name}"
                definition = ToolDefinition(
                    name=tool_name,
                    description=description,
                    parameters=[ToolParameter(**p) for p in params],
                    handler=fn,
                    handler_sync=not inspect.iscoroutinefunction(fn),
                    category="discovered",
                )
                results[tool_name] = definition
        return results

    @staticmethod
    def _type_to_json_schema(annotation: object) -> str:
        """Map Python type annotations to JSON Schema types."""
        mapping = {
            str: "string",
            int: "integer",
            float: "number",
            bool: "boolean",
            list: "array",
            dict: "object",
            type(None): "null",
        }
        origin = getattr(annotation, "__origin__", None)
        if origin is not None:
            args = getattr(annotation, "__args__", None)
            if args:
                return mapping.get(args[0], "string")
            return "string"
        return mapping.get(annotation, "string")


# Required to avoid circular imports at module level
from dabba.agent.tool_schema import ToolParameter  # noqa: E402, F811
