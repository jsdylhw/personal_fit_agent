"""Convert completed runtime state into the public TurnResult contract."""

from __future__ import annotations

from typing import Any

from agent.main_agent.context import AgentContext
from agent.main_agent.prompt_builder import last_workflow_result
from agent.runtime.chat_logger import write_main_agent_markdown_log
from agent.runtime.models import TurnResult, executions_from_trace
from agent.runtime.presentation_projector import project_presentations


def build_completed_result(
    intent: Any,
    context: AgentContext,
    message: str,
    *,
    step_count: int,
    max_tool_steps: int,
    steps: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a completed or max-steps result from the current turn only."""
    context.last_llm_error = None
    if step_count > max_tool_steps:
        return build_turn_result(
            "max_steps_exceeded",
            intent,
            context,
            steps,
            f"达到最大步数 ({max_tool_steps}), 已执行 {len(steps)} 步, 但未完成。",
        )

    final_answer = ""
    for item in context.messages:
        if item.get("role") != "assistant":
            continue
        for block in item.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "text":
                final_answer = str(block.get("text") or "")
    log_path = write_main_agent_markdown_log(
        context.session_id,
        user_message=message,
        tool_plan={"intent": intent_kind(intent), "skill_id": context.active_skill_id},
        execution={"status": "completed", "steps": steps, "step_results": context.execution_trace},
        selected_activities=context.selected_activities,
        selected_activity_range=context.selected_activity_range,
        current_fit_file=str(context.current_fit_file) if context.current_fit_file else None,
    )
    answer = with_execution_header(final_answer or "已完成。", context=context, steps=steps)
    return build_turn_result("completed", intent, context, steps, answer, str(log_path))


def build_llm_unavailable_result(
    intent: Any,
    context: AgentContext,
    *,
    steps: list[dict[str, Any]],
    error: Exception,
) -> dict[str, Any]:
    """Preserve completed tool state when final language generation fails."""
    context.last_llm_error = {"type": type(error).__name__, "message": str(error)}
    workflow_answer = completed_workflow_fallback(context)
    if workflow_answer:
        return build_turn_result("llm_unavailable", intent, context, steps, workflow_answer)
    answer = (
        "LLM 服务连接暂时不可用，已保留本轮活动选择和已执行工具状态。"
        f"本轮已执行 {len(steps)} 步；不会自动执行新的下载、分析或上传。\n\n"
        "请稍后回复“重试”继续。"
    )
    return build_turn_result("llm_unavailable", intent, context, steps, answer)


def build_activation_unavailable_result(context: AgentContext, *, error: Exception) -> dict[str, Any]:
    """Fail closed when the model client cannot be created."""
    context.last_llm_error = {"type": type(error).__name__, "message": str(error)}
    context.active_skill_id = None
    answer = "LLM 服务连接暂时不可用，尚未选择领域 Skill，因此本轮没有暴露或执行任何活动工具。请稍后重试。"
    return build_turn_result("llm_unavailable", "skill_activation", context, [], answer)


def build_turn_result(
    status: str,
    intent: Any,
    context: AgentContext,
    steps: list[dict[str, Any]],
    answer: str,
    log_path: str = "",
) -> dict[str, Any]:
    """Create the typed result while preserving the legacy dictionary API."""
    executions = executions_from_trace(context.execution_trace, steps=steps)
    return TurnResult(
        answer=answer,
        status=status,
        context=context,
        intent=intent_kind(intent),
        skill_id=context.active_skill_id,
        executions=executions,
        presentations=project_presentations(executions),
        selected_activities=context.selected_activities,
        current_fit_file=str(context.current_fit_file) if context.current_fit_file else None,
        log_path=log_path,
    ).to_dict()


def intent_kind(intent: Any) -> str:
    """Return a stable public intent label from legacy or string inputs."""
    return intent.kind.value if hasattr(intent, "kind") else str(intent)


def with_execution_header(
    answer: str,
    *,
    context: AgentContext,
    steps: list[dict[str, Any]],
) -> str:
    """Prefix the answer with a concise account of actual business tools."""
    text = str(answer).strip()
    if not steps or text.startswith("已处理："):
        return text
    activity_labels: list[str] = []
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
        "resolve_activities": "定位活动",
        "find_segments": "定位片段",
        "inspect_selection": "初步检查",
        "analyze_selection": "分析当前焦点",
        "navigate_selection": "切换焦点",
        "analyze_activity": "读取活动报告",
        "query_activity_detail": "查询 FIT 细节",
        "summarize_activities": "汇总已有报告",
        "compare_activities": "对比活动",
        "calculate_history_metrics": "计算历史指标",
        "analyze_training_history": "分析训练历史",
        "sync_garmin_activities": "同步 Garmin 活动",
        "sync_and_run_activity_workflow": "同步并处理活动",
        "run_activity_workflow": "处理本地活动",
        "retry_activity_workflow": "重试工作流",
        "rebuild_activity_reports": "后台重建 V2 报告",
        "get_activity_report_job": "查看报告任务",
    }
    operations = [labels.get(str(step.get("tool") or ""), str(step.get("tool") or "")) for step in steps]
    compact_operations: list[str] = []
    for operation in operations:
        if operation and operation not in compact_operations:
            compact_operations.append(operation)
    return f"已处理：{target}｜{' → '.join(compact_operations)}\n\n{text}"


def completed_workflow_fallback(context: AgentContext) -> str | None:
    """Truthfully report a completed workflow if final generation disconnects."""
    workflow = last_workflow_result(context)
    if not workflow or workflow.get("status") != "completed":
        return None
    task_counts: dict[str, int] = {}
    for task in workflow.get("tasks") or []:
        if isinstance(task, dict):
            status = str(task.get("status") or "unknown")
            task_counts[status] = task_counts.get(status, 0) + 1
    details: list[str] = []
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
