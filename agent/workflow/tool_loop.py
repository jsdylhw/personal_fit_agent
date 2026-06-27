"""新一代 workflow 入口:Intent Router → Native Tool Use Loop.

利用 Anthropic 原生 tool use 让 LLM 直接选择工具,
替代旧的 Planner → Validator → Selector → Executor 四层链.
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
from agent.workflow.tool_guard import guard_tool_call


def run_tool_loop(
    message: str,
    *,
    fit_path: str | Path | None = None,
    use_history: bool = True,
    max_tokens: int = 4096,
    verbose: bool = False,
) -> dict[str, Any]:
    """新入口:Intent Router + 原生 tool use loop."""
    intent = route_intent(message)
    allowed_cats = intent_tool_categories(intent)
    current_fit = _resolve_fit_path(fit_path) if fit_path else None

    session_id = new_session_id("tool_loop")
    context = AgentContext(
        session_id=session_id,
        current_fit_file=current_fit,
        history_enabled=use_history,
        messages=[{"role": "user", "content": message}],
    )

    # 只暴露本轮允许的 planner 工具 (FIT data tools 在内部 tool loop 中使用)
    tools = [render_anthropic_tools([t])[0] for t in PLANNER_TOOLS if t.category in allowed_cats]
    handlers = _build_planner_handlers(context)
    client = AnthropicMessagesClient()
    system = _build_system_prompt(intent)

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": _build_initial_message(message, intent, context)},
    ]

    if verbose:
        _log(f"intent: {intent.kind.value} | groups: {intent.tool_groups} | "
             f"side_effects: {intent.allow_side_effects} | tools: {len(tools)}")

    steps_taken: list[dict[str, Any]] = []
    has_resolved = bool(context.current_fit_file)
    user_confirmed = not intent.needs_confirmation

    while True:
        response = client.create_messages(
            system=system,
            messages=messages,
            max_tokens=max_tokens,
            tools=tools,
        )
        messages.append({"role": "assistant", "content": response.get("content") or []})

        if response.get("stop_reason") != "tool_use":
            break

        tool_result_blocks: list[dict[str, Any]] = []
        for block in response.get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue

            tool_name = block["name"]
            tool_input = block.get("input") or {}

            # Guard
            guard = guard_tool_call(
                tool_name, tool_input,
                context=context,
                allowed_categories=allowed_cats,
                user_confirmed=user_confirmed,
                has_resolved=has_resolved,
            )
            if not guard.allowed:
                if guard.needs_confirmation:
                    user_confirmed = True
                    tool_result_blocks.append(build_tool_result_block(
                        block["id"],
                        json.dumps({"status": "needs_confirmation", "message": guard.confirm_message}),
                    ))
                    continue
                tool_result_blocks.append(build_tool_result_block(
                    block["id"],
                    json.dumps({"error": "guarded", "reason": guard.reason}),
                ))
                if verbose:
                    _log(f"  ⊘ {tool_name}: guarded ({guard.reason})")
                continue

            # Execute
            if verbose:
                args_fmt = ", ".join(f"{k}={v}" for k, v in tool_input.items()) or "no args"
                _log(f"  → {tool_name}({args_fmt})")

            handler = handlers.get(tool_name)
            try:
                output = handler(**tool_input) if handler else _unknown_tool(tool_name)
            except Exception as exc:
                output = {"error": type(exc).__name__, "message": str(exc)}

            if verbose:
                _log(f"  ← {tool_name}: {_result_snippet(output)}")

            tool_result_blocks.append(
                build_tool_result_block(block["id"], json.dumps(output, ensure_ascii=False, default=str))
            )
            steps_taken.append({"tool": tool_name, "input": tool_input})

            if tool_name.startswith("resolve_"):
                has_resolved = True

        messages.append({"role": "user", "content": tool_result_blocks})

    final_answer = extract_text(response) if 'response' in dir() else ""
    if not final_answer and not steps_taken:
        return _fallback_planned_workflow(message, context, fit_path=fit_path, use_history=use_history)

    log_path = write_workflow_markdown_log(
        session_id,
        user_message=message,
        planner_plan={"intent": intent.kind.value, "tool_groups": list(intent.tool_groups)},
        normalized_plan={},
        execution={"status": "completed", "steps": steps_taken},
        selected_activities=context.selected_activities,
        selected_activity_range=context.selected_activity_range,
        current_fit_file=str(context.current_fit_file) if context.current_fit_file else None,
    )

    return {
        "answer": final_answer or "已完成。",
        "status": "completed",
        "log_path": str(log_path),
        "intent": intent.kind.value,
        "steps": steps_taken,
        "selected_activities": context.selected_activities,
        "current_fit_file": str(context.current_fit_file) if context.current_fit_file else None,
    }


# -- Handler 工厂 -----------------------------------------------------------

def _build_planner_handlers(context: AgentContext) -> dict[str, Any]:
    """构建 planner 工具的 handler 字典,context 通过闭包注入."""

    def _casual_chat(answer=None, message=None, **kw):
        return {"answer": answer or message or "你好，我在。"}

    def _ask_user_clarification(question=None, **kw):
        return {"answer": question or "请再描述一下你的需求。"}

    def _resolve_current_activity(**kw):
        from agent.activity.resolution import execute_activity_resolution_step
        from agent.workflow.plan_schema import WorkflowPlanStep
        step = WorkflowPlanStep(name="resolve_current_activity", reason="tool_use", arguments={})
        return execute_activity_resolution_step(step, context)

    def _resolve_activity_by_date(**kw):
        return _run_planner_step("resolve_activity_by_date", kw, context)

    def _resolve_activity_range(**kw):
        return _run_planner_step("resolve_activity_range", kw, context)

    def _resolve_recent_activities(**kw):
        return _run_planner_step("resolve_recent_activities", kw, context)

    def _analyze_single_activity(force=False, **kw):
        return _run_planner_step("analyze_single_activity", {"force": force, **kw}, context)

    def _summarize_activity_range(**kw):
        return _run_planner_step("summarize_activity_range", kw, context)

    def _compare_activities(**kw):
        return _run_planner_step("compare_activities", kw, context)

    def _summarize_recent_training_load(**kw):
        return _run_planner_step("summarize_recent_training_load", kw, context)

    def _generate_route_advice(**kw):
        return _run_planner_step("generate_route_advice", kw, context)

    def _sync_garmin_activities(count=5, **kw):
        from agent.workflow.handlers.ops import sync_garmin_activities_tool
        return sync_garmin_activities_tool(count=int(count))

    def _analyze_new_fit_files(**kw):
        return _run_planner_step("analyze_new_fit_files", kw, context)

    def _generate_summary_file(force=False, **kw):
        return _run_planner_step("generate_summary_file", {"force": force, **kw}, context)

    def _ensure_activity_summaries(force=False, **kw):
        return _run_planner_step("ensure_activity_summaries", {"force": force, **kw}, context)

    def _upload_strava_activity(force=False, **kw):
        return _run_planner_step("upload_strava_activity", {"force": force, **kw}, context)

    return {
        "casual_chat": _casual_chat,
        "ask_user_clarification": _ask_user_clarification,
        "resolve_current_activity": _resolve_current_activity,
        "resolve_activity_by_date": _resolve_activity_by_date,
        "resolve_activity_range": _resolve_activity_range,
        "resolve_recent_activities": _resolve_recent_activities,
        "analyze_single_activity": _analyze_single_activity,
        "summarize_activity_range": _summarize_activity_range,
        "compare_activities": _compare_activities,
        "compare_with_history": _summarize_activity_range,  # 暂用 range handler
        "generate_training_advice": _summarize_activity_range,  # 暂用 range handler
        "summarize_recent_training_load": _summarize_recent_training_load,
        "generate_route_advice": _generate_route_advice,
        "sync_garmin_activities": _sync_garmin_activities,
        "analyze_new_fit_files": _analyze_new_fit_files,
        "generate_summary_file": _generate_summary_file,
        "ensure_activity_summaries": _ensure_activity_summaries,
        "upload_strava_activity": _upload_strava_activity,
    }


def _run_planner_step(name: str, args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    """委托单个 step 给已有 executor."""
    from agent.workflow.plan_schema import WorkflowPlan, WorkflowPlanStep
    from agent.workflow.executor import execute_workflow_plan

    step = WorkflowPlanStep(name=name, reason="tool_use", arguments=args)
    plan = WorkflowPlan(task_type="tool_loop", steps=[step], allow_side_effects=True)
    exec_result = execute_workflow_plan(plan, context)
    if exec_result.step_results:
        sr = exec_result.step_results[0]
        if sr.result:
            return sr.result
        return {"answer": sr.message or "", "status": sr.status}
    return {"status": exec_result.status}


# -- Helpers ---------------------------------------------------------------

def _build_system_prompt(intent) -> str:
    side_note = ""
    if intent.allow_side_effects:
        side_note = "你可以调用有副作用的工具(同步、上传),但仅在用户明确要求时。"
    return f"""你是 Personal FIT Agent。根据用户请求选择合适的工具完成任务。

{side_note}

规则:
- 先定位活动(resolve),再分析(analyze)
- 只有用户明确要求时才上传/下载
- 完成后给出简短中文总结
- 不要编造数据
"""


def _build_initial_message(message: str, intent, context: AgentContext) -> str:
    parts = [f"用户请求: {message}"]
    if context.current_fit_file:
        parts.append(f"当前 FIT 文件: {context.current_fit_file}")
    return "\n".join(parts)


def _unknown_tool(name: str) -> dict[str, Any]:
    return {"error": "unknown_tool", "name": name}


def _fallback_planned_workflow(
    message: str, context: AgentContext, *,
    fit_path: str | Path | None = None, use_history: bool = True,
) -> dict[str, Any]:
    from agent.workflow.runner import run_planned_workflow
    return run_planned_workflow(message, fit_path=fit_path, use_history=use_history)


def _log(msg: str) -> None:
    import sys
    print(f"\033[2m[agent]\033[0m {msg}", file=sys.stderr, flush=True)


def _result_snippet(output: dict[str, Any]) -> str:
    text = json.dumps(output, ensure_ascii=False, default=str)
    return text[:120] + ("..." if len(text) > 120 else "")
