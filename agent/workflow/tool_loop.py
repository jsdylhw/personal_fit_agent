"""Agent tool-use loop.

agent_loop() — 纯 tool-use 循环, 接收 HookRegistry 实例.
run_tool_loop() — 便捷入口: intent/context/handlers 组装.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.chat_logger import new_session_id, write_workflow_markdown_log
from agent.context import AgentContext
from core.fit_paths import resolve_fit_path as _resolve_fit_path
from agent.llm import AnthropicMessagesClient, extract_text, build_tool_result_block
from agent.tools import PLANNER_TOOLS, render_anthropic_tools
from agent.workflow.intent import route_intent, intent_tool_categories
from agent.workflow.hooks import HookRegistry, install_all_hooks, make_permission_hook, make_guard_hook, make_state_update_hook

MAX_TOOL_STEPS = 10
CONFIRM_WORDS = {"确认", "yes", "y", "是", "继续", "ok", "confirm", "确定", "好", "可以"}


# -- 核心: agent_loop -------------------------------------------------

def agent_loop(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]],
    handlers: dict[str, Any],
    hooks: HookRegistry,
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

        response = client.create_messages(
            system=system, messages=messages,
            max_tokens=max_tokens, tools=tools,
        )
        messages.append({"role": "assistant", "content": response.get("content") or []})

        if response.get("stop_reason") != "tool_use":
            hooks.trigger("on_loop_end", messages=messages, response=response, steps=step_count - 1)
            return step_count

        results: list[dict[str, Any]] = []
        for block in response.get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue

            blocked = hooks.trigger("pre_tool_use", block=block, step_count=step_count)
            if blocked:
                results.append(build_tool_result_block(block["id"], json.dumps(blocked, ensure_ascii=False)))
                continue

            handler = handlers.get(block["name"])
            try:
                output = handler(**block.get("input", {})) if handler else {"error": "unknown_tool", "name": block["name"]}
            except Exception as exc:
                err = hooks.trigger("on_error", block=block, error=exc)
                output = err or {"error": type(exc).__name__, "message": str(exc)}

            hooks.trigger("post_tool_use", block=block, output=output, step_count=step_count)

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
    if context is None:
        current_fit = _resolve_fit_path(fit_path) if fit_path else None
        session_id = new_session_id("tool_loop")
        context = AgentContext(
            session_id=session_id, current_fit_file=current_fit,
            history_enabled=use_history,
            messages=[{"role": "user", "content": message}],
        )
    else:
        session_id = context.session_id
        context.messages.append({"role": "user", "content": message})

    # pending 确认 → 执行工具,记录到 context.messages, 返回后可继续下轮
    if context.pending_action and _is_confirm(message):
        pending = context.pending_action
        context.pending_action = None
        handlers = _build_planner_handlers(context)
        handler = handlers.get(pending["tool"])
        if handler:
            try:
                output = handler(**pending.get("input", {}))
            except Exception as exc:
                output = {"error": type(exc).__name__, "message": str(exc)}
            context.last_tool_result = {"step_name": pending["tool"], "result": output}
            # 写入 context.messages 保持追踪
            result_json = json.dumps(output, ensure_ascii=False, default=str)
            context.messages.append({"role": "user", "content": f"[确认执行] {pending['tool']}"})
            context.messages.append({"role": "assistant", "content": [{"type": "text", "text": f"已执行 {pending['tool']}:\n{result_json[:300]}"}]})
            if verbose:
                _log_confirm(pending["tool"], output)
            return {
                "answer": f"已执行 {pending['tool']}。\n{result_json[:200]}",
                "status": "completed", "context": context, "intent": "confirmed",
                "steps": [{"tool": pending["tool"], "input": pending.get("input", {})}],
            }
        return {"answer": f"未知工具: {pending['tool']}", "status": "failed", "context": context}

    intent = route_intent(message)
    allowed_cats = intent_tool_categories(intent)

    step_count, steps_taken = _do_loop(message, intent, allowed_cats, context, session_id, verbose, max_tokens)
    return _build_result(intent, context, verbose, session_id, message, fit_path, use_history, max_tokens,
                         step_count, steps_taken)


def _do_loop(message, intent, allowed_cats, context, session_id, verbose, max_tokens):
    """执行 agent_loop 并同步 messages 回 context. 返回 step_count."""
    tools = [render_anthropic_tools([t])[0] for t in PLANNER_TOOLS if t.category in allowed_cats]
    handlers = _build_planner_handlers(context)
    system = _build_system_prompt(intent)
    has_resolved = {"value": bool(context.current_fit_file)}
    steps_taken: list[dict] = []

    if len(context.messages) > 1:
        preamble = _build_state_preamble(context)
        messages = [{"role": "user", "content": preamble}] + list(context.messages)
    else:
        messages = [{"role": "user", "content": _build_initial_message(message, intent, context)}]

    hooks = HookRegistry()
    install_all_hooks(hooks, context, allowed_cats, has_resolved, steps_taken, verbose=verbose)
    if verbose:
        _log_hdr(message, intent, len(tools), bool(context.current_fit_file))

    step_count = agent_loop(messages, tools=tools, handlers=handlers, hooks=hooks,
                            system=system, max_tokens=max_tokens)

    _sync_messages_to_context(context, messages)
    return step_count, steps_taken


def _sync_messages_to_context(context, messages):
    """将 agent_loop 产生的消息同步回 context,去掉状态 preamble."""
    clean = []
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, str) and content.startswith("[本轮状态]"):
            continue  # 跳过 preamble
        clean.append(m)
    context.messages = clean


def _build_result(intent, context, verbose, session_id, message, fit_path, use_history, max_tokens,
                  step_count=0, steps=None):
    if steps is None:
        steps = []
    if context.pending_action:
        return _result("needs_confirmation", intent, context, steps,
                       f"⚠ {context.pending_action.get('message', '确认执行？')}\n\n请回复 '确认' 或 'yes' 来执行。")

    if step_count > MAX_TOOL_STEPS:
        return _result("max_steps_exceeded", intent, context, steps,
                       f"达到最大步数 ({MAX_TOOL_STEPS}), 已执行 {len(steps)} 步, 但未完成。")

    final_answer = ""
    for m in context.messages:
        if m.get("role") == "assistant":
            for b in (m.get("content") or []):
                if isinstance(b, dict) and b.get("type") == "text":
                    final_answer = b.get("text", "")
    if not final_answer and not steps:
        return _fallback_planned(message, context, fit_path=fit_path, use_history=use_history)

    log_path = write_workflow_markdown_log(
        session_id, user_message=message,
        planner_plan={"intent": intent.kind.value, "tool_groups": list(intent.tool_groups)},
        normalized_plan={},
        execution={"status": "completed", "steps": steps},
        selected_activities=context.selected_activities,
        selected_activity_range=context.selected_activity_range,
        current_fit_file=str(context.current_fit_file) if context.current_fit_file else None,
    )
    return _result("completed", intent, context, steps, final_answer or "已完成。", str(log_path))


# -- helpers -------------------------------------------------------------

def _is_confirm(message: str) -> bool:
    return message.lower().strip() in CONFIRM_WORDS


def _result(status, intent, context, steps, answer, log_path=""):
    r = {"answer": answer, "status": status, "context": context,
         "intent": intent.kind.value if hasattr(intent, 'kind') else str(intent),
         "steps": steps,
         "selected_activities": context.selected_activities,
         "current_fit_file": str(context.current_fit_file) if context.current_fit_file else None}
    if log_path: r["log_path"] = log_path
    return r


def _build_planner_handlers(context):
    def _casual_chat(answer=None, message=None, **kw):
        return {"answer": answer or message or "你好，我在。"}
    def _ask_user_clarification(question=None, **kw):
        return {"answer": question or "请再描述一下你的需求。"}
    def _sync_garmin_activities(count=5, **kw):
        from agent.workflow.handlers.ops import sync_garmin_activities_tool
        result = sync_garmin_activities_tool(count=int(count))
        context.last_tool_result = {"step_name": "sync_garmin_activities", "result": result}
        return result
    def _step(name, **kw): return _run_planner_step(name, kw, context)
    return {
        "casual_chat": _casual_chat, "ask_user_clarification": _ask_user_clarification,
        "resolve_current_activity": lambda **kw: _step("resolve_current_activity", **kw),
        "resolve_activity_by_date": lambda **kw: _step("resolve_activity_by_date", **kw),
        "resolve_activity_range": lambda **kw: _step("resolve_activity_range", **kw),
        "resolve_recent_activities": lambda **kw: _step("resolve_recent_activities", **kw),
        "analyze_single_activity": lambda force=False, **kw: _step("analyze_single_activity", force=force, **kw),
        "summarize_activity_range": lambda **kw: _step("summarize_activity_range", **kw),
        "compare_activities": lambda **kw: _step("compare_activities", **kw),
        "compare_with_history": lambda **kw: _step("summarize_activity_range", **kw),
        "generate_training_advice": lambda **kw: _step("summarize_activity_range", **kw),
        "summarize_recent_training_load": lambda **kw: _step("summarize_recent_training_load", **kw),
        "generate_route_advice": lambda **kw: _step("generate_route_advice", **kw),
        "sync_garmin_activities": _sync_garmin_activities,
        "analyze_new_fit_files": lambda **kw: _step("analyze_new_fit_files", **kw),
        "generate_summary_file": lambda force=False, **kw: _step("generate_summary_file", force=force, **kw),
        "ensure_activity_summaries": lambda force=False, **kw: _step("ensure_activity_summaries", force=force, **kw),
        "upload_strava_activity": lambda force=False, **kw: _step("upload_strava_activity", force=force, **kw),
    }


def _run_planner_step(name, args, context):
    from agent.workflow.plan_schema import WorkflowPlan, WorkflowPlanStep
    from agent.workflow.executor import execute_workflow_plan
    step = WorkflowPlanStep(name=name, reason="tool_use", arguments=args)
    plan = WorkflowPlan(task_type="tool_loop", steps=[step], allow_side_effects=True)
    exec_result = execute_workflow_plan(plan, context)
    if exec_result.step_results:
        sr = exec_result.step_results[0]
        return sr.result or {"answer": sr.message or "", "status": sr.status}
    return {"status": exec_result.status}


def _build_system_prompt(intent) -> str:
    side = "你可以调用有副作用的工具(同步、上传),但需要用户确认。" if getattr(intent, 'allow_side_effects', False) else ""
    return f"""你是 Personal FIT Agent。根据用户请求选择合适的工具完成任务。
{side}
规则:
- 先定位活动(resolve),再分析(analyze)
- 副作用工具(上传/下载)先询问用户确认
- 完成后给出简短中文总结
- 不要编造数据
"""


def _build_state_preamble(context):
    parts = ["[本轮状态]"]
    if context.current_fit_file: parts.append(f"当前 FIT: {context.current_fit_file}")
    if context.selected_activities: parts.append(f"已选活动: {len(context.selected_activities)} 条")
    if context.selected_activity_range: parts.append(f"活动范围: {json.dumps(context.selected_activity_range, ensure_ascii=False)}")
    if context.pending_action: parts.append(f"⚠ 待确认: {context.pending_action.get('tool')} ({context.pending_action.get('message')})")
    return "\n".join(parts)


def _build_initial_message(message, intent, context):
    parts = [f"用户请求: {message}"]
    if context.current_fit_file: parts.append(f"当前 FIT: {context.current_fit_file}")
    return "\n".join(parts)


def _fallback_planned(message, context, **kw):
    from agent.workflow.runner import run_planned_workflow
    return run_planned_workflow(message, fit_path=kw.get('fit_path'), use_history=kw.get('use_history', True))


def _log_confirm(tool, output):
    from agent.workflow.hooks import _log
    _log(f"  [confirm] \033[1m{tool}\033[0m {json.dumps(output, ensure_ascii=False, default=str)[:120]}")


def _log_hdr(message, intent, tool_count, has_fit):
    from agent.workflow.hooks import _log
    _log("─" * 50)
    _log(f"intent: \033[1m{intent.kind.value}\033[0m | groups: {intent.tool_groups} | side_effects: {intent.allow_side_effects}")
    _log(f"context: fit={'✓' if has_fit else '✗'} | tools: {tool_count}")
    _log(f"message: {message[:100]}")
