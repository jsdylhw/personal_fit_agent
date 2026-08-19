"""Agent adapter for route-advice generation."""

from __future__ import annotations

from typing import Any

from agent.main_agent.context import AgentContext
from integrations.llm import AnthropicMessagesClient, extract_text
from services.route.advice import generate_route_advice as generate_route_advice_service
from services.route.single_day import compact_route_plan, create_single_day_plan, replace_candidate
from storage.repositories.route import RoutePlanStore


def generate_route_advice(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    return generate_route_advice_tool(context, args=args, name="generate_route_advice")


def create_route_plan(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    return create_route_plan_tool(context, args=args, name="create_route_plan")


def update_route_plan(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    return update_route_plan_tool(context, args=args, name="update_route_plan")


def get_route_plan(args: dict[str, Any], context: AgentContext) -> dict[str, Any]:
    return get_route_plan_tool(context, args=args, name="get_route_plan")


def generate_route_advice_tool(
    context: AgentContext,
    *,
    args: dict[str, Any] | None = None,
    name: str = "generate_route_advice",
) -> dict[str, Any]:
    """Extract conversational inputs before calling the context-free service."""
    return generate_route_advice_service(
        args=args,
        training_load=_training_load(context),
        user_message=_latest_user_message(context),
        advisor=_request_route_advice,
        name=name,
    )


def create_route_plan_tool(
    context: AgentContext,
    *,
    args: dict[str, Any] | None = None,
    name: str = "create_route_plan",
) -> dict[str, Any]:
    args = args or {}
    candidates = args.get("candidates") if isinstance(args.get("candidates"), list) else []
    if not candidates and isinstance(args.get("waypoints"), list):
        candidates = [{
            "name": args.get("candidate_name") or "推荐路线",
            "waypoints": args["waypoints"],
            "route_type": args.get("route_type") or "point_to_point",
            "target_distance_km": args.get("target_distance_km"),
        }]
    plan = create_single_day_plan(
        workspace_id=_workspace_id(context),
        title=str(args.get("title") or "单日骑行路线"),
        country_code=str(args.get("country_code") or ""),
        candidates=candidates,
        include_elevation=bool(args.get("include_elevation", True)),
    )
    stored = RoutePlanStore().save(plan)
    compact = compact_route_plan(stored)
    return {
        "step": name,
        "status": "completed",
        "answer": _plan_answer(compact, prefix="已生成"),
        "result": compact,
    }


def update_route_plan_tool(
    context: AgentContext,
    *,
    args: dict[str, Any] | None = None,
    name: str = "update_route_plan",
) -> dict[str, Any]:
    args = args or {}
    store = RoutePlanStore()
    plan_id = str(args.get("plan_id") or "").strip()
    plan = _load_plan(store, context, plan_id)
    if not plan:
        raise ValueError("没有可更新的路线计划，请先创建单日路线")
    operation = str(args.get("operation") or "replace_waypoints")
    if operation == "select_candidate":
        selected_id = str(args.get("candidate_id") or "")
        valid_ids = {str(item.get("candidate_id")) for item in plan.get("candidates") or [] if isinstance(item, dict)}
        if selected_id not in valid_ids:
            raise ValueError("route candidate does not exist")
        plan = {**plan, "active_candidate_id": selected_id}
    elif operation == "replace_waypoints":
        waypoints = args.get("waypoints") if isinstance(args.get("waypoints"), list) else []
        plan = replace_candidate(
            plan,
            candidate_id=str(args.get("candidate_id") or "") or None,
            name=str(args.get("candidate_name") or ""),
            waypoint_queries=[str(value) for value in waypoints],
            route_type=str(args.get("route_type") or ""),
            target_distance_km=args.get("target_distance_km"),
            include_elevation=bool(args.get("include_elevation", True)),
        )
    else:
        raise ValueError("operation must be replace_waypoints or select_candidate")
    stored = store.save(plan)
    compact = compact_route_plan(stored)
    return {
        "step": name,
        "status": "completed",
        "answer": _plan_answer(compact, prefix="已更新"),
        "result": compact,
    }


def get_route_plan_tool(
    context: AgentContext,
    *,
    args: dict[str, Any] | None = None,
    name: str = "get_route_plan",
) -> dict[str, Any]:
    args = args or {}
    store = RoutePlanStore()
    plan_id = str(args.get("plan_id") or "").strip()
    plan = _load_plan(store, context, plan_id)
    if not plan:
        raise ValueError("没有已保存的路线计划")
    compact = compact_route_plan(plan)
    return {
        "step": name,
        "status": "completed",
        "answer": _plan_answer(compact, prefix="当前路线"),
        "result": compact,
    }


def _workspace_id(context: AgentContext) -> str:
    return str(context.workspace_id or context.session_id)


def _load_plan(
    store: RoutePlanStore,
    context: AgentContext,
    plan_id: str,
) -> dict[str, Any] | None:
    workspace_id = _workspace_id(context)
    plan = store.get(plan_id) if plan_id else store.get_latest(workspace_id)
    if plan and str(plan.get("workspace_id") or "") != workspace_id:
        raise ValueError("route plan does not belong to the current workspace")
    return plan


def _plan_answer(plan: dict[str, Any], *, prefix: str) -> str:
    candidates = [item for item in plan.get("candidates") or [] if isinstance(item, dict)]
    active_id = plan.get("active_candidate_id")
    active = next((item for item in candidates if item.get("candidate_id") == active_id), candidates[0] if candidates else {})
    return (
        f"{prefix}：{plan.get('title') or '单日路线'}；"
        f"当前候选 {active.get('name') or '-'}，{active.get('distance_km') or 0} km，"
        f"预计 {active.get('duration_min') or 0} 分钟。"
    )


def _request_route_advice(system: str, user: str) -> str:
    """Own the LLM call at the Agent boundary and return only its text."""
    response = AnthropicMessagesClient().create_message(
        system=system,
        user=user,
        max_tokens=1200,
        temperature=0.4,
    )
    return extract_text(response)


def _training_load(context: AgentContext) -> dict[str, Any] | None:
    last = context.last_tool_result
    result = last.get("result") if isinstance(last, dict) else None
    if isinstance(result, dict) and result.get("schema_version") == "training_load_summary.v1":
        return result
    return None


def _latest_user_message(context: AgentContext) -> str:
    for message in reversed(context.messages):
        if isinstance(message, dict) and message.get("role") == "user":
            return str(message.get("content") or "")
    return ""


HANDLERS = {
    "generate_route_advice": generate_route_advice,
    "create_route_plan": create_route_plan,
    "update_route_plan": update_route_plan,
    "get_route_plan": get_route_plan,
}
