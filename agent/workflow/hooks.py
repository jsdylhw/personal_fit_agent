"""Hard-coded hooks used by the agent tool loop."""

from __future__ import annotations

import copy
from typing import Any

from agent.workflow.tool_result import is_failed_tool_output


class ToolLoopHooks:
    """Fixed hook order for the tool loop."""

    def __init__(self, context, allowed_cats, has_resolved_ref, steps_taken, *, verbose=False):
        self.context = context
        self.allowed_cats = allowed_cats
        self.has_resolved_ref = has_resolved_ref
        self.steps_taken = steps_taken
        self.verbose = verbose

    def before_llm_call(self) -> dict[str, str] | None:
        if not self.context.current_todos:
            return None
        if self.context.todo_rounds_since_update < 3:
            return None
        self.context.todo_rounds_since_update = 0
        return {
            "role": "user",
            "content": "<reminder>请调用 todo_write 更新当前 TODO 状态。</reminder>",
        }

    def on_tool_round(self) -> None:
        self.context.todo_rounds_since_update += 1

    def on_error(self, block: dict[str, Any], error: Exception) -> dict[str, Any] | None:
        return None

    def on_loop_end(self, *, messages: list[dict[str, Any]], response: dict[str, Any], steps: int) -> None:
        return None

    def remember_permission_pause(
        self,
        block: dict[str, Any],
        *,
        messages: list[dict[str, Any]],
        results_before_pause: list[dict[str, Any]],
        remaining_blocks: list[dict[str, Any]],
        system: str,
        max_tokens: int,
        max_steps: int,
        step_count: int,
    ) -> None:
        if not self.context.pending_action:
            return
        self.context.pending_action["resume"] = {
            "messages": copy.deepcopy(messages),
            "block": copy.deepcopy(block),
            "results_before_pause": copy.deepcopy(results_before_pause),
            "remaining_blocks": copy.deepcopy(remaining_blocks),
            "allowed_categories": list(self.allowed_cats),
            "has_resolved": self.has_resolved_ref["value"],
            "system": system,
            "max_tokens": max_tokens,
            "max_steps": max_steps,
            "step_count": step_count,
        }

    def pre_tool_use(self, block: dict[str, Any], *, step_count: int) -> dict[str, Any] | None:
        if self.verbose:
            self._log_pre_tool(block, step_count=step_count)

        guard = self._guard_tool_call(block)
        if guard is not None:
            return guard

        return self._check_permission(block)

    def post_tool_use(self, block: dict[str, Any], output: Any, *, step_count: int) -> None:
        name = block.get("name", "")
        self.context.last_tool_result = {"step_name": name, "result": output}
        self.steps_taken.append({"tool": name, "input": block.get("input", {})})
        if is_failed_tool_output(output):
            self.context.last_failed_action = {"tool": name, "input": block.get("input", {}) or {}}
        elif name == (self.context.last_failed_action or {}).get("tool"):
            self.context.last_failed_action = None
        if name.startswith("resolve_"):
            self.has_resolved_ref["value"] = True
        if self.verbose:
            self._log_post_tool(block, output, step_count=step_count)

    def _guard_tool_call(self, block: dict[str, Any]) -> dict[str, Any] | None:
        from agent.workflow.tool_guard import guard_tool_call

        guard = guard_tool_call(
            block.get("name", ""),
            block.get("input", {}),
            context=self.context,
            allowed_categories=self.allowed_cats,
            user_confirmed=False,
            has_resolved=self.has_resolved_ref["value"],
        )
        if not guard.allowed:
            return {"error": "guarded", "reason": guard.reason}
        return None

    def _check_permission(self, block: dict[str, Any]) -> dict[str, Any] | None:
        from agent.workflow.permission import PermissionDecision, check_permission

        tool_input = block.get("input") if isinstance(block.get("input"), dict) else {}
        perm = check_permission(block.get("name", ""), tool_input)
        if perm.allowed:
            return None
        if perm.decision == PermissionDecision.DENY:
            return {"error": "permission_denied", "reason": perm.reason}

        self.context.pending_action = {
            "tool": block["name"],
            "input": tool_input,
            "message": perm.reason,
        }
        return {"status": "needs_confirmation", "message": perm.block_message}

    @staticmethod
    def _log_pre_tool(block: dict[str, Any], *, step_count: int) -> None:
        fmt = _format_tool_args(block)
        _log(f"  [{step_count}] \033[33m→\033[0m \033[1m{block.get('name')}\033[0m({fmt})")

    @staticmethod
    def _log_post_tool(block: dict[str, Any], output: Any, *, step_count: int) -> None:
        if block.get("name") == "todo_write":
            _log_todos(output)
            return
        _log(f"  [{step_count}] \033[32m←\033[0m \033[1m{block.get('name')}\033[0m {_summarize_output(output)}")


def _log(msg: str) -> None:
    import sys
    print(f"\033[2m[agent]\033[0m {msg}", file=sys.stderr, flush=True)


def _log_raw(msg: str) -> None:
    import sys
    print(msg, file=sys.stderr, flush=True)


def _format_tool_args(block: dict[str, Any]) -> str:
    import json

    args = block.get("input") if isinstance(block.get("input"), dict) else {}
    if block.get("name") == "todo_write":
        todos = args.get("todos")
        if isinstance(todos, list):
            return f"{len(todos)} tasks"
        return "todos"
    return ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in args.items()) or "no args"


def _summarize_output(output: Any) -> str:
    import json

    if isinstance(output, dict):
        parts = []
        for key in ("status", "count", "total", "downloaded", "skipped", "strava_activity_id"):
            if key in output:
                parts.append(f"{key}={json.dumps(output[key], ensure_ascii=False, default=str)}")
        if parts:
            return " ".join(parts)
    return json.dumps(output, ensure_ascii=False, default=str)[:120]


def _log_todos(output: Any) -> None:
    if not isinstance(output, dict):
        _log(f"  \033[32m←\033[0m \033[1mtodo_write\033[0m {_summarize_output(output)}")
        return

    todos = output.get("todos")
    if not isinstance(todos, list):
        _log(f"  \033[32m←\033[0m \033[1mtodo_write\033[0m {_summarize_output(output)}")
        return

    from agent.workflow.todos import format_todos_for_terminal

    _log_raw(format_todos_for_terminal(todos))
    _log(f"  \033[32m←\033[0m \033[1mtodo_write\033[0m Updated {len(todos)} tasks")
