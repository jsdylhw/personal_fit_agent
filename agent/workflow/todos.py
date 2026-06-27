"""In-memory todo planning support for the tool loop."""

from __future__ import annotations

import ast
import json
from typing import Any

from agent.context import AgentContext

TODO_STATUSES = {"pending", "in_progress", "completed"}
TODO_STATUS_ICONS = {
    "pending": " ",
    "in_progress": "\033[36m▸\033[0m",
    "completed": "\033[32m✓\033[0m",
}


def write_todos(context: AgentContext, todos: Any) -> dict[str, Any]:
    normalized, error = normalize_todos(todos)
    if error:
        return {"error": "invalid_todos", "message": error}
    context.current_todos = normalized
    context.todo_rounds_since_update = 0
    return {
        "status": "updated",
        "count": len(normalized),
        "todos": normalized,
    }


def normalize_todos(todos: Any) -> tuple[list[dict[str, str]], str | None]:
    if isinstance(todos, str):
        try:
            todos = json.loads(todos)
        except json.JSONDecodeError:
            try:
                todos = ast.literal_eval(todos)
            except (SyntaxError, ValueError):
                return [], "todos must be a list or JSON array string"

    if not isinstance(todos, list):
        return [], "todos must be a list"

    normalized: list[dict[str, str]] = []
    for index, item in enumerate(todos):
        if not isinstance(item, dict):
            return [], f"todos[{index}] must be an object"
        content = item.get("content")
        status = item.get("status")
        if not isinstance(content, str) or not content.strip():
            return [], f"todos[{index}] missing non-empty content"
        if status not in TODO_STATUSES:
            return [], f"todos[{index}] has invalid status {status!r}"
        normalized.append({"content": content.strip(), "status": str(status)})
    return normalized, None


def format_todos_for_prompt(todos: list[dict[str, Any]]) -> str:
    if not todos:
        return ""
    lines = ["当前 TODO:"]
    for todo in todos:
        status = todo.get("status", "pending")
        content = todo.get("content", "")
        lines.append(f"- [{status}] {content}")
    return "\n".join(lines)


def format_todos_for_terminal(todos: list[dict[str, Any]]) -> str:
    """Format todos like the s05 teaching agent terminal view."""
    if not todos:
        return "\n\033[33m## Current Tasks\033[0m\n  (empty)"

    lines = ["", "\033[33m## Current Tasks\033[0m"]
    for todo in todos:
        status = str(todo.get("status", "pending"))
        icon = TODO_STATUS_ICONS.get(status, " ")
        content = str(todo.get("content", ""))
        lines.append(f"  [{icon}] {content}")
    return "\n".join(lines)
