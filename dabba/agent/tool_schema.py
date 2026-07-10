"""
Tool definition schemas for the dabba agent system.

Provides dataclasses for defining tools, their parameters,
tool calls, and tool execution results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

HandlerFn = Callable[..., Union[Any, Awaitable[Any]]]


@dataclass
class ToolParameter:
    """
    Definition of a single tool parameter.

    Args:
        name: Parameter name (must be a valid Python identifier).
        type: JSON Schema type string (e.g., "string", "integer", "boolean", "array", "object").
        description: Human-readable description of the parameter.
        required: Whether the parameter is required for tool invocation.
        default: Default value if the parameter is optional.
        items: If type is "array", schema of array items.
        properties: If type is "object", dict of property name -> ToolParameter.
    """

    name: str
    type: str
    description: str = ""
    required: bool = True
    default: Any = None
    items: Optional[ToolParameter] = None
    properties: Optional[Dict[str, ToolParameter]] = None

    def to_json_schema(self) -> Dict[str, Any]:
        """
        Convert this parameter to a JSON Schema fragment.

        Returns:
            A dictionary conforming to JSON Schema draft-07.
        """
        schema: Dict[str, Any] = {"type": self.type, "description": self.description}
        if self.default is not None:
            schema["default"] = self.default
        if self.type == "array" and self.items is not None:
            schema["items"] = self.items.to_json_schema()
        if self.type == "object" and self.properties is not None:
            schema["properties"] = {
                k: v.to_json_schema() for k, v in self.properties.items()
            }
            schema["additionalProperties"] = False
        if self.default is not None:
            schema["default"] = self.default
        return schema


@dataclass
class ToolDefinition:
    """
    Complete definition of a callable tool.

    Args:
        name: Unique tool name (used to invoke the tool).
        description: Human-readable description of what the tool does.
        parameters: List of parameter definitions.
        handler: Callable that executes the tool logic. Receives the same
            keyword arguments specified in parameters.
        handler_sync: If True, the handler is synchronous; otherwise async.
        category: Optional category for grouping tools in listings.
    """

    name: str
    description: str
    parameters: List[ToolParameter] = field(default_factory=list)
    handler: Optional[HandlerFn] = None
    handler_sync: bool = True
    category: str = "general"

    def parameters_to_json_schema(self) -> Dict[str, Any]:
        """
        Convert parameter list to a JSON Schema object.

        Returns:
            A JSON Schema object with 'type', 'properties', and 'required'.
        """
        properties = {}
        required = []
        for param in self.parameters:
            properties[param.name] = param.to_json_schema()
            if param.required:
                required.append(param.name)
        schema: Dict[str, Any] = {
            "type": "object",
            "properties": properties,
        }
        if required:
            schema["required"] = required
        return schema

    def validate_args(self, args: Dict[str, Any]) -> List[str]:
        """
        Validate the provided arguments against the parameter definitions.

        Args:
            args: Dictionary of argument name -> value.

        Returns:
            List of validation error messages (empty if valid).
        """
        errors: List[str] = []
        param_map = {p.name: p for p in self.parameters}
        for param in self.parameters:
            if param.required and param.name not in args:
                errors.append(f"Missing required parameter: '{param.name}'")
        for key in args:
            if key not in param_map:
                errors.append(f"Unknown parameter: '{key}'")
        return errors


@dataclass
class ToolCall:
    """
    Represents a single tool invocation request.

    Args:
        tool_name: Name of the tool to invoke.
        arguments: Dictionary of argument names to values.
        call_id: Unique identifier for this call (used for result correlation).
    """

    tool_name: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    call_id: str = ""

    def __post_init__(self) -> None:
        if not self.call_id:
            import uuid
            self.call_id = uuid.uuid4().hex[:12]


@dataclass
class ToolResult:
    """
    Result of executing a ToolCall.

    Args:
        tool_name: Name of the tool that was executed.
        call_id: Matches the ToolCall.call_id.
        success: Whether the tool execution completed without error.
        output: The return value of the tool handler.
        error: Error message if success is False.
        execution_time_ms: Wall-clock time of execution in milliseconds.
    """

    tool_name: str
    call_id: str = ""
    success: bool = True
    output: Any = None
    error: str = ""
    execution_time_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to a dictionary suitable for LLM consumption."""
        return {
            "tool": self.tool_name,
            "call_id": self.call_id,
            "success": self.success,
            "output": self._serialize_output(self.output) if self.success else None,
            "error": self.error if not self.success else None,
        }

    @staticmethod
    def _serialize_output(output: Any) -> str:
        """
        Serialize tool output for LLM consumption.

        Converts various output types to a string representation.

        Args:
            output: Raw output from the tool handler.

        Returns:
            String representation of the output.
        """
        if isinstance(output, str):
            max_len = 100_000
            if len(output) > max_len:
                return output[:max_len] + f"\n... [truncated at {max_len} chars]"
            return output
        if isinstance(output, (list, dict)):
            import json
            try:
                text = json.dumps(output, indent=2, default=str)
                if len(text) > 100_000:
                    text = text[:100_000] + f"\n... [truncated at 100000 chars]"
                return text
            except (TypeError, ValueError):
                return str(output)
        if isinstance(output, bytes):
            return output.decode("utf-8", errors="replace")
        return str(output)
