"""新一代 workflow 入口:Intent → Tool Allowlist → Native Tool Use → Guard → Executor.

替代旧的 Planner → Validator → Selector → Executor 四层链,
利用 Anthropic 原生 tool use 让 LLM 直接选择步骤.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.chat_logger import new_session_id, write_workflow_markdown_log
from agent.context import AgentContext
from core.fit_paths import resolve_fit_path as _resolve_fit_path
from agent.llm import AnthropicMessagesClient, extract_text, build_tool_result_block
from agent.tools import PLANNER_TOOLS, FIT_DATA_TOOLS, ToolRegistry, render_anthropic_tools
from agent.tools.spec import ToolDef
from agent.workflow.executor import execute_workflow_plan
from agent.workflow.intent import Intent, route_intent, intent_tool_categories
from agent.workflow.tool_guard import guard_tool_call, GuardResult

MAX_TOOL_STEPS = 10


def run_tool_loop(
    message: str,
    *,
    fit_path: str | Path | None = None,
    use_history: bool = True,
    max_tokens: int = 4096,
) -> dict[str, Any]:
    """新入口:Intent Router + 原生 tool use loop.

    替代 run_planned_workflow(),不再走 Planner → Selector 链路.
    """
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

    # 组装本轮可用的工具
    registry = _build_allowlist_registry(allowed_cats)

    client = AnthropicMessagesClient()
    system = _build_system_prompt(intent)

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": _build_initial_message(message, intent, context)},
    ]

    results: list[dict[str, Any]] = []
    final_answer: str | None = None
    has_resolved = bool(context.current_fit_file)
    user_confirmed = not intent.needs_confirmation

    for step_idx in range(1, MAX_TOOL_STEPS + 1):
        response = client.create_messages(
            system=system,
            messages=messages,
            max_tokens=max_tokens,
            tools=render_anthropic_tools(registry.all()),
        )

        messages.append({"role": "assistant", "content": response.get("content") or []})
        response_text = extract_text(response)

        # 收集 tool_use
        tool_blocks = [
            block for block in response.get("content") or []
            if isinstance(block, dict) and block.get("type") == "tool_use"
        ]

        if not tool_blocks and response_text:
            final_answer = response_text
            break

        if not tool_blocks:
            break

        # Guard + Execute
        tool_result_blocks: list[dict[str, Any]] = []
        for block in tool_blocks:
            tool_name = block["name"]
            tool_input = block.get("input") or {}

            # Check if it's a planner tool; if not, try fit tools
            tool_def = registry.get(tool_name)

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
                    # 首次遇到需要确认的副作用 → 注入确认请求
                    tool_result_blocks.append(build_tool_result_block(
                        block["id"],
                        json.dumps({"status": "needs_confirmation", "message": guard.confirm_message}),
                    ))
                    user_confirmed = True  # 本轮注入确认后不再挡
                    continue
                tool_result_blocks.append(build_tool_result_block(
                    block["id"],
                    json.dumps({"error": "guarded", "reason": guard.reason}),
                ))
                continue

            # Execute
            try:
                if tool_def:
                    result = _execute_planner_tool(tool_def.name, tool_input, context)
                else:
                    result = {"error": "unknown_tool", "name": tool_name}
            except Exception as exc:
                result = {"error": type(exc).__name__, "message": str(exc)}

            if tool_def and tool_def.category in {"activity_resolution"}:
                has_resolved = True

            results.append({"tool": tool_name, "result": result})
            tool_result_blocks.append(
                build_tool_result_block(block["id"], json.dumps(result, ensure_ascii=False, default=str))
            )

        messages.append({"role": "user", "content": tool_result_blocks})

    # Fallback to old planner if tool loop didn't produce answer
    if not final_answer:
        return _fallback_planned_workflow(message, context, fit_path=fit_path, use_history=use_history)

    # Write log
    log_path = write_workflow_markdown_log(
        session_id,
        user_message=message,
        planner_plan={"intent": intent.kind.value, "tool_groups": list(intent.tool_groups)},
        normalized_plan={},
        execution={"status": "completed", "steps": results},
        selected_activities=context.selected_activities,
        selected_activity_range=context.selected_activity_range,
        current_fit_file=str(context.current_fit_file) if context.current_fit_file else None,
    )

    return {
        "answer": final_answer,
        "status": "completed",
        "log_path": str(log_path),
        "intent": intent.kind.value,
        "steps": results,
        "selected_activities": context.selected_activities,
        "current_fit_file": str(context.current_fit_file) if context.current_fit_file else None,
    }


# -- Helpers ---------------------------------------------------------------

def _build_allowlist_registry(allowed_cats: set[str]) -> ToolRegistry:
    """根据允许的类别过滤工具."""
    registry = ToolRegistry()
    for tool in PLANNER_TOOLS:
        if tool.category in allowed_cats:
            registry.add(tool)
    for tool in FIT_DATA_TOOLS:
        if tool.category in allowed_cats:
            registry.add(tool)
    return registry


def _build_system_prompt(intent: Intent) -> str:
    side_note = ""
    if intent.allow_side_effects:
        side_note = "你可以调用有副作用的工具(如同步、上传),但仅在用户明确要求时。"
    return f"""你是 Personal FIT Agent。根据用户请求选择合适的工具完成任务。

{side_note}

规则:
- 先定位活动(resolve),再分析(analyze)
- 只有用户明确要求时才上传/下载
- 完成后给出简短中文总结
- 不要编造数据
"""


def _build_initial_message(message: str, intent: Intent, context: AgentContext) -> str:
    parts = [f"用户请求: {message}"]
    if context.current_fit_file:
        parts.append(f"当前 FIT 文件: {context.current_fit_file}")
    return "\n".join(parts)


def _execute_planner_tool(name: str, args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    """执行单个 Planner 工具 — 委托给 executor 的统一分发."""
    from agent.workflow.plan_schema import WorkflowPlan, WorkflowPlanStep
    from agent.workflow.executor import execute_workflow_plan

    step = WorkflowPlanStep(name=name, reason="tool_use", arguments=args)
    plan = WorkflowPlan(
        task_type="tool_loop",
        steps=[step],
        allow_side_effects=True,
    )
    exec_result = execute_workflow_plan(plan, context)
    if exec_result.step_results:
        sr = exec_result.step_results[0]
        if sr.result:
            return sr.result
        return {"answer": sr.message or "", "status": sr.status}
    return {"status": exec_result.status}


def _fallback_planned_workflow(
    message: str,
    context: AgentContext,
    *,
    fit_path: str | Path | None = None,
    use_history: bool = True,
) -> dict[str, Any]:
    """当 tool loop 无法产生回答时,回退到旧 Planner 链路."""
    from agent.workflow.runner import run_planned_workflow
    return run_planned_workflow(message, fit_path=fit_path, use_history=use_history)
