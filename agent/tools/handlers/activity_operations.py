"""Agent adapters for side-effecting activity operations."""

from __future__ import annotations

from typing import Any

from agent.main_agent.context import AgentContext


def sync_garmin_activities(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    from operations.activity.sync import sync_recent

    return sync_recent(count=int(args.get("count", 5)))


def sync_and_run_activity_workflow(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    from operations.activity.workflow_service import sync_and_start_activity_workflow

    return sync_and_start_activity_workflow(
        count=int(args.get("count", 5)),
        goals=args.get("goals") or ("ensure_summary",),
        force=bool(args.get("force")),
        force_upload=bool(args.get("force_upload")),
    )


def run_activity_workflow(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    from operations.activity.workflow_service import start_local_activity_workflow

    return start_local_activity_workflow(
        limit=int(args.get("limit", 5)),
        order=str(args.get("order") or "latest"),
        sport_type=str(args["sport_type"]) if args.get("sport_type") else None,
        goals=args.get("goals") or ("ensure_summary",),
        force=bool(args.get("force")),
        force_upload=bool(args.get("force_upload")),
    )


def rebuild_activity_reports(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    from operations.activity.report_batch import submit_activity_report_rebuild

    return submit_activity_report_rebuild(scope=str(args.get("scope") or "all"))


def get_activity_report_job(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    from operations.activity.report_batch import get_activity_report_job as get_job

    return get_job(str(args.get("job_id") or ""))


def get_activity_workflow(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    from operations.activity.workflow_service import get_activity_workflow as get_workflow

    return get_workflow(str(args.get("workflow_id") or ""))


def retry_activity_workflow(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    from operations.activity.workflow_service import retry_activity_workflow as retry_workflow

    task_ids = args.get("task_ids")
    return retry_workflow(
        str(args.get("workflow_id") or ""),
        task_ids=task_ids if isinstance(task_ids, list) else None,
    )


HANDLERS = {
    "sync_garmin_activities": sync_garmin_activities,
    "sync_and_run_activity_workflow": sync_and_run_activity_workflow,
    "run_activity_workflow": run_activity_workflow,
    "rebuild_activity_reports": rebuild_activity_reports,
    "get_activity_report_job": get_activity_report_job,
    "get_activity_workflow": get_activity_workflow,
    "retry_activity_workflow": retry_activity_workflow,
}
