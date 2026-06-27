"""工具权限模块 — 三道闸门.

插在工具执行之前:
  Gate 1: 硬拒绝 — 命中即拦截
  Gate 2: 规则检查 — 命中需要用户审批
  Gate 3: 用户审批 — 交互式确认

使用:
    result = check_permission(tool_name, tool_input, has_confirmed=False)
    if not result.allowed:
        return result.block_message
    # 执行工具
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

# -- Gate 1: 硬拒绝表 ----------------------------------------------------

DENY_LIST: list[tuple[str, str]] = [
    # (工具名, 拒绝原因) — 无条件拦截
    # 当前无需硬拒绝的 planner 工具;保留接口用于后续扩展
    # 例如: ("delete_activity", "不可逆操作,已禁用"),
]


def check_deny_list(tool_name: str, args: dict[str, Any]) -> str | None:
    """Gate 1: 硬拒绝检查."""
    for deny_name, reason in DENY_LIST:
        if tool_name == deny_name:
            return reason
    return None


# -- Gate 2: 规则检查 ----------------------------------------------------

@dataclass
class PermissionRule:
    """权限规则: 匹配条件 → 审批消息."""
    tools: list[str]                                 # 匹配的工具名
    check: Callable[[dict[str, Any]], bool]           # 返回 True 表示需要审批
    message: str                                      # 审批时显示的消息


PERMISSION_RULES: list[PermissionRule] = [
    PermissionRule(
        tools=["upload_strava_activity"],
        check=lambda args: True,
        message="上传活动到 Strava (外部服务,有副作用)",
    ),
    PermissionRule(
        tools=["sync_garmin_activities"],
        check=lambda args: True,
        message="从 Garmin 中国下载活动 (外部服务,有副作用)",
    ),
    PermissionRule(
        tools=["generate_summary_file", "ensure_activity_summaries", "analyze_new_fit_files"],
        check=lambda args: True,
        message="生成/刷新 summary 文件 (会写入本地磁盘)",
    ),
]


def check_rules(tool_name: str, args: dict[str, Any]) -> str | None:
    """Gate 2: 规则检查. 返回审批消息或 None(放行)."""
    for rule in PERMISSION_RULES:
        if tool_name in rule.tools and rule.check(args):
            return rule.message
    return None


# -- Gate 3: 权限检查入口 --------------------------------------------------

@dataclass
class PermissionResult:
    allowed: bool
    reason: str = ""
    block_message: str = ""


def check_permission(
    tool_name: str,
    args: dict[str, Any],
    *,
    has_confirmed: bool = False,
) -> PermissionResult:
    """三道闸门串联.

    Args:
        tool_name: 工具名.
        args: 工具参数.
        has_confirmed: 用户是否已审批本轮.

    Returns:
        PermissionResult — allowed=True 放行, allowed=False 拦截.
    """
    # Gate 1: 硬拒绝
    deny_reason = check_deny_list(tool_name, args)
    if deny_reason:
        return PermissionResult(allowed=False, reason=deny_reason,
                                block_message=f"⛔ {deny_reason}")

    # Gate 2 + 3: 规则检查 → 如果用户已确认则放行,否则需要审批
    rule_reason = check_rules(tool_name, args)
    if rule_reason:
        if has_confirmed:
            return PermissionResult(allowed=True)
        return PermissionResult(allowed=False, reason=rule_reason,
                                block_message=f"⚠ {rule_reason}\n请回复 '确认' 来执行。")

    return PermissionResult(allowed=True)
