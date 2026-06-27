"""Intent Router — 根据用户消息判断本轮可用的工具组.

不替代 Planner 的"规划步骤"能力,而是做更轻的判断:
- 用户想做什么类型的操作?
- 应该开放哪些工具组?
- 是否允许副作用?
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class IntentKind(str, Enum):
    CHAT = "chat"                       # 问候/闲聊
    ANALYZE_SINGLE = "analyze_single"   # 分析单条活动
    ANALYZE_RANGE = "analyze_range"     # 汇总多条活动
    COMPARE = "compare"                 # 对比活动
    TRAINING_LOAD = "training_load"     # 训练负荷
    TRAINING_ADVICE = "training_advice" # 训练建议
    ROUTE_ADVICE = "route_advice"       # 路线建议
    SYNC = "sync"                       # 下载 Garmin
    UPLOAD = "upload"                   # 上传 Strava
    MIXED = "mixed"                     # 多步骤混合


# 工具组 → ToolDef category 映射
TOOL_GROUP = {
    "resolve": {"activity_resolution"},
    "analyze": {"analysis"},
    "fit_query": {"fit_query"},
    "coaching": {"coaching"},
    "operation": {"operation"},
    "strava": {"strava"},
    "chat": {"conversation"},
}

# Intent → 默认开放的工具组
INTENT_TOOL_GROUPS: dict[IntentKind, set[str]] = {
    IntentKind.CHAT:           {"chat"},
    IntentKind.ANALYZE_SINGLE: {"resolve", "analyze", "fit_query"},
    IntentKind.ANALYZE_RANGE:  {"resolve", "analyze"},
    IntentKind.COMPARE:        {"resolve", "analyze"},
    IntentKind.TRAINING_LOAD:  {"resolve", "analyze"},
    IntentKind.TRAINING_ADVICE: {"resolve", "analyze", "coaching"},
    IntentKind.ROUTE_ADVICE:   {"coaching"},
    IntentKind.SYNC:           {"operation"},
    IntentKind.UPLOAD:         {"resolve", "strava", "operation"},
    IntentKind.MIXED:          {"resolve", "analyze", "fit_query", "coaching", "operation", "strava"},
}


@dataclass
class Intent:
    """用户请求的意图判断结果."""
    kind: IntentKind
    tool_groups: set[str] = field(default_factory=set)
    allow_side_effects: bool = False
    needs_confirmation: bool = False


def route_intent(user_message: str) -> Intent:
    """根据用户消息判断意图(关键词规则,轻量).

    对于无法明确判断的请求,返回 MIXED + 全工具组.
    """
    text = user_message.lower()

    # 闲聊
    greetings = {"你好", "hi", "hello", "hey", "谢谢", "thanks", "早", "晚上好"}
    if any(g in text for g in greetings) and len(text) < 20:
        return Intent(kind=IntentKind.CHAT, tool_groups=INTENT_TOOL_GROUPS[IntentKind.CHAT])

    # 副作用操作 — 检查是否混合意图(同步并分析/上传前分析)
    wants_sync = any(t in text for t in ("下载", "同步", "sync", "garmin"))
    wants_upload = any(t in text for t in ("上传", "strava", "upload"))
    wants_analyze = any(t in text for t in ("分析", "查看", "报告", "总结", "汇总"))

    if wants_sync and wants_analyze:
        return Intent(kind=IntentKind.MIXED,
                      tool_groups={"resolve", "analyze", "operation", "fit_query"},
                      allow_side_effects=True)

    if wants_sync and not wants_upload:
        return Intent(kind=IntentKind.SYNC, tool_groups=INTENT_TOOL_GROUPS[IntentKind.SYNC],
                      allow_side_effects=True)

    force_upload = any(t in text for t in ("强制上传", "force upload", "覆盖上传"))
    if wants_upload:
        return Intent(kind=IntentKind.UPLOAD, tool_groups=INTENT_TOOL_GROUPS[IntentKind.UPLOAD],
                      allow_side_effects=True, needs_confirmation=not force_upload)

    # 分析类
    wants_compare = any(t in text for t in ("比较", "对比", "差异", "哪次更好", "哪次更"))
    wants_route = any(t in text for t in ("路线", "骑哪里", "去哪骑", "推荐路线", "route"))
    wants_training_load = any(t in text for t in ("训练负荷", "tss", "疲劳", "恢复", "ct负荷", "ctl"))
    wants_training_advice = any(t in text for t in ("训练建议", "训练计划", "下次训练", "周训练"))

    if wants_compare:
        return Intent(kind=IntentKind.COMPARE, tool_groups=INTENT_TOOL_GROUPS[IntentKind.COMPARE])
    if wants_route:
        groups = INTENT_TOOL_GROUPS[IntentKind.ROUTE_ADVICE].copy()
        if any(t in text for t in ("最近训练", "训练状态", "训练负荷", "根据最近")):
            groups.add("resolve")
            groups.add("analyze")
        return Intent(kind=IntentKind.ROUTE_ADVICE, tool_groups=groups)
    if wants_training_advice:
        return Intent(kind=IntentKind.TRAINING_ADVICE, tool_groups=INTENT_TOOL_GROUPS[IntentKind.TRAINING_ADVICE])
    if wants_training_load:
        return Intent(kind=IntentKind.TRAINING_LOAD, tool_groups=INTENT_TOOL_GROUPS[IntentKind.TRAINING_LOAD])

    # 范围分析
    wants_range = any(t in text for t in ("汇总", "总结", "所有", "全部", "本月", "本周", "最近", "上个月",
                                           "这周", "这个月", "过去", "历史"))
    if wants_range:
        return Intent(kind=IntentKind.ANALYZE_RANGE, tool_groups=INTENT_TOOL_GROUPS[IntentKind.ANALYZE_RANGE])

    # 默认: 单活动分析
    return Intent(kind=IntentKind.ANALYZE_SINGLE, tool_groups=INTENT_TOOL_GROUPS[IntentKind.ANALYZE_SINGLE])


def intent_tool_categories(intent: Intent) -> set[str]:
    """将 intent.tool_groups 展开为具体的 ToolDef category 集合."""
    categories: set[str] = set()
    for group in intent.tool_groups:
        cats = TOOL_GROUP.get(group, set())
        categories.update(cats)
    return categories
