"""终端 agent 模式:让大模型按需调用完整工作流工具集.

这个模块和 analyze-file 的隐藏 FIT 分析 loop 不同:
- analyze-file 只暴露 6 个只读数据工具,用于单条 FIT 报告生成;
- workflow agent 暴露 8 个工具,包含 Garmin 下载,FIT 分析和 Strava 上传.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.chat_logger import append_chat_log, new_session_id, readable_chat_log_path
from agent.context import AgentContext
from agent.llm import AnthropicMessagesClient, extract_text
from agent.prompts import WORKFLOW_AGENT_SYSTEM_PROMPT
from agent.tools import agent_workflow_tool_catalog, call_fit_analysis_tool
from core.file_workflow import _extract_json_object
from core.history import query_activity_history
from fit.parser import parse_fit


MAX_WORKFLOW_AGENT_STEPS = 8


def run_workflow_agent(
    user_message: str,
    *,
    fit_path: str | Path | None = None,
    use_history: bool = True,
    max_steps: int = MAX_WORKFLOW_AGENT_STEPS,
) -> dict[str, Any]:
    """运行一次终端 agent 工作流.

    Args:
        user_message: 用户自然语言请求.
        fit_path: 可选的当前 FIT 文件.提供后,数据查询工具会针对它执行.
        use_history: 数据工具是否可读取历史.
        max_steps: 最多 LLM/tool 循环轮数.

    Returns:
        dict: {answer, session_id, log_path, readable_log_path, turns, current_fit_file}
    """
    current_fit = (
        _resolve_optional_fit_path(fit_path)
        if fit_path is not None
        else _infer_fit_path_from_message(user_message)
    )
    session_id = new_session_id("workflow_agent")
    context = AgentContext(
        session_id=session_id,
        current_fit_file=current_fit,
        history_enabled=use_history,
        parsed=parse_fit(current_fit) if current_fit else None,
    )
    context.history_before = (
        _history_for_parsed(context.parsed)
        if context.parsed and context.history_enabled
        else None
    )

    client = AnthropicMessagesClient()
    context.messages = [
        {
            "role": "user",
            "content": json.dumps(
                {
                    "instruction": "请根据用户请求决定是否调用工具.普通聊天直接回答即可.",
                    "user_message": user_message,
                    "current_fit_file": _context_fit_path_text(context),
                    "current_fit_source": "argument_or_message_match" if context.current_fit_file else None,
                    "history_enabled": bool(context.history_before),
                    "available_tools": agent_workflow_tool_catalog(),
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
        }
    ]
    turns: list[dict[str, Any]] = []
    final_answer: str | None = None
    last_response: dict[str, Any] | None = None

    for step in range(1, max(1, int(max_steps)) + 1):
        response = client.create_messages(
            system=WORKFLOW_AGENT_SYSTEM_PROMPT,
            messages=context.messages,
            max_tokens=2600,
        )
        last_response = response
        response_text = extract_text(response)
        action = _extract_workflow_action(response_text)
        turns.append({
            "step": step,
            "type": "llm_response",
            "raw_text": response_text,
            "parsed": action,
            "response": response,
        })
        context.messages.append({"role": "assistant", "content": response_text})

        if action.get("action") == "final" or action.get("answer"):
            final_answer = str(action.get("answer") or action.get("text") or response_text).strip()
            break

        if action.get("action") != "tool":
            tool_result = {
                "error": "invalid_action",
                "message": "Return action=tool to call a tool or action=final to answer.",
            }
        else:
            tool_name = str(action.get("tool") or "")
            arguments = action.get("arguments") if isinstance(action.get("arguments"), dict) else {}
            tool_result = call_fit_analysis_tool(
                tool_name,
                arguments,
                parsed=context.parsed,
                history_before=context.history_before,
            )
            _refresh_current_fit_after_tool(
                tool_name,
                tool_result,
                context=context,
            )

        context.last_tool_result = tool_result
        turns.append({"step": step, "type": "tool_result", **tool_result})
        context.messages.append({
            "role": "user",
            "content": json.dumps(
                {
                    "tool_result": tool_result,
                    "current_fit_file": _context_fit_path_text(context),
                    "instruction": "继续.如需更多信息可继续调用工具,否则返回 action=final.",
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
        })

    if final_answer is None:
        final_answer = "工具循环达到最大轮数,还没有得到最终回答.请缩小请求范围或提高 --max-steps."

    log_path = append_chat_log(
        session_id,
        {
            "event": "workflow_agent",
            "user_message": user_message,
            "current_fit_file": _context_fit_path_text(context),
            "system": WORKFLOW_AGENT_SYSTEM_PROMPT,
            "messages": context.messages,
            "turns": turns,
            "answer": final_answer,
            "model": (last_response or {}).get("model"),
        },
    )
    return {
        "answer": final_answer,
        "session_id": session_id,
        "log_path": str(log_path),
        "readable_log_path": str(readable_chat_log_path(log_path)),
        "current_fit_file": _context_fit_path_text(context),
        "turns": turns,
    }


def _extract_workflow_action(text: str) -> dict[str, Any]:
    try:
        data = _extract_json_object(text)
    except Exception:
        return {"action": "final", "answer": text.strip()}
    return data if isinstance(data, dict) else {"action": "final", "answer": text.strip()}


def _resolve_optional_fit_path(value: str | Path | None) -> Path | None:
    if value is None:
        return None
    from agent.guided_chat import resolve_fit_path

    return resolve_fit_path(value)


def _infer_fit_path_from_message(message: str) -> Path | None:
    """从用户自然语言里匹配本地 FIT 文件名.

    例如用户输入 "分析 594588818_ACTIVITY 这个 fit",这里会匹配
    `594588818_ACTIVITY.fit`.只做本地候选文件名/ stem 的保守匹配,
    不猜远程文件,也不递归扫描整个项目.
    """
    normalized = _normalize_fit_match_text(message)
    if not normalized:
        return None

    from agent.guided_chat import _iter_candidate_fit_files

    candidates = sorted(
        _iter_candidate_fit_files(),
        key=lambda path: len(path.name),
        reverse=True,
    )
    for path in candidates:
        name = _normalize_fit_match_text(path.name)
        stem = _normalize_fit_match_text(path.stem)
        if name and name in normalized:
            return path.resolve()
        if stem and stem in normalized:
            return path.resolve()
    return None


def _normalize_fit_match_text(value: str) -> str:
    return "".join(str(value).lower().split())


def _history_for_parsed(parsed: dict[str, Any]) -> dict[str, Any]:
    summary = parsed.get("summary", {})
    before = summary.get("start_time_local") or summary.get("start_time")
    return query_activity_history(before=before, days=90, limit=50)


def _context_fit_path_text(context: AgentContext) -> str | None:
    return str(context.current_fit_file) if context.current_fit_file else None


def _refresh_current_fit_after_tool(
    tool_name: str,
    tool_result: dict[str, Any],
    *,
    context: AgentContext,
) -> None:
    """分析工具返回 fit_path 后,把它设为 current_fit,方便后续数据查询工具使用."""
    if tool_name not in {"analyze_fit_file", "resolve_activity"} or "result" not in tool_result:
        context.history_before = (
            _history_for_parsed(context.parsed)
            if context.parsed and context.history_enabled
            else None
        )
        return

    result = tool_result.get("result") or {}
    if tool_name == "resolve_activity":
        activity = result.get("activity") if isinstance(result.get("activity"), dict) else {}
        candidate = activity.get("fit_path")
        activity_key = activity.get("activity_key")
        summary_path = activity.get("summary_path")
        if summary_path:
            context.current_summary_path = Path(summary_path)
    else:
        candidate = result.get("fit_path")
        activity_key = None
        summary_path = result.get("summary_path")
        if summary_path:
            context.current_summary_path = Path(summary_path)
    if not candidate:
        context.history_before = (
            _history_for_parsed(context.parsed)
            if context.parsed and context.history_enabled
            else None
        )
        return

    path = Path(candidate)
    if not path.exists():
        context.history_before = (
            _history_for_parsed(context.parsed)
            if context.parsed and context.history_enabled
            else None
        )
        return

    context.current_fit_file = path.resolve()
    if activity_key:
        context.current_activity_key = str(activity_key)
    context.parsed = parse_fit(path)
    context.history_before = (
        _history_for_parsed(context.parsed)
        if context.history_enabled
        else None
    )
