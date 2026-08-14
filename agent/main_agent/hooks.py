"""Hard-coded hooks used by the agent tool loop."""

from __future__ import annotations

from typing import Any

from agent.main_agent.tool_result import is_failed_tool_output


class ToolLoopHooks:
    """Fixed hook order for the tool loop."""

    def __init__(
        self,
        context,
        allowed_cats,
        has_resolved_ref,
        steps_taken,
        *,
        allowed_tool_names=None,
        verbose=False,
    ):
        self.context = context
        self.allowed_cats = allowed_cats
        self.has_resolved_ref = has_resolved_ref
        self.steps_taken = steps_taken
        self.allowed_tool_names = set(allowed_tool_names) if allowed_tool_names is not None else None
        self.verbose = verbose
        self.final_response_only = False
        self._tool_call_count = 0
        self._tool_call_indices: dict[str, int] = {}
        self._navigation_before: dict[str, dict[str, Any]] = {}

    def before_llm_call(self) -> dict[str, str] | None:
        reference = getattr(self.context, "pending_skill_reference", None)
        if reference:
            self.context.pending_skill_reference = None
            return {"role": "user", "content": reference}
        return None

    def on_tool_round(self) -> None:
        return None

    def on_error(self, block: dict[str, Any], error: Exception) -> dict[str, Any] | None:
        return None

    def on_loop_end(self, *, messages: list[dict[str, Any]], response: dict[str, Any], steps: int) -> None:
        return None

    def pre_tool_use(self, block: dict[str, Any], *, step_count: int) -> dict[str, Any] | None:
        self._tool_call_count += 1
        call_id = str(block.get("id") or self._tool_call_count)
        self._tool_call_indices[call_id] = self._tool_call_count
        self._navigation_before[call_id] = _navigation_summary(self.context)
        if self.verbose:
            self._log_pre_tool(block, tool_index=self._tool_call_count)

        guard = self._guard_tool_call(block)
        if guard is not None:
            return guard

        return None

    def post_tool_use(self, block: dict[str, Any], output: Any, *, step_count: int) -> None:
        name = block.get("name", "")
        call_id = str(block.get("id") or "")
        tool_index = self._tool_call_indices.get(call_id, self._tool_call_count)
        self.context.last_tool_result = {"step_name": name, "result": output}
        self.steps_taken.append({"tool": name, "input": block.get("input", {})})
        payload = output if isinstance(output, dict) else {"result": output}
        self.context.execution_trace.append({
            "index": tool_index - 1,
            "tool": name,
            "input": block.get("input", {}),
            "status": payload.get("status") or ("failed" if is_failed_tool_output(output) else "completed"),
            "message": payload.get("message"),
            "error": payload.get("error"),
            "result": output,
            "navigation_before": self._navigation_before.get(call_id),
            "navigation_after": _navigation_summary(self.context),
        })
        if is_failed_tool_output(output):
            self.context.last_failed_action = {"tool": name, "input": block.get("input", {}) or {}}
        elif name == (self.context.last_failed_action or {}).get("tool"):
            self.context.last_failed_action = None
        if name == "resolve_activities":
            self.has_resolved_ref["value"] = True
            if self.context.active_skill_id == "analyze-activity":
                self._append_activity_sport_reference()
        if _is_terminal_analysis_result(name, output):
            self.final_response_only = True
        if self.verbose:
            self._log_post_tool(block, output, tool_index=tool_index)

    def _append_activity_sport_reference(self) -> None:
        """Load sport guidance from trusted selected records after resolution."""
        from agent.skills import get_skill, load_sport_references

        skill = get_skill(self.context.active_skill_id)
        if skill is None:
            return
        sport_types = [
            str(activity.get("sport_type") or "")
            for activity in self.context.selected_activities
            if isinstance(activity, dict)
        ]
        reference_sections = load_sport_references(skill, sport_types=sport_types)
        if reference_sections:
            self.context.pending_skill_reference = (
                "[结构化活动类型参考]\n" + "\n\n".join(reference_sections)
            )

    def _guard_tool_call(self, block: dict[str, Any]) -> dict[str, Any] | None:
        from agent.main_agent.guard import guard_tool_call

        guard = guard_tool_call(
            block.get("name", ""),
            block.get("input", {}),
            context=self.context,
            allowed_categories=self.allowed_cats,
            allowed_tool_names=self.allowed_tool_names,
            has_resolved=self.has_resolved_ref["value"],
        )
        if not guard.allowed:
            return {"error": "guarded", "reason": guard.reason}
        return None

    @staticmethod
    def _log_pre_tool(block: dict[str, Any], *, tool_index: int) -> None:
        fmt = _format_tool_args(block)
        name = str(block.get("name") or "")
        _log(f"  [#{tool_index}] \033[33m→\033[0m \033[1m{_tool_label(name)}\033[0m [{name}]：{fmt}")

    @staticmethod
    def _log_post_tool(block: dict[str, Any], output: Any, *, tool_index: int) -> None:
        _log(f"  [#{tool_index}] \033[32m←\033[0m {_summarize_output(str(block.get('name') or ''), output)}")


def _navigation_summary(context: Any) -> dict[str, Any]:
    """Return compact navigation facts suitable for logs, never full ID sets."""
    navigation = getattr(context, "analysis_navigation", None)
    if not isinstance(navigation, dict):
        return {"root_type": None, "root_count": 0, "focus_type": None}
    root = navigation.get("root_scope") if isinstance(navigation.get("root_scope"), dict) else {}
    stack = navigation.get("focus_stack") if isinstance(navigation.get("focus_stack"), list) else []
    focus = stack[-1] if stack and isinstance(stack[-1], dict) else {}
    return {
        "root_type": root.get("type"),
        "root_count": len(root.get("ids") or ([root.get("id")] if root.get("id") else [])),
        "focus_type": focus.get("type"),
        "focus_id": focus.get("id"),
        "depth": len(stack),
    }


def _log(msg: str) -> None:
    import sys
    print(f"\033[2m[agent]\033[0m {msg}", file=sys.stderr, flush=True)


def _format_tool_args(block: dict[str, Any]) -> str:
    import json

    name = str(block.get("name") or "")
    args = block.get("input") if isinstance(block.get("input"), dict) else {}
    if name in {"resolve_activities", "lookup_activities"}:
        kind = str(args.get("kind") or "")
        labels = {
            "recent": "最近活动", "date": "指定日期", "range": "日期范围",
            "current": "当前活动", "all": "全部活动", "key": "活动 ID",
            "index": "活动序号", "name": "活动名称",
        }
        if kind == "all" and args.get("order") == "earliest" and args.get("limit") == 1:
            parts = ["全库最早活动"]
        else:
            parts = [labels.get(kind, kind or "未指定范围")]
        if args.get("limit"):
            parts.append(f"{args['limit']} 条")
        if args.get("time_of_day"):
            parts.append(_time_of_day_label(args["time_of_day"]))
        if args.get("date") or args.get("date_local"):
            parts.append(_date_label(args.get("date") or args.get("date_local")))
        if args.get("sport_type"):
            parts.append(str(args["sport_type"]))
        return " · ".join(parts)
    if name == "summarize_activities":
        return "读取已有报告，缺失时补齐后汇总"
    if name == "find_segments":
        ordinal = f" · 第 {args['ordinal']} 个" if args.get("ordinal") else ""
        return f"{args.get('segment_type') or 'effort'}{ordinal}"
    if name == "inspect_selection":
        return "轻量检查当前活动/集合/片段焦点"
    if name == "analyze_selection":
        return f"{args.get('objective') or 'inspect_activity'} · {args.get('depth') or 'inspect'}"
    if name == "navigate_selection":
        ordinal = f" · 第 {args['ordinal']} 个" if args.get("ordinal") else ""
        return f"{args.get('action') or 'current'}{ordinal}"
    if name == "calculate_history_metrics":
        return f"读取结构化指标 · 按 {args.get('group_by') or 'week'} 聚合"
    if name == "analyze_training_history":
        sport = args.get("sport_type") or ("合并运动量" if args.get("combine_sports_for_volume") else "按已选运动类型")
        return f"专业历史分析 · {sport} · 按 {args.get('group_by') or 'week'} 对比"
    if name == "analyze_activity":
        return "读取单条完整报告，缺失时生成"
    if name == "query_activity_detail":
        return f"FIT 定向问题：{str(args.get('question') or '').strip() or '未提供'}"
    if name == "sync_garmin_activities":
        return f"最近 {args.get('count') or 5} 条 · 仅下载并更新索引"
    if name in {"run_activity_workflow", "sync_and_run_activity_workflow"}:
        goals = ", ".join(str(goal) for goal in args.get("goals") or ["ensure_summary"])
        count = args.get("count") or args.get("limit") or 5
        return f"{count} 条活动 · {goals}"
    if name in {"get_activity_workflow", "retry_activity_workflow"}:
        return f"工作流 {args.get('workflow_id') or '未提供'}"
    if name == "rebuild_activity_reports":
        return f"后台重建 V2 报告 · {args.get('scope') or 'all'}"
    if name == "get_activity_report_job":
        return f"报告任务 {args.get('job_id') or '未提供'}"
    return ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in args.items()) or "no args"


def _summarize_output(name: str, output: Any) -> str:
    if isinstance(output, dict):
        nested = output.get("result") if isinstance(output.get("result"), dict) else {}
        payload = nested or output
        if output.get("error"):
            return f"未完成：{output.get('message') or output.get('error')}"
        if name in {"resolve_activities", "lookup_activities"}:
            activities = payload.get("activities") if isinstance(payload.get("activities"), list) else []
            labels = "；".join(_activity_label(item) for item in activities[:3] if isinstance(item, dict))
            return f"找到 {payload.get('count', len(activities))} 条活动" + (f"：{labels}" if labels else "")
        if name in {"analyze_activity", "query_activity_detail"}:
            source = str(payload.get("source") or "")
            text = {
                "existing_summary": "已读取已有报告",
                "generated_summary": "已生成完整报告",
                "targeted_query": "已完成 FIT 定向查询",
                "analysis_agent_error": "分析引擎返回降级报告",
            }.get(source, "已完成活动分析")
            return text
        if name == "summarize_activities":
            generation = payload.get("summary_generation") if isinstance(payload.get("summary_generation"), dict) else {}
            generated = generation.get("generated_count", 0)
            skipped = generation.get("skipped_count", 0)
            return f"已汇总 {payload.get('count', 0)} 条活动（读取已有报告 {skipped} 条，补齐 {generated} 条）"
        if name == "find_segments":
            return f"已定位 {payload.get('count', 0)} 个 {payload.get('segment_type') or '片段'}"
        if name in {"inspect_selection", "analyze_selection"}:
            analysis = payload.get("analysis") if isinstance(payload.get("analysis"), dict) else {}
            target = payload.get("target") if isinstance(payload.get("target"), dict) else {}
            return f"已分析 {len(target.get('activity_ids') or [])} 条活动（{analysis.get('status') or output.get('status') or 'completed'}）"
        if name == "navigate_selection":
            focus = payload.get("current_focus") if isinstance(payload.get("current_focus"), dict) else {}
            return f"当前焦点：{focus.get('type') or 'none'}"
        if name == "calculate_history_metrics":
            coverage = payload.get("coverage") if isinstance(payload.get("coverage"), dict) else {}
            return (
                f"已计算 {coverage.get('included_activity_count', 0)} 条活动的历史指标"
                f"（{payload.get('group_by') or 'week'}）"
            )
        if name == "analyze_training_history":
            coverage = payload.get("coverage") if isinstance(payload.get("coverage"), dict) else {}
            conclusion = payload.get("conclusion") if isinstance(payload.get("conclusion"), dict) else {}
            return (
                f"已分析 {coverage.get('activity_count', 0)} 条活动"
                f"（{conclusion.get('assessment') or 'insufficient_data'}，"
                f"置信度 {conclusion.get('confidence') or 'low'}）"
            )
        if name == "sync_garmin_activities":
            return (
                f"同步完成：下载 {int(payload.get('downloaded') or 0)} 条，"
                f"跳过 {int(payload.get('skipped') or 0)} 条，失败 {int(payload.get('failed') or 0)} 条；未分析"
            )
        if name in {"run_activity_workflow", "sync_and_run_activity_workflow", "retry_activity_workflow"}:
            workflow_id = output.get("workflow_id") or payload.get("workflow_id")
            status = output.get("status") or payload.get("status") or "completed"
            return f"工作流 {workflow_id or ''}：{status}".rstrip("：")
        if name in {"rebuild_activity_reports", "get_activity_report_job"}:
            return (
                f"报告任务 {payload.get('job_id') or ''}：{payload.get('status') or 'unknown'}"
                f"（{int(payload.get('completed') or 0)}/{int(payload.get('total') or 0)}）"
            )
        if "status" in output:
            return f"完成：{output.get('status')}"
        analysis_error = nested.get("analysis_error") if isinstance(nested.get("analysis_error"), dict) else None
        if analysis_error:
            return f"分析异常：{analysis_error.get('type')}"
    return "已完成"


def _tool_label(name: str) -> str:
    return {
        "resolve_activities": "定位活动",
        "lookup_activities": "临时查询活动",
        "find_segments": "定位活动片段",
        "inspect_selection": "初步检查",
        "analyze_selection": "分析当前焦点",
        "navigate_selection": "切换分析焦点",
        "analyze_activity": "查看活动报告",
        "query_activity_detail": "查询 FIT 细节",
        "summarize_activities": "汇总活动",
        "compare_activities": "对比活动",
        "calculate_history_metrics": "计算历史指标",
        "analyze_training_history": "分析训练历史",
        "sync_garmin_activities": "同步 Garmin 活动",
        "sync_and_run_activity_workflow": "同步并处理活动",
        "run_activity_workflow": "处理本地活动",
        "get_activity_workflow": "查看工作流",
        "retry_activity_workflow": "重试工作流",
        "rebuild_activity_reports": "重建 V2 报告",
        "get_activity_report_job": "查看报告任务",
    }.get(name, name)


def _time_of_day_label(value: Any) -> str:
    return {"morning": "上午", "afternoon": "下午", "evening": "晚上", "night": "夜间"}.get(str(value), str(value))


def _date_label(value: Any) -> str:
    return {"today": "今天", "yesterday": "昨天"}.get(str(value).lower(), str(value))


def _activity_label(activity: dict[str, Any]) -> str:
    started = str(activity.get("start_time_local") or activity.get("date_local") or "未知时间")
    name = str(activity.get("summary_label") or activity.get("file_name") or activity.get("activity_key") or "活动")
    return f"{started} {name}"


def _is_terminal_analysis_result(name: str, output: Any) -> bool:
    """These tools already return the evidence/state needed for the final answer.

    The next model turn may write prose, but must not start another analysis,
    sync, upload, or workflow operation.
    """
    terminal_tools = {
        "analyze_activity",
        "query_activity_detail",
        "summarize_activities",
        "compare_activities",
        "generate_training_advice",
        "summarize_recent_training_load",
        "calculate_history_metrics",
        "analyze_training_history",
        "inspect_selection",
        "analyze_selection",
        "generate_route_advice",
        "sync_garmin_activities",
        "sync_and_run_activity_workflow",
        "run_activity_workflow",
        "get_activity_workflow",
        "retry_activity_workflow",
        "rebuild_activity_reports",
        "get_activity_report_job",
    }
    if name not in terminal_tools:
        return False
    if not isinstance(output, dict) or output.get("error") or is_failed_tool_output(output):
        return False
    if name in {
        "sync_garmin_activities",
        "sync_and_run_activity_workflow",
        "run_activity_workflow",
        "get_activity_workflow",
        "retry_activity_workflow",
        "rebuild_activity_reports",
        "get_activity_report_job",
    }:
        return output.get("status") not in {None, "failed", "busy", "not_found"}
    return output.get("status") == "completed"
