"""Agent tool-use loop.

agent_loop() — 纯 tool-use 循环, 接收 ToolLoopHooks 实例.
run_tool_loop() — 便捷入口: intent/context/handlers 组装.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.chat_logger import new_session_id, write_main_agent_markdown_log
from agent.context import AgentContext
from core.fit_paths import resolve_fit_path as _resolve_fit_path
from agent.llm import AnthropicMessagesClient, build_tool_result_block
from agent.tools import MAIN_AGENT_TOOLS, render_anthropic_tools
from agent.tools.spec import CATEGORY_PLANNING
from agent.main_agent.intent import route_intent, intent_tool_categories
from agent.main_agent.hooks import ToolLoopHooks
from agent.main_agent.tools import TOOL_HANDLERS
from agent.main_agent.turn_control import handle_control_turn, is_confirm

MAX_TOOL_STEPS = 10


# -- 核心: agent_loop -------------------------------------------------

def agent_loop(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]],
    handlers: dict[str, Any],
    hooks: ToolLoopHooks,
    system: str = "",
    max_tokens: int = 4096,
    max_steps: int = MAX_TOOL_STEPS,
) -> int:
    """纯 tool-use loop. 返回 step_count. messages 原地修改."""
    client = AnthropicMessagesClient()
    step_count = 0

    while True:
        step_count += 1
        if step_count > max_steps:
            break

        reminder = hooks.before_llm_call()
        if isinstance(reminder, dict):
            messages.append(reminder)

        response = client.create_messages(
            system=system, messages=messages,
            max_tokens=max_tokens, tools=tools,
        )
        messages.append({"role": "assistant", "content": response.get("content") or []})

        if response.get("stop_reason") != "tool_use":
            hooks.on_loop_end(messages=messages, response=response, steps=step_count - 1)
            return step_count

        hooks.on_tool_round()

        results: list[dict[str, Any]] = []
        content_blocks = response.get("content") or []
        for idx, block in enumerate(content_blocks):
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue

            blocked = hooks.pre_tool_use(block, step_count=step_count)
            if blocked:
                if blocked.get("status") == "needs_confirmation":
                    remaining_blocks = [
                        b for b in content_blocks[idx + 1:]
                        if isinstance(b, dict) and b.get("type") == "tool_use"
                    ]
                    hooks.remember_permission_pause(
                        block,
                        messages=messages,
                        results_before_pause=results,
                        remaining_blocks=remaining_blocks,
                        system=system,
                        max_tokens=max_tokens,
                        max_steps=max_steps,
                        step_count=step_count,
                    )
                    return step_count
                results.append(build_tool_result_block(block["id"], json.dumps(blocked, ensure_ascii=False)))
                continue

            handler = handlers.get(block["name"])
            tool_input = block.get("input") if isinstance(block.get("input"), dict) else {}
            try:
                output = handler(tool_input, hooks.context) if handler else {"error": "unknown_tool", "name": block["name"]}
            except Exception as exc:
                err = hooks.on_error(block, exc)
                output = err or {"error": type(exc).__name__, "message": str(exc)}

            hooks.post_tool_use(block, output, step_count=step_count)

            if (
                isinstance(output, dict)
                and output.get("status") == "needs_confirmation"
                and hooks.context.pending_action
            ):
                remaining_blocks = [
                    b for b in content_blocks[idx + 1:]
                    if isinstance(b, dict) and b.get("type") == "tool_use"
                ]
                hooks.remember_permission_pause(
                    block,
                    messages=messages,
                    results_before_pause=results,
                    remaining_blocks=remaining_blocks,
                    system=system,
                    max_tokens=max_tokens,
                    max_steps=max_steps,
                    step_count=step_count,
                )
                return step_count

            results.append(build_tool_result_block(block["id"], json.dumps(output, ensure_ascii=False, default=str)))

        messages.append({"role": "user", "content": results})

    return step_count


# -- 便捷入口: run_tool_loop --------------------------------------------

def run_tool_loop(
    message: str,
    *,
    fit_path: str | Path | None = None,
    use_history: bool = True,
    max_tokens: int = 4096,
    verbose: bool = False,
    context: AgentContext | None = None,
) -> dict[str, Any]:
    """组装 intent/context/handlers → agent_loop()."""
    context = _prepare_context(message, fit_path=fit_path, use_history=use_history, context=context)

    if context.pending_action and is_confirm(message) and context.pending_action.get("resume"):
        pending = context.pending_action
        context.pending_action = None
        return _resume_confirmed_turn(pending, context, verbose=verbose, default_max_tokens=max_tokens)

    control_result = handle_control_turn(message, context, verbose=verbose)
    if control_result is not None:
        return control_result

    intent = route_intent(message)
    allowed_cats = intent_tool_categories(intent)

    step_count, steps_taken = _run_agent_turn(
        message,
        intent,
        allowed_cats,
        context,
        verbose,
        max_tokens,
        fit_path=fit_path,
        use_history=use_history,
    )
    return _build_result(intent, context, message, fit_path, use_history, step_count, steps_taken)


def _prepare_context(
    message: str,
    *,
    fit_path: str | Path | None,
    use_history: bool,
    context: AgentContext | None,
) -> AgentContext:
    if context is not None:
        context.messages.append({"role": "user", "content": message})
        return context

    current_fit = _resolve_fit_path(fit_path) if fit_path else None
    return AgentContext(
        session_id=new_session_id("tool_loop"),
        current_fit_file=current_fit,
        history_enabled=use_history,
        messages=[{"role": "user", "content": message}],
    )


def _run_agent_turn(message, intent, allowed_cats, context, verbose, max_tokens, *, fit_path=None, use_history=True):
    """执行 agent_loop 并同步 messages 回 context. 返回 step_count."""
    tool_categories = set(allowed_cats)
    tool_categories.add(CATEGORY_PLANNING)
    tools = [render_anthropic_tools([t])[0] for t in MAIN_AGENT_TOOLS if t.category in tool_categories]
    handlers = TOOL_HANDLERS
    system = _build_system_prompt(intent)
    has_resolved = {"value": bool(context.current_fit_file)}
    steps_taken: list[dict] = []

    messages = list(context.messages)
    preamble = _build_state_preamble(context)
    if preamble:
        messages = [{"role": "user", "content": preamble}] + messages

    hooks = ToolLoopHooks(context, tool_categories, has_resolved, steps_taken, verbose=verbose)
    if verbose:
        _log_hdr(message, intent, len(tools), bool(context.current_fit_file))

    step_count = agent_loop(messages, tools=tools, handlers=handlers, hooks=hooks,
                            system=system, max_tokens=max_tokens)

    if context.pending_action and isinstance(context.pending_action.get("resume"), dict):
        context.pending_action["resume"]["intent"] = intent
        context.pending_action["resume"]["message"] = message
        context.pending_action["resume"]["fit_path"] = fit_path
        context.pending_action["resume"]["use_history"] = use_history

    _sync_messages_to_context(context, messages)
    return step_count, steps_taken


def _resume_confirmed_turn(pending, context, *, verbose: bool, default_max_tokens: int):
    """Execute the confirmed tool and continue the paused tool loop."""
    from agent.main_agent.permission import check_permission

    resume = pending.get("resume") if isinstance(pending.get("resume"), dict) else {}
    block = resume.get("block") or {
        "type": "tool_use",
        "id": "confirmed-tool",
        "name": pending.get("tool"),
        "input": pending.get("input") or {},
    }
    tool_name = str(pending.get("tool") or block.get("name") or "")
    tool_input = pending.get("input") if isinstance(pending.get("input"), dict) else {}

    permission = check_permission(tool_name, tool_input, has_confirmed=True)
    if not permission.allowed:
        answer = permission.block_message or f"权限拒绝: {permission.reason}"
        context.messages.append({"role": "assistant", "content": [{"type": "text", "text": answer}]})
        return {"answer": answer, "status": "permission_denied", "context": context, "intent": "confirmed", "steps": []}

    handlers = TOOL_HANDLERS
    handler = handlers.get(tool_name)
    if not handler:
        answer = f"未知工具: {tool_name}"
        context.messages.append({"role": "assistant", "content": [{"type": "text", "text": answer}]})
        return {"answer": answer, "status": "failed", "context": context, "intent": "confirmed", "steps": []}

    allowed_cats = set(resume.get("allowed_categories") or [])
    allowed_cats.add(CATEGORY_PLANNING)
    tools = [render_anthropic_tools([t])[0] for t in MAIN_AGENT_TOOLS if t.category in allowed_cats]
    messages = list(resume.get("messages") or context.messages)
    results = list(resume.get("results_before_pause") or [])
    steps_taken: list[dict] = []
    has_resolved = {"value": bool(resume.get("has_resolved"))}
    hooks = ToolLoopHooks(context, allowed_cats, has_resolved, steps_taken, verbose=verbose)

    try:
        output = handler(tool_input, context)
    except Exception as exc:
        err = hooks.on_error(block, exc)
        output = err or {"error": type(exc).__name__, "message": str(exc)}

    hooks.post_tool_use(block, output, step_count=int(resume.get("step_count") or 0))
    results.append(build_tool_result_block(block["id"], json.dumps(output, ensure_ascii=False, default=str)))
    for skipped in resume.get("remaining_blocks") or []:
        results.append(build_tool_result_block(
            skipped["id"],
            json.dumps({"status": "skipped", "reason": "paused_for_permission_confirmation"}, ensure_ascii=False),
        ))
    messages.append({"role": "user", "content": results})

    if verbose:
        from agent.main_agent.hooks import _log
        _log(f"  [确认执行] \033[1m{tool_name}\033[0m {json.dumps(output, ensure_ascii=False, default=str)[:120]}")

    max_steps = int(resume.get("max_steps") or MAX_TOOL_STEPS)
    used_steps = int(resume.get("step_count") or 0)
    remaining_steps = max_steps - used_steps
    if remaining_steps <= 0:
        _sync_messages_to_context(context, messages)
        return _build_result(
            resume.get("intent") or "confirmed",
            context,
            resume.get("message") or f"确认执行 {tool_name}",
            resume.get("fit_path"),
            bool(resume.get("use_history", context.history_enabled)),
            max_steps + 1,
            steps_taken,
        )

    step_count = agent_loop(
        messages,
        tools=tools,
        handlers=handlers,
        hooks=hooks,
        system=str(resume.get("system") or ""),
        max_tokens=int(resume.get("max_tokens") or default_max_tokens),
        max_steps=remaining_steps,
    )

    intent = resume.get("intent") or "confirmed"
    if context.pending_action and isinstance(context.pending_action.get("resume"), dict):
        context.pending_action["resume"]["intent"] = intent
        context.pending_action["resume"]["message"] = resume.get("message") or f"确认执行 {tool_name}"
        context.pending_action["resume"]["fit_path"] = resume.get("fit_path")
        context.pending_action["resume"]["use_history"] = bool(resume.get("use_history", context.history_enabled))

    _sync_messages_to_context(context, messages)
    return _build_result(
        intent,
        context,
        resume.get("message") or f"确认执行 {tool_name}",
        resume.get("fit_path"),
        bool(resume.get("use_history", context.history_enabled)),
        used_steps + step_count,
        steps_taken,
    )


def _sync_messages_to_context(context, messages):
    """同步长期对话历史,裁剪 tool_use/tool_result 中间态."""
    clean = []
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, str) and content.startswith("[本轮状态]"):
            continue
        if _is_tool_result_message(m):
            continue
        if _has_tool_use_block(m):
            text_blocks = [
                b for b in (content or [])
                if isinstance(b, dict) and b.get("type") == "text" and b.get("text")
            ]
            if text_blocks:
                clean.append({"role": "assistant", "content": text_blocks})
            continue
        clean.append(m)
    context.messages = clean


def _is_tool_result_message(message: dict[str, Any]) -> bool:
    content = message.get("content")
    return (
        message.get("role") == "user"
        and isinstance(content, list)
        and any(isinstance(block, dict) and block.get("type") == "tool_result" for block in content)
    )


def _has_tool_use_block(message: dict[str, Any]) -> bool:
    content = message.get("content")
    return (
        message.get("role") == "assistant"
        and isinstance(content, list)
        and any(isinstance(block, dict) and block.get("type") == "tool_use" for block in content)
    )


def _build_result(intent, context, message, fit_path, use_history, step_count=0, steps=None):
    if steps is None:
        steps = []
    if context.pending_action:
        return _result("needs_confirmation", intent, context, steps,
                       f"⚠ {context.pending_action.get('message', '确认执行？')}\n\n请回复 '确认' 或 'yes' 来执行。")

    context.permission_grants.clear()

    if step_count > MAX_TOOL_STEPS:
        return _result("max_steps_exceeded", intent, context, steps,
                       f"达到最大步数 ({MAX_TOOL_STEPS}), 已执行 {len(steps)} 步, 但未完成。")

    final_answer = ""
    for m in context.messages:
        if m.get("role") == "assistant":
            for b in (m.get("content") or []):
                if isinstance(b, dict) and b.get("type") == "text":
                    final_answer = b.get("text", "")
    log_path = write_main_agent_markdown_log(
        context.session_id, user_message=message,
        tool_plan={"intent": _intent_kind(intent), "tool_groups": _intent_groups(intent)},
        execution={"status": "completed", "steps": steps},
        selected_activities=context.selected_activities,
        selected_activity_range=context.selected_activity_range,
        current_fit_file=str(context.current_fit_file) if context.current_fit_file else None,
    )
    return _result("completed", intent, context, steps, final_answer or "已完成。", str(log_path))


# -- helpers -------------------------------------------------------------


def _result(status, intent, context, steps, answer, log_path=""):
    r = {"answer": answer, "status": status, "context": context,
         "intent": _intent_kind(intent),
         "steps": steps,
         "selected_activities": context.selected_activities,
         "current_fit_file": str(context.current_fit_file) if context.current_fit_file else None}
    if log_path: r["log_path"] = log_path
    return r


def _intent_kind(intent) -> str:
    return intent.kind.value if hasattr(intent, "kind") else str(intent)


def _intent_groups(intent) -> list[str]:
    return list(getattr(intent, "tool_groups", []))


def _build_system_prompt(intent) -> str:
    side = "你可以调用有副作用的工具(同步、上传),但需要用户确认。" if getattr(intent, 'allow_side_effects', False) else ""
    return f"""你是 Personal FIT Agent。根据用户请求选择合适的工具完成任务。
{side}
规则:
- 先用 find_activity 定位活动,再用 analyze_activity / summarize_activities / compare_activities 处理
- 多步骤任务先调用 todo_write 列出计划;执行过程中保持最多一个 in_progress,完成后及时更新 TODO 状态
- 用户要求上传/下载/刷新时,直接调用对应工具;不要自己用自然语言询问确认,权限系统会拦截并生成确认提示
- 完成后给出简短中文总结
- 不要编造数据
"""


def _build_state_preamble(context):
    parts = []
    if context.current_fit_file: parts.append(f"当前 FIT: {context.current_fit_file}")
    if context.selected_activities: parts.append(f"已选活动: {len(context.selected_activities)} 条")
    if context.selected_activity_range: parts.append(f"活动范围: {json.dumps(context.selected_activity_range, ensure_ascii=False)}")
    if context.pending_action: parts.append(f"⚠ 待确认: {context.pending_action.get('tool')} ({context.pending_action.get('message')})")
    if context.current_todos:
        from agent.main_agent.todos import format_todos_for_prompt
        parts.append(format_todos_for_prompt(context.current_todos))
    if not parts:
        return ""
    return "\n".join(["[本轮状态]", *parts])

def _log_hdr(message, intent, tool_count, has_fit):
    from agent.main_agent.hooks import _log
    _log("─" * 50)
    _log(f"intent: \033[1m{intent.kind.value}\033[0m | groups: {intent.tool_groups} | side_effects: {intent.allow_side_effects}")
    _log(f"context: fit={'✓' if has_fit else '✗'} | tools: {tool_count}")
    _log(f"message: {message[:100]}")
