"""
Task list tool for the dabba agent.

Lets the agent track its own multi-step work as a checklist —
create tasks, mark one in_progress, mark it completed, and so on.
The current list is kept in-process (per ToolRegistry instance) and
returned as JSON so the CLI/VSCode UI can render it as a live todo panel.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from dabba.agent.tool_schema import ToolDefinition, ToolParameter
from dabba.agent.tool_registry import ToolRegistry


VALID_STATUSES = ("pending", "in_progress", "completed")


@dataclass
class TodoStore:
    """Holds the current task list for one agent session."""
    items: List[Dict[str, str]] = field(default_factory=list)

    def set_all(self, items: List[Dict[str, str]]) -> List[Dict[str, str]]:
        cleaned = []
        for i, item in enumerate(items):
            content = str(item.get("content", "")).strip()
            status = str(item.get("status", "pending")).strip()
            if not content:
                continue
            if status not in VALID_STATUSES:
                status = "pending"
            cleaned.append({"id": str(item.get("id") or i), "content": content, "status": status})
        self.items = cleaned
        return self.items

    def update_status(self, task_id: str, status: str) -> List[Dict[str, str]]:
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid status '{status}'. Must be one of {VALID_STATUSES}.")
        found = False
        for item in self.items:
            if item["id"] == str(task_id):
                item["status"] = status
                found = True
        if not found:
            raise ValueError(f"No task with id '{task_id}'.")
        return self.items

    def to_dict(self) -> Dict:
        return {"todos": self.items}


def register_todo_tools(registry: ToolRegistry, store: Optional[TodoStore] = None) -> TodoStore:
    """
    Register the todo-list tool with a ToolRegistry.

    Args:
        registry: The tool registry to register with.
        store: Optional existing TodoStore to reuse (so the UI and the
            tool handler share the same live list).

    Returns:
        The TodoStore backing this registration — read it directly for
        display, or rely on the tool's return value.
    """
    store = store or TodoStore()

    def todo_write(todos: List[Dict[str, str]]) -> Dict:
        """Replace the entire task list. Use for the initial plan or a full rewrite."""
        items = store.set_all(todos)
        return {"todos": items}

    def todo_update(id: str, status: str) -> Dict:
        """Update a single task's status without touching the others."""
        items = store.update_status(id, status)
        return {"todos": items}

    registry.register(
        ToolDefinition(
            name="todo_write",
            description=(
                "Create or replace your task list for a multi-step request. "
                "Call this first when a task has 3+ distinct steps, so progress "
                "is visible. Each item needs 'content' and 'status' "
                "(pending, in_progress, or completed). Keep exactly one task "
                "in_progress at a time."
            ),
            parameters=[
                ToolParameter(
                    name="todos",
                    type="array",
                    description="Full list of task objects: [{id, content, status}, ...]",
                    items=ToolParameter(
                        name="todo",
                        type="object",
                        properties={
                            "id": ToolParameter(name="id", type="string", required=False, description="Stable id; auto-assigned if omitted."),
                            "content": ToolParameter(name="content", type="string", description="Imperative task description."),
                            "status": ToolParameter(name="status", type="string", description="pending | in_progress | completed"),
                        },
                    ),
                ),
            ],
            handler=todo_write,
            handler_sync=True,
            category="planning",
        )
    )

    registry.register(
        ToolDefinition(
            name="todo_update",
            description="Update one task's status (e.g. mark it in_progress when you start, completed when done).",
            parameters=[
                ToolParameter(name="id", type="string", description="The task id to update."),
                ToolParameter(name="status", type="string", description="New status: pending, in_progress, or completed."),
            ],
            handler=todo_update,
            handler_sync=True,
            category="planning",
        )
    )

    return store
