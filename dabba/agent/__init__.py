"""
Agent module for the dabba framework.

Provides a complete MCP-based agent system with tool calling,
multi-step planning, context management, and LLM integration.

Components:
    - Tool definitions and schemas (tool_schema)
    - Tool registration and dispatch (tool_registry)
    - MCP message parsing (mcp_handler)
    - Context window management (context_manager)
    - Multi-step planning (planner)
    - Plan execution (executor)
    - Main agent loop (agent_loop)
"""

from dabba.agent.tool_schema import (
    ToolCall,
    ToolDefinition,
    ToolParameter,
    ToolResult,
)
from dabba.agent.tool_registry import ToolRegistry
from dabba.agent.mcp_handler import McpHandler
from dabba.agent.context_manager import ContextManager, ConversationEntry
from dabba.config.agent_config import AgentConfig
from dabba.agent.planner import (
    ExecutionPlan,
    PlanStep,
    Planner,
    StepStatus,
)
from dabba.agent.executor import Executor, ExecutionStats
from dabba.agent.agent_loop import AgentLoop

Agent = AgentLoop
MCPHandler = McpHandler

__all__ = [
    "ToolCall",
    "ToolDefinition",
    "ToolParameter",
    "ToolResult",
    "ToolRegistry",
    "McpHandler",
    "ContextManager",
    "ConversationEntry",
    "ExecutionPlan",
    "PlanStep",
    "Planner",
    "StepStatus",
    "Executor",
    "ExecutionStats",
    "AgentLoop",
]
