"""Planner 输出使用的粗粒度工作流步骤语言.

这里定义的是业务步骤,不是底层工具名.后续 selector/executor 再负责
把这些步骤映射到具体工具和执行逻辑.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class WorkflowStepSpec:
    name: str
    description: str
    category: str
    requires: list[str] = field(default_factory=list)
    produces: list[str] = field(default_factory=list)
    side_effect: bool = False
    requires_confirmation: bool = False
    idempotent: bool = True
    max_retries: int = 1

    @property
    def requires_current_fit(self) -> bool:
        """兼容旧字段:当前 FIT 文件现在通过 requires 表达."""
        return "current_fit_file" in self.requires

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "requires": self.requires,
            "produces": self.produces,
            "side_effect": self.side_effect,
            "requires_confirmation": self.requires_confirmation,
            "requires_current_fit": self.requires_current_fit,
            "idempotent": self.idempotent,
            "max_retries": self.max_retries,
        }


@dataclass(frozen=True)
class WorkflowPlanStep:
    name: str
    reason: str
    arguments: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "reason": self.reason,
            "arguments": self.arguments,
        }


@dataclass(frozen=True)
class WorkflowPlan:
    task_type: str
    steps: list[WorkflowPlanStep]
    activity_scope: dict[str, Any] = field(default_factory=dict)
    allow_side_effects: bool = False
    requires_confirmation: bool = False
    needs_user_clarification: bool = False
    clarifying_question: str | None = None
    final_output: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_type": self.task_type,
            "steps": [step.to_dict() for step in self.steps],
            "activity_scope": self.activity_scope,
            "allow_side_effects": self.allow_side_effects,
            "requires_confirmation": self.requires_confirmation,
            "needs_user_clarification": self.needs_user_clarification,
            "clarifying_question": self.clarifying_question,
            "final_output": self.final_output,
        }


WORKFLOW_STEP_SPECS: tuple[WorkflowStepSpec, ...] = (
    WorkflowStepSpec(
        name="casual_chat",
        description="处理不需要活动数据的问候或普通聊天.",
        category="conversation",
    ),
    WorkflowStepSpec(
        name="ask_user_clarification",
        description="当请求缺少必要范围或意图不明确时,向用户追问一个聚焦问题.",
        category="conversation",
    ),
    WorkflowStepSpec(
        name="resolve_current_activity",
        description="使用当前 FIT 文件或已经选中的活动作为分析对象.",
        category="activity_resolution",
        produces=["current_fit_file", "selected_activities"],
    ),
    WorkflowStepSpec(
        name="resolve_activity_by_date",
        description="按日期,名称,activity_key 或 activity_index 定位一条本地活动;activity_index 是时间正序编号,1 表示最早活动.",
        category="activity_resolution",
        produces=["current_fit_file", "selected_activities"],
    ),
    WorkflowStepSpec(
        name="resolve_activity_range",
        description="按本周,本月,最近一段时间或明确日期范围定位多条本地活动.",
        category="activity_resolution",
        produces=["selected_activities", "activity_range"],
    ),
    WorkflowStepSpec(
        name="resolve_recent_activities",
        description="定位本地活动列表中的最新/最早/最近 N 条记录;第一个通常表示最早,最后一个通常表示最新.",
        category="activity_resolution",
        produces=["selected_activities", "current_fit_file"],
    ),
    WorkflowStepSpec(
        name="analyze_single_activity",
        description="基于客观 FIT 数据和可选历史记录分析一条已选活动.",
        category="analysis",
        requires=["current_fit_file"],
        produces=["activity_analysis"],
    ),
    WorkflowStepSpec(
        name="summarize_activity_range",
        description="汇总、列出或生成多条活动的整体总结报告,例如最近 3 次活动概览、上个月有哪些活动、所有历史活动整体情况.",
        category="analysis",
        requires=["selected_activities"],
        produces=["range_summary"],
    ),
    WorkflowStepSpec(
        name="compare_with_history",
        description="将已选活动或活动范围与近期训练历史做对比.",
        category="analysis",
        requires=["selected_activities"],
        produces=["history_comparison"],
    ),
    WorkflowStepSpec(
        name="compare_activities",
        description="仅当用户明确要求比较、对比、差异、哪次更好时,对多条已选活动做横向对比.",
        category="analysis",
        requires=["selected_activities"],
        produces=["activity_comparison"],
    ),
    WorkflowStepSpec(
        name="generate_training_advice",
        description="根据活动数据和历史生成下一次训练或周训练建议.",
        category="coaching",
        requires=["selected_activities"],
        produces=["training_advice"],
    ),
    WorkflowStepSpec(
        name="summarize_recent_training_load",
        description="读取已选活动 summary,提取 TSS/IF/时长/距离等结构化近期训练负荷,不生成本地训练判断.",
        category="analysis",
        requires=["selected_activities"],
        produces=["training_load_summary"],
    ),
    WorkflowStepSpec(
        name="generate_route_advice",
        description="根据用户目标推荐路线约束或路线类型;如果已有 training_load_summary,可作为补充参考.",
        category="coaching",
        produces=["route_advice"],
    ),
    WorkflowStepSpec(
        name="sync_garmin_activities",
        description="在本地分析前下载最近的 Garmin 活动.",
        category="operation",
        side_effect=True,
        idempotent=False,
        produces=["synced_fit_files"],
    ),
    WorkflowStepSpec(
        name="analyze_new_fit_files",
        description="对上一步同步得到的新 FIT 文件运行保存型单活动分析.",
        category="operation",
        requires=["synced_fit_files"],
        produces=["activity_analysis"],
        side_effect=True,
        idempotent=False,
    ),
    WorkflowStepSpec(
        name="generate_summary_file",
        description="为已选 FIT 文件生成或刷新保存的 summary JSON.",
        category="operation",
        requires=["current_fit_file"],
        produces=["activity_summary"],
        side_effect=True,
    ),
    WorkflowStepSpec(
        name="ensure_activity_summaries",
        description="检查已选活动是否已有 summary,缺失时生成 summary;用户要求重新分析、刷新报告、重新大模型分析时应传 force=true.",
        category="operation",
        requires=["selected_activities"],
        produces=["activity_summaries"],
        side_effect=True,
    ),
    WorkflowStepSpec(
        name="upload_strava_activity",
        description="用户明确要求上传 Strava 时,直接调用上传工具;不生成或刷新分析报告,工具成功或错误结果都交给 LLM 总结.",
        category="strava",
        requires=["current_fit_file"],
        produces=["strava_upload_result"],
        side_effect=True,
        idempotent=False,
    ),
)


PLAN_JSON_SCHEMA: dict[str, Any] = {
    "task_type": "string",
    "steps": [
        {
            "name": "必须是 available_steps[].name 之一",
            "reason": "选择该步骤的简短原因",
            "arguments": "步骤级参数对象,没有参数时为 {}",
        }
    ],
    "activity_scope": "描述 current_activity/date/date_range/recent_range/newly_synced 等活动范围的对象",
    "allow_side_effects": "boolean",
    "requires_confirmation": "boolean",
    "needs_user_clarification": "boolean",
    "clarifying_question": "string 或 null",
    "final_output": "用户最终需要的输出名称数组",
}


def available_workflow_steps() -> list[WorkflowStepSpec]:
    return list(WORKFLOW_STEP_SPECS)


def available_workflow_steps_catalog() -> list[dict[str, Any]]:
    return [step.to_dict() for step in WORKFLOW_STEP_SPECS]


def workflow_steps_by_category(category: str) -> list[WorkflowStepSpec]:
    return [step for step in WORKFLOW_STEP_SPECS if step.category == category]


def get_workflow_step(name: str) -> WorkflowStepSpec | None:
    return next((step for step in WORKFLOW_STEP_SPECS if step.name == name), None)


def workflow_plan_from_dict(data: dict[str, Any]) -> WorkflowPlan:
    """把 LLM 输出的 JSON dict 转成 WorkflowPlan."""
    if not isinstance(data, dict):
        raise ValueError("workflow plan must be a JSON object")

    raw_steps = data.get("steps")
    if isinstance(raw_steps, dict):
        raw_steps = [raw_steps]
    if not isinstance(raw_steps, list):
        raise ValueError("workflow plan steps must be a list")

    steps: list[WorkflowPlanStep] = []
    for item in raw_steps:
        if not isinstance(item, dict):
            raise ValueError("workflow plan step must be an object")
        arguments = item.get("arguments")
        steps.append(
            WorkflowPlanStep(
                name=str(item.get("name") or ""),
                reason=str(item.get("reason") or ""),
                arguments=arguments if isinstance(arguments, dict) else {},
            )
        )

    activity_scope = data.get("activity_scope")
    final_output = data.get("final_output")
    return WorkflowPlan(
        task_type=str(data.get("task_type") or "unknown"),
        steps=steps,
        activity_scope=activity_scope if isinstance(activity_scope, dict) else {},
        allow_side_effects=bool(data.get("allow_side_effects")),
        requires_confirmation=bool(data.get("requires_confirmation")),
        needs_user_clarification=bool(data.get("needs_user_clarification")),
        clarifying_question=(
            str(data["clarifying_question"])
            if data.get("clarifying_question") is not None
            else None
        ),
        final_output=[
            str(item)
            for item in final_output
            if item is not None
        ] if isinstance(final_output, list) else [],
    )
