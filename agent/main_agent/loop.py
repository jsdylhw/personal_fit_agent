"""Agent tool-use loop.

agent_loop() — 纯 tool-use 循环, 接收 ToolLoopHooks 实例.
run_tool_loop() — 便捷入口: intent/context/handlers 组装.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from agent.chat_logger import new_session_id, write_main_agent_markdown_log
from agent.context import AgentContext
from core.fit_paths import resolve_fit_path as _resolve_fit_path
from agent.llm import AnthropicMessagesClient, LLMRequestError, build_tool_result_block
from agent.tools import MAIN_AGENT_TOOLS, render_anthropic_tools
from agent.main_agent.intent import route_intent, intent_tool_categories
from agent.main_agent.hooks import ToolLoopHooks
from agent.main_agent.tools import TOOL_HANDLERS
from agent.main_agent.turn_control import handle_control_turn

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
    client: AnthropicMessagesClient | None = None,
) -> int:
    """纯 tool-use loop. 返回 step_count. messages 原地修改."""
    client = client or AnthropicMessagesClient()
    step_count = 0

    while True:
        step_count += 1
        if step_count > max_steps:
            break

        reminder = hooks.before_llm_call()
        if isinstance(reminder, dict):
            messages.append(reminder)

        final_response_only = hooks.final_response_only
        response = client.create_messages(
            system=system, messages=messages,
            max_tokens=max_tokens,
            tools=[] if final_response_only else tools,
        )
        messages.append({"role": "assistant", "content": response.get("content") or []})

        if response.get("stop_reason") != "tool_use":
            hooks.on_loop_end(messages=messages, response=response, steps=step_count - 1)
            return step_count

        if final_response_only:
            # API contract normally prevents this branch because tools=[].
            # Keep the local loop safe even if a provider incorrectly returns
            # a stale tool_use block after a terminal result.
            messages.append({
                "role": "user",
                "content": "已有完整工具结果。不要再调用工具，直接用中文给出最终回答。",
            })
            continue

        hooks.on_tool_round()

        results: list[dict[str, Any]] = []
        content_blocks = response.get("content") or []
        for block in content_blocks:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue

            blocked = hooks.pre_tool_use(block, step_count=step_count)
            if blocked:
                results.append(build_tool_result_block(block["id"], json.dumps(blocked, ensure_ascii=False)))
                continue

            handler = handlers.get(block["name"])
            tool_input = block.get("input") if isinstance(block.get("input"), dict) else {}
            tool_started = perf_counter()
            try:
                output = handler(tool_input, hooks.context) if handler else {"error": "unknown_tool", "name": block["name"]}
            except Exception as exc:
                err = hooks.on_error(block, exc)
                output = err or {"error": type(exc).__name__, "message": str(exc)}

            from agent.main_agent.tool_result import is_failed_tool_output
            from agent.observability import record_tool_call

            record_tool_call(
                name=str(block.get("name") or ""),
                arguments=tool_input,
                output=output,
                duration_ms=(perf_counter() - tool_started) * 1000,
                success=not is_failed_tool_output(output),
            )

            hooks.post_tool_use(block, output, step_count=step_count)

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

    control_result = handle_control_turn(message, context, verbose=verbose)
    if control_result is not None:
        return control_result

    intent = route_intent(message)
    allowed_cats = intent_tool_categories(intent)

    try:
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
    except LLMRequestError as exc:
        return _build_llm_unavailable_result(
            intent, context, steps=getattr(exc, "steps_taken", []), error=exc,
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

    try:
        step_count = agent_loop(messages, tools=tools, handlers=handlers, hooks=hooks,
                                system=system, max_tokens=max_tokens)
    except LLMRequestError as exc:
        exc.steps_taken = list(steps_taken)
        raise
    finally:
        # LLM 可能在任意一个工具轮次之后断线；保留已完成工具造成的状态，
        # 让交互模式可用“重试”继续，而不是丢失本轮上下文。
        _sync_messages_to_context(context, messages)

    return step_count, steps_taken


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
    context.last_llm_error = None

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
    answer = _with_execution_header(final_answer or "已完成。", context=context, steps=steps)
    return _result("completed", intent, context, steps, answer, str(log_path))


def _build_llm_unavailable_result(intent, context, *, steps: list[dict], error: Exception):
    context.last_llm_error = {
        "type": type(error).__name__,
        "message": str(error),
    }
    workflow_answer = _completed_workflow_fallback(context)
    if workflow_answer:
        return _result("llm_unavailable", intent, context, steps, workflow_answer)
    answer = (
        "LLM 服务连接暂时不可用，已保留本轮活动选择和已执行工具状态。"
        f"本轮已执行 {len(steps)} 步；不会自动执行新的下载、分析或上传。\n\n"
        "请稍后回复“重试”继续。"
    )
    return _result("llm_unavailable", intent, context, steps, answer)


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


def _with_execution_header(answer: str, *, context: AgentContext, steps: list[dict[str, Any]]) -> str:
    """Keep a concise, deterministic account of what the agent actually processed."""
    text = str(answer).strip()
    if not steps or text.startswith("已处理："):
        return text
    activity_labels = []
    for activity in context.selected_activities[:3]:
        if not isinstance(activity, dict):
            continue
        started = activity.get("start_time_local") or activity.get("date_local")
        label = activity.get("summary_label") or activity.get("file_name") or activity.get("activity_key")
        activity_labels.append(" ".join(str(value) for value in (started, label) if value))
    if activity_labels:
        target = "；".join(activity_labels)
        if len(context.selected_activities) > len(activity_labels):
            target += f" 等 {len(context.selected_activities)} 条"
    else:
        target = "本次请求"
    labels = {
        "find_activity": "定位活动",
        "analyze_activity": "读取活动报告",
        "query_activity_detail": "查询 FIT 细节",
        "summarize_activities": "汇总已有报告",
        "compare_activities": "对比活动",
        "calculate_history_metrics": "计算历史指标",
        "sync_garmin_activities": "同步 Garmin 活动",
        "sync_and_run_activity_workflow": "同步并处理活动",
        "run_activity_workflow": "处理本地活动",
        "retry_activity_workflow": "重试工作流",
    }
    operations = [labels.get(str(step.get("tool") or ""), str(step.get("tool") or "")) for step in steps]
    compact_operations = []
    for operation in operations:
        if operation and operation not in compact_operations:
            compact_operations.append(operation)
    return f"已处理：{target}｜{' → '.join(compact_operations)}\n\n{text}"


def _build_system_prompt(intent) -> str:
    side = "你可以调用有副作用的工具（同步、上传）。" if getattr(intent, 'allow_side_effects', False) else ""
    local_today = datetime.now().astimezone().date().isoformat()
    return f"""你是 Personal FIT Agent。根据用户请求选择合适的工具完成任务。
{side}
规则:
- 当前本地日期是 {local_today}。用户说“今天/昨天”时必须传 date=today/date=yesterday，让本地工具解析；不要猜测或自行改写为其他 ISO 日期。
- 先用 find_activity 定位活动,再用 analyze_activity / summarize_activities / compare_activities / calculate_history_metrics 处理。find_activity 只传日期、范围、数量、时间段、运动类型等事实条件，不传 scope/mode；本地会确定解析方式。
- 用户按“上午/下午/晚上/夜间”筛选时，在 find_activity 中传 time_of_day=morning/afternoon/evening/night，再进行后续操作。
- 多条活动的一般报告汇总调用 summarize_activities；它优先读取已有 summary，仅对缺失的活动补齐报告。绝不能对列表逐条调用 analyze_activity 或 query_activity_detail。
- 用户询问历史趋势、是否进步、周/月变化、训练量变化时，先用 find_activity 定位范围，再调用 calculate_history_metrics，并根据它返回的覆盖率、周期变化和阈值一致性解释；不要让 LLM 从报告文字自行计算。
- analyze_activity 只用于一条活动的完整报告，已有 summary 时直接返回；只有用户问到明确 FIT 原始细节（如“100-200 秒”“某次冲刺”“第几公里”）时，才对已精确定位的一条活动调用 query_activity_detail。
- 若用户要处理多条“本地已有”活动（批量生成 summary、上传 Strava 或汇总），调用 run_activity_workflow：一次创建持久化 Run；不要用 find_activity 后逐条编排。
- 用户只要求从 Garmin 同步/下载时，调用 sync_garmin_activities：只下载 FIT 并更新索引，不生成 summary、不分析、不上传。
- 仅当用户明确要求同步/下载后继续分析、上传或汇总时，调用 sync_and_run_activity_workflow；它只处理本次同步并已索引的活动，并创建同一个持久化 Run。
- 需要查看或恢复该批量操作时，使用 get_activity_workflow / retry_activity_workflow，并以工具结果中的 workflow_id 为准。
- 用户要求上传/下载/刷新时，直接调用对应工具；无需额外追问。
- 完成后用简洁中文回答：若调用了工具，先以“已处理：活动/范围｜操作”说明处理对象和操作；再给 1-2 句结论，以及最多 3 条证据或建议。除非用户要求比较，不要堆叠大表格、重复基础指标、表情或客套开场。
- 不要编造数据
"""


def _build_state_preamble(context):
    parts = []
    if context.current_fit_file: parts.append(f"当前 FIT: {context.current_fit_file}")
    if context.selected_activities: parts.append(f"已选活动: {len(context.selected_activities)} 条")
    if context.selected_activity_range: parts.append(f"活动范围: {json.dumps(context.selected_activity_range, ensure_ascii=False)}")
    workflow = _last_workflow_result(context)
    if workflow:
        workflow_id = str(workflow.get("workflow_id") or "")
        status = str(workflow.get("status") or "unknown")
        if workflow_id:
            parts.append(f"最近工作流: {workflow_id}（{status}；仅用于衔接刚才的批量操作）")
    if not parts:
        return ""
    return "\n".join(["[本轮状态]", *parts])


def _last_workflow_result(context: AgentContext) -> dict[str, Any] | None:
    """返回最近一次工作流工具的原始结果，避免依赖已裁剪的 tool_result 消息。"""
    last = context.last_tool_result or {}
    if last.get("step_name") not in {
        "run_activity_workflow",
        "sync_and_run_activity_workflow",
        "get_activity_workflow",
        "retry_activity_workflow",
    }:
        return None
    result = last.get("result")
    return result if isinstance(result, dict) and result.get("workflow_id") else None


def _completed_workflow_fallback(context: AgentContext) -> str | None:
    """LLM 在工具执行后断线时，仍如实报告已完成的持久化 Run。"""
    workflow = _last_workflow_result(context)
    if not workflow or workflow.get("status") != "completed":
        return None

    task_counts: dict[str, int] = {}
    for task in workflow.get("tasks") or []:
        if isinstance(task, dict):
            status = str(task.get("status") or "unknown")
            task_counts[status] = task_counts.get(status, 0) + 1

    details = []
    sync = workflow.get("sync")
    if isinstance(sync, dict):
        details.append(
            f"同步：下载 {int(sync.get('downloaded') or 0)} 条，跳过 {int(sync.get('skipped') or 0)} 条"
        )
    if task_counts:
        details.append(
            "任务：" + "，".join(
                f"{label} {task_counts.get(status, 0)}"
                for status, label in (("completed", "完成"), ("skipped", "跳过"), ("failed", "失败"))
                if task_counts.get(status, 0)
            )
        )

    summary = "；".join(details) or "所有已规划任务均已完成"
    return (
        f"工作流已完成：{workflow['workflow_id']}。{summary}。\n\n"
        "LLM 仅在生成最终说明时连接中断；不会重复执行同步、分析或上传。"
    )

def _log_hdr(message, intent, tool_count, has_fit):
    from agent.main_agent.hooks import _log
    _log("─" * 50)
    _log(f"intent: \033[1m{intent.kind.value}\033[0m | groups: {intent.tool_groups} | side_effects: {intent.allow_side_effects}")
    _log(f"context: fit={'✓' if has_fit else '✗'} | tools: {tool_count}")
    _log(f"message: {message[:100]}")
