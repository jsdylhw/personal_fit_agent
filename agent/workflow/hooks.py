"""Agent loop hook 系统 — 实例化注册表, 支持并发安全.

使用:
  reg = HookRegistry()
  reg.register("pre_tool_use", my_hook)
  blocked = reg.trigger("pre_tool_use", block=block)
"""

from __future__ import annotations

from typing import Any, Callable


class HookRegistry:
    """每个 agent_loop 调用持有一个实例,避免全局状态."""

    def __init__(self):
        self._hooks: dict[str, list[Callable]] = {
            "pre_tool_use": [],
            "post_tool_use": [],
            "on_loop_end": [],
            "on_error": [],
        }

    def register(self, hook_point: str, callback: Callable) -> None:
        if hook_point not in self._hooks:
            raise ValueError(f"Unknown hook point: {hook_point}")
        self._hooks[hook_point].append(callback)

    def trigger(self, hook_point: str, **kwargs: Any) -> Any | None:
        for callback in self._hooks.get(hook_point, []):
            result = callback(**kwargs)
            if hook_point in ("pre_tool_use", "on_error") and result is not None:
                return result
        return None


# -- 内置 hook 工厂 -----------------------------------------------------

def make_permission_hook(context):
    """pre_tool_use: 权限检查."""
    from agent.workflow.permission import check_permission
    def _hook(block, **kw):
        perm = check_permission(block.get("name", ""), block.get("input", {}))
        if not perm.allowed:
            context.pending_action = {
                "tool": block["name"],
                "input": block.get("input", {}),
                "message": perm.reason,
            }
            return {"status": "needs_confirmation", "message": perm.block_message}
        return None
    return _hook


def make_guard_hook(context, allowed_cats, has_resolved_ref):
    """pre_tool_use: 依赖/合法性校验(在 permission 之前)."""
    from agent.workflow.tool_guard import guard_tool_call
    def _hook(block, **kw):
        guard = guard_tool_call(
            block.get("name", ""), block.get("input", {}),
            context=context, allowed_categories=allowed_cats,
            user_confirmed=False, has_resolved=has_resolved_ref["value"],
        )
        if not guard.allowed:
            return {"error": "guarded", "reason": guard.reason}
        return None
    return _hook


def make_state_update_hook(context, steps_taken, has_resolved_ref):
    """post_tool_use: 更新 context、track steps、更新 has_resolved."""
    def _hook(block, output, **kw):
        name = block.get("name", "")
        context.last_tool_result = {"step_name": name, "result": output}
        steps_taken.append({"tool": name, "input": block.get("input", {})})
        if name.startswith("resolve_"):
            has_resolved_ref["value"] = True
    return _hook


def make_verbose_pre_hook(step_counter_ref):
    """pre_tool_use: verbose 日志."""
    def _hook(block, **kw):
        import json
        args = block.get("input") or {}
        fmt = ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in args.items()) or "no args"
        _log(f"  [{step_counter_ref['value']}] \033[33m→\033[0m \033[1m{block.get('name')}\033[0m({fmt})")
        return None
    return _hook


def make_verbose_post_hook(step_counter_ref):
    """post_tool_use: verbose 日志."""
    def _hook(block, output, **kw):
        import json
        text = json.dumps(output, ensure_ascii=False, default=str)[:120]
        _log(f"  [{step_counter_ref['value']}] \033[32m←\033[0m \033[1m{block.get('name')}\033[0m {text}")
    return _hook


def install_all_hooks(reg: HookRegistry, context, allowed_cats, has_resolved_ref, steps_taken, *, verbose=False) -> None:
    """安装 run_tool_loop 所需的全部 hooks.

    顺序: pre → guard(合法性),然后 permission(审批); post → state_update.
    """
    step_ref = {"value": 0}
    # pre: guard 先(合法性), permission 后(审批)
    reg.register("pre_tool_use", make_guard_hook(context, allowed_cats, has_resolved_ref))
    reg.register("pre_tool_use", make_permission_hook(context))
    # post: state_update
    reg.register("post_tool_use", make_state_update_hook(context, steps_taken, has_resolved_ref))
    if verbose:
        reg.register("pre_tool_use", make_verbose_pre_hook(step_ref))
        reg.register("post_tool_use", make_verbose_post_hook(step_ref))


def _log(msg: str) -> None:
    import sys
    print(f"\033[2m[agent]\033[0m {msg}", file=sys.stderr, flush=True)
