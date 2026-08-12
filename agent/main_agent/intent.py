"""Intent Router — 根据用户消息判断本轮可用的工具组.

不做显式规划,只做轻量意图判断:
- 用户想做什么类型的操作?
- 应该开放哪些工具组?
- 是否允许副作用?
"""

from __future__ import annotations

import re
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
    "resolve": {"activity_selection"},
    "analyze": {"analysis"},
    "fit_query": {"fit_query"},
    "coaching": {"coaching"},
    "operation": {"operation"},
    "workflow": {"workflow"},
    "chat": {"conversation"},
}

# Intent → 默认开放的工具组
INTENT_TOOL_GROUPS: dict[IntentKind, set[str]] = {
    IntentKind.CHAT:           {"chat"},
    IntentKind.ANALYZE_SINGLE: {"resolve", "analyze", "fit_query"},
    IntentKind.ANALYZE_RANGE:  {"resolve", "analyze", "workflow"},
    IntentKind.COMPARE:        {"resolve", "analyze"},
    IntentKind.TRAINING_LOAD:  {"resolve", "analyze"},
    IntentKind.TRAINING_ADVICE: {"resolve", "analyze", "coaching"},
    IntentKind.ROUTE_ADVICE:   {"coaching"},
    IntentKind.SYNC:           {"operation"},
    IntentKind.UPLOAD:         {"resolve", "operation", "workflow"},
    IntentKind.MIXED:          {"resolve", "analyze", "fit_query", "coaching", "operation", "workflow"},
}


@dataclass
class Intent:
    """用户请求的意图判断结果."""
    kind: IntentKind
    tool_groups: set[str] = field(default_factory=set)
    allow_side_effects: bool = False


@dataclass(frozen=True)
class RouteSignals:
    """Facts extracted from one user turn before choosing an Intent.

    These signals only control the capability surface exposed to the main
    model.  They do not prescribe a tool sequence or tool arguments.
    """

    wants_sync: bool = False
    wants_upload: bool = False
    wants_analyze: bool = False
    wants_compare: bool = False
    wants_route: bool = False
    wants_training_load: bool = False
    wants_training_advice: bool = False
    activity_scope: str = "unknown"  # single / range / unknown
    has_activity_signal: bool = False


def route_intent(user_message: str) -> Intent:
    """根据可审计的本地信号决定本轮能力范围。

    Main Agent 仍负责选择具体工具和参数；这里不做隐藏规划，也不额外调用
    一个路由模型。
    """
    text = user_message.lower()

    # 闲聊
    greetings = {"你好", "hi", "hello", "hey", "谢谢", "thanks", "早", "晚上好"}
    if text.strip(" \t\r\n!！?？,，。") in greetings:
        return Intent(kind=IntentKind.CHAT, tool_groups=INTENT_TOOL_GROUPS[IntentKind.CHAT])

    signals = extract_route_signals(text)

    # 同步后继续分析或上传属于同一个复合目标。此前只覆盖 sync+analyze，
    # 造成 sync+upload 被后面的 upload 分支吞掉。
    if signals.wants_sync and (signals.wants_analyze or signals.wants_upload):
        return Intent(
            kind=IntentKind.MIXED,
            tool_groups=INTENT_TOOL_GROUPS[IntentKind.MIXED].copy(),
            allow_side_effects=True,
        )

    if signals.wants_sync:
        return Intent(kind=IntentKind.SYNC, tool_groups=INTENT_TOOL_GROUPS[IntentKind.SYNC],
                      allow_side_effects=True)

    if signals.wants_upload:
        return Intent(kind=IntentKind.UPLOAD, tool_groups=INTENT_TOOL_GROUPS[IntentKind.UPLOAD],
                      allow_side_effects=True)

    # 分析类
    if signals.wants_compare:
        return Intent(kind=IntentKind.COMPARE, tool_groups=INTENT_TOOL_GROUPS[IntentKind.COMPARE])
    if signals.wants_route:
        groups = INTENT_TOOL_GROUPS[IntentKind.ROUTE_ADVICE].copy()
        if any(t in text for t in ("最近训练", "训练状态", "训练负荷", "根据最近")):
            groups.add("resolve")
            groups.add("analyze")
        return Intent(kind=IntentKind.ROUTE_ADVICE, tool_groups=groups)
    if signals.wants_training_advice:
        return Intent(kind=IntentKind.TRAINING_ADVICE, tool_groups=INTENT_TOOL_GROUPS[IntentKind.TRAINING_ADVICE])
    if signals.wants_training_load:
        return Intent(kind=IntentKind.TRAINING_LOAD, tool_groups=INTENT_TOOL_GROUPS[IntentKind.TRAINING_LOAD])

    has_analysis_context = signals.has_activity_signal or signals.wants_analyze
    if signals.activity_scope == "range" and has_analysis_context:
        return Intent(kind=IntentKind.ANALYZE_RANGE, tool_groups=INTENT_TOOL_GROUPS[IntentKind.ANALYZE_RANGE])

    # “最近”只表示排序，不再单独代表范围。“最近一次/最新一条”明确是
    # 单条；没有复数范围信号的活动问题也按单条开放工具。
    if has_analysis_context:
        return Intent(kind=IntentKind.ANALYZE_SINGLE, tool_groups=INTENT_TOOL_GROUPS[IntentKind.ANALYZE_SINGLE])

    return Intent(kind=IntentKind.CHAT, tool_groups=INTENT_TOOL_GROUPS[IntentKind.CHAT])


def extract_route_signals(user_message: str) -> RouteSignals:
    """提取稳定、可单测的路由事实，不选择任何具体工具。"""
    text = user_message.lower()
    wants_sync = _has_positive_action(text, ("下载", "同步", "sync", "garmin"))
    wants_upload = _has_positive_action(text, ("上传", "strava", "upload"))
    wants_analyze = _has_positive_action(text, ("分析", "查看", "报告", "总结", "汇总"))
    return RouteSignals(
        wants_sync=wants_sync,
        wants_upload=wants_upload,
        wants_analyze=wants_analyze,
        wants_compare=any(t in text for t in ("比较", "对比", "差异", "哪次更好", "哪次更")),
        wants_route=any(t in text for t in ("路线", "骑哪里", "去哪骑", "推荐路线", "route")),
        wants_training_load=any(t in text for t in ("训练负荷", "tss", "疲劳", "恢复", "ct负荷", "ctl")),
        wants_training_advice=any(t in text for t in ("训练建议", "训练计划", "下次训练", "周训练")),
        activity_scope=_activity_scope(text),
        has_activity_signal=_has_activity_signal(text),
    )


def intent_tool_categories(intent: Intent) -> set[str]:
    """将 intent.tool_groups 展开为具体的 ToolDef category 集合."""
    categories: set[str] = set()
    for group in intent.tool_groups:
        cats = TOOL_GROUP.get(group, set())
        categories.update(cats)
    return categories


def _has_positive_action(text: str, terms: tuple[str, ...]) -> bool:
    """识别操作意图，忽略“不要/不需要/无需”明确否定的关键词。"""
    negations = ("不要", "不需要", "无需", "不用", "别", "不必")
    for term in terms:
        start = 0
        while True:
            index = text.find(term, start)
            if index < 0:
                break
            # 中文否定通常紧挨在动词前；保留较短窗口避免吞掉上句的无关否定。
            prefix = text[max(0, index - 6):index]
            if not any(negation in prefix for negation in negations):
                return True
            start = index + len(term)
    return False


def _has_activity_signal(text: str) -> bool:
    """识别没有显式“分析”一词的单活动数据问题。"""
    signals = (
        "活动", "骑行", "骑车", "跑步", "训练", "fit", "功率", "心率", "踏频",
        "配速", "冲刺", "爬升", "公里", "距离", "速度", "tss", "if", "np",
        "这次", "本次", "这趟", "表现如何", "表现怎么样",
    )
    return any(signal in text for signal in signals)


_SINGLE_SCOPE_MARKERS = (
    "这次", "本次", "这趟", "当前活动", "最后一次", "最新一次", "最近一次",
    "最后一条", "最新一条", "最近一条", "最后一个", "最新一个", "最近一个",
)
_RANGE_SCOPE_MARKERS = (
    "汇总", "所有", "全部", "本月", "本周", "上个月", "上周", "这周", "这个月",
    "过去几", "最近几", "近几", "历史", "多次", "多条", "多个",
)
_PLURAL_COUNT_PATTERN = re.compile(
    r"(?:最近|最新|过去|前|近)?\s*(?:[2-9]\d*|[二两三四五六七八九十百]+)\s*(?:个|次|条|场|项|天|周|月)"
)
_SINGLE_COUNT_PATTERN = re.compile(
    r"(?:最近|最新|最后)?(?:的)?\s*(?:1|一)\s*(?:个|次|条|场|项)"
)


def _activity_scope(text: str) -> str:
    """区分单条与范围；裸“最近”不携带数量含义。"""
    # “汇总”明确要求集合式处理，即使集合只有 1 条也保持范围语义。
    if "汇总" in text:
        return "range"
    if any(marker in text for marker in _SINGLE_SCOPE_MARKERS) or _SINGLE_COUNT_PATTERN.search(text):
        return "single"
    if any(marker in text for marker in _RANGE_SCOPE_MARKERS) or _PLURAL_COUNT_PATTERN.search(text):
        return "range"
    return "unknown"
