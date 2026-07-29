"""Hard-coded hooks used by the agent tool loop."""

from __future__ import annotations

from typing import Any

from agent.main_agent.tool_result import is_failed_tool_output


class ToolLoopHooks:
    """Fixed hook order for the tool loop."""

    def __init__(self, context, allowed_cats, has_resolved_ref, steps_taken, *, verbose=False):
        self.context = context
        self.allowed_cats = allowed_cats
        self.has_resolved_ref = has_resolved_ref
        self.steps_taken = steps_taken
        self.verbose = verbose
        self.final_response_only = False

    def before_llm_call(self) -> dict[str, str] | None:
        return None

    def on_tool_round(self) -> None:
        return None

    def on_error(self, block: dict[str, Any], error: Exception) -> dict[str, Any] | None:
        return None

    def on_loop_end(self, *, messages: list[dict[str, Any]], response: dict[str, Any], steps: int) -> None:
        return None

    def pre_tool_use(self, block: dict[str, Any], *, step_count: int) -> dict[str, Any] | None:
        if self.verbose:
            self._log_pre_tool(block, step_count=step_count)

        guard = self._guard_tool_call(block)
        if guard is not None:
            return guard

        return None

    def post_tool_use(self, block: dict[str, Any], output: Any, *, step_count: int) -> None:
        name = block.get("name", "")
        self.context.last_tool_result = {"step_name": name, "result": output}
        self.steps_taken.append({"tool": name, "input": block.get("input", {})})
        if is_failed_tool_output(output):
            self.context.last_failed_action = {"tool": name, "input": block.get("input", {}) or {}}
        elif name == (self.context.last_failed_action or {}).get("tool"):
            self.context.last_failed_action = None
        if name == "find_activity" or name.startswith("resolve_"):
            self.has_resolved_ref["value"] = True
        if _is_terminal_analysis_result(name, output):
            self.final_response_only = True
        if self.verbose:
            self._log_post_tool(block, output, step_count=step_count)

    def _guard_tool_call(self, block: dict[str, Any]) -> dict[str, Any] | None:
        from agent.main_agent.guard import guard_tool_call

        guard = guard_tool_call(
            block.get("name", ""),
            block.get("input", {}),
            context=self.context,
            allowed_categories=self.allowed_cats,
            has_resolved=self.has_resolved_ref["value"],
        )
        if not guard.allowed:
            return {"error": "guarded", "reason": guard.reason}
        return None

    @staticmethod
    def _log_pre_tool(block: dict[str, Any], *, step_count: int) -> None:
        fmt = _format_tool_args(block)
        name = str(block.get("name") or "")
        _log(f"  [{step_count}] \033[33m→\033[0m \033[1m{_tool_label(name)}\033[0m [{name}]：{fmt}")

    @staticmethod
    def _log_post_tool(block: dict[str, Any], output: Any, *, step_count: int) -> None:
        _log(f"  [{step_count}] \033[32m←\033[0m {_summarize_output(str(block.get('name') or ''), output)}")


def _log(msg: str) -> None:
    import sys
    print(f"\033[2m[agent]\033[0m {msg}", file=sys.stderr, flush=True)


def _format_tool_args(block: dict[str, Any]) -> str:
    import json

    name = str(block.get("name") or "")
    args = block.get("input") if isinstance(block.get("input"), dict) else {}
    if name == "find_activity":
        scope = _inferred_find_scope(args)
        labels = {"recent": "最近活动", "activity": "指定活动", "range": "日期范围", "current": "当前活动"}
        parts = [labels.get(scope, scope)]
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
    if name == "analyze_activity":
        return "读取单条完整报告，缺失时生成"
    if name == "query_activity_detail":
        return f"FIT 定向问题：{str(args.get('question') or '').strip() or '未提供'}"
    if name in {"run_activity_workflow", "sync_and_run_activity_workflow"}:
        goals = ", ".join(str(goal) for goal in args.get("goals") or ["ensure_summary"])
        count = args.get("count") or args.get("limit") or 5
        return f"{count} 条活动 · {goals}"
    if name in {"get_activity_workflow", "retry_activity_workflow"}:
        return f"工作流 {args.get('workflow_id') or '未提供'}"
    return ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in args.items()) or "no args"


def _summarize_output(name: str, output: Any) -> str:
    if isinstance(output, dict):
        nested = output.get("result") if isinstance(output.get("result"), dict) else {}
        payload = nested or output
        if output.get("error"):
            return f"未完成：{output.get('message') or output.get('error')}"
        if name == "find_activity":
            activities = payload.get("activities") if isinstance(payload.get("activities"), list) else []
            activity = payload.get("activity") if isinstance(payload.get("activity"), dict) else None
            if activity:
                return f"已定位：{_activity_label(activity)}"
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
        if name in {"run_activity_workflow", "sync_and_run_activity_workflow", "retry_activity_workflow"}:
            workflow_id = output.get("workflow_id") or payload.get("workflow_id")
            status = output.get("status") or payload.get("status") or "completed"
            return f"工作流 {workflow_id or ''}：{status}".rstrip("：")
        if "status" in output:
            return f"完成：{output.get('status')}"
        analysis_error = nested.get("analysis_error") if isinstance(nested.get("analysis_error"), dict) else None
        if analysis_error:
            return f"分析异常：{analysis_error.get('type')}"
    return "已完成"


def _tool_label(name: str) -> str:
    return {
        "find_activity": "定位活动",
        "analyze_activity": "查看活动报告",
        "query_activity_detail": "查询 FIT 细节",
        "summarize_activities": "汇总活动",
        "compare_activities": "对比活动",
        "sync_and_run_activity_workflow": "同步并处理活动",
        "run_activity_workflow": "处理本地活动",
        "get_activity_workflow": "查看工作流",
        "retry_activity_workflow": "重试工作流",
    }.get(name, name)


def _time_of_day_label(value: Any) -> str:
    return {"morning": "上午", "afternoon": "下午", "evening": "晚上", "night": "夜间"}.get(str(value), str(value))


def _date_label(value: Any) -> str:
    return {"today": "今天", "yesterday": "昨天"}.get(str(value).lower(), str(value))


def _inferred_find_scope(args: dict[str, Any]) -> str:
    if args.get("start_date") or args.get("end_date") or args.get("relative_range") or args.get("range_type"):
        return "range"
    if args.get("activity_key") or args.get("activity_index") or args.get("date") or args.get("date_local") or args.get("name"):
        return "activity"
    if args.get("current") is True:
        return "current"
    return "recent"


def _activity_label(activity: dict[str, Any]) -> str:
    started = str(activity.get("start_time_local") or activity.get("date_local") or "未知时间")
    name = str(activity.get("summary_label") or activity.get("file_name") or activity.get("activity_key") or "活动")
    return f"{started} {name}"


def _is_terminal_analysis_result(name: str, output: Any) -> bool:
    """These tools already return the evidence needed for the user-facing answer.

    The next model turn may write prose, but must not start another analysis or
    accidentally turn a read-only detail query into a forced summary refresh.
    """
    if name not in {
        "analyze_activity",
        "query_activity_detail",
        "summarize_activities",
        "compare_activities",
        "generate_training_advice",
        "summarize_recent_training_load",
        "generate_route_advice",
    }:
        return False
    if not isinstance(output, dict) or output.get("error") or is_failed_tool_output(output):
        return False
    return output.get("status") == "completed"
