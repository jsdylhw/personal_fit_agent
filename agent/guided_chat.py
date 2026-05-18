"""引导式活动分析与单轮直接问答.

和 core/file_workflow.py 的隐藏 tool loop 不同,这里的 guided/direct 模式不会
动态调用工具——程序一次性预计算所有数据视图(overview/summary/60s/1km/history),
作为静态背景上下文发给 LLM.LLM 只能基于这些预计算数据分析,不能再请求新窗口.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.chat_logger import append_chat_log, new_session_id, readable_chat_log_path
from agent.llm import AnthropicMessagesClient, extract_text
from agent.prompts import DIRECT_FIT_ANALYSIS_SYSTEM_PROMPT, GUIDED_ACTIVITY_CHAT_SYSTEM_PROMPT
from agent.tools import call_fit_analysis_tool
from core.history import query_activity_history
from fit.parser import parse_fit


class GuidedActivityChatSession:
    """Human-guided activity analysis chat backed directly by a FIT file."""

    def __init__(
        self,
        fit_path: str | Path,
        *,
        use_history: bool = True,
        session_id: str | None = None,
    ):
        self.fit_path = resolve_fit_path(fit_path)
        self.parsed = parse_fit(self.fit_path)
        self.history_before = _history_for_parsed(self.parsed) if use_history else None
        self.client = AnthropicMessagesClient()
        self.session_id = session_id or new_session_id("guided_activity_chat")
        self.messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "type": "background_context",
                        "instruction": (
                            "下面是本地 FIT 文件解析出的客观数据,只作为对话背景."
                            "不要假装知道这里没有的数据;需要用户补充主观感受,目标或训练安排时直接询问."
                        ),
                        "activity_context": build_fit_activity_context(
                            self.fit_path,
                            self.parsed,
                            history_before=self.history_before,
                            include_deep_data=True,
                        ),
                    },
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ),
            }
        ]

    def start(self) -> dict[str, Any]:
        return self.ask(
            "请开始一次人为引导的运动分析.先用很短的话说明你看到了哪次活动,"
            "然后提出 2-4 个最关键的问题,帮助我补充主观感受,训练目标和下一次安排."
            "不要现在直接写完整报告."
        )

    def ask(self, message: str) -> dict[str, Any]:
        self.messages.append({"role": "user", "content": message})
        response = self.client.create_messages(
            system=GUIDED_ACTIVITY_CHAT_SYSTEM_PROMPT,
            messages=self.messages,
            max_tokens=2200,
        )
        answer = extract_text(response)
        self.messages.append({"role": "assistant", "content": answer})
        log_path = self._log_event(
            {
                "event": "guided_activity_chat_turn",
                "fit_path": str(self.fit_path),
                "user_message": message,
                "answer": answer,
                "response": response,
            }
        )
        return {
            "answer": answer,
            "log_path": str(log_path),
            "readable_log_path": str(readable_chat_log_path(log_path)),
            "session_id": self.session_id,
            "fit_path": str(self.fit_path),
        }

    def finalize(
        self,
        instruction: str | None = None,
        *,
        update_summary: bool = True,
    ) -> dict[str, Any]:
        final_instruction = (
            "请基于本次多轮对话和活动背景,生成最终运动分析总结."
            "要求包含:总体评价,关键依据,主观信息如何影响判断,下一次训练建议,"
            "本周安排建议,恢复/拉伸/交叉训练建议."
            "如果用户没有补充的信息不足,明确写出不确定性."
        )
        if instruction:
            final_instruction += f"\n用户额外要求:{instruction}"

        result = self.ask(final_instruction)
        if update_summary:
            summary_path = update_guided_summary(
                self.fit_path,
                self.parsed,
                result["answer"],
                session_id=self.session_id,
                log_path=result.get("log_path"),
                readable_log_path=result.get("readable_log_path"),
                source="fit-chat",
            )
            result["summary_path"] = str(summary_path)
        return result

    def _log_event(self, event: dict[str, Any]) -> Path:
        return append_chat_log(
            self.session_id,
            {
                **event,
                "message_count": len(self.messages),
            },
        )


def direct_fit_analysis(
    fit_path: str | Path,
    question: str,
    *,
    use_history: bool = True,
    update_summary: bool = False,
) -> dict[str, Any]:
    """单轮直接问答:预计算数据视图 → 发送给 LLM → 返回回答.

    CLI fit-ask 命令的入口.

    Args:
        fit_path: FIT 文件路径或 "latest".
        question: 用户问题.
        use_history: 是否附带历史数据.
        update_summary: 是否写入 summary JSON.

    Returns:
        dict: {answer, fit_path, session_id, log_path, summary_path?}
    """
    path = resolve_fit_path(fit_path)
    parsed = parse_fit(path)
    history_before = _history_for_parsed(parsed) if use_history else None
    client = AnthropicMessagesClient()
    session_id = new_session_id("direct_fit_chat")
    user_payload = {
        "instruction": (
            "请基于下面的 FIT 文件客观数据直接回答用户问题."
            "这是单轮直接发送模式,不需要再要求用户必须进入多轮对话;"
            "但如果关键信息缺失,需要明确写出不确定性."
        ),
        "user_question": question,
        "activity_context": build_fit_activity_context(
            path,
            parsed,
            history_before=history_before,
            include_deep_data=True,
        ),
    }
    response = client.create_message(
        system=DIRECT_FIT_ANALYSIS_SYSTEM_PROMPT,
        user=json.dumps(user_payload, ensure_ascii=False, indent=2, default=str),
        max_tokens=3200,
    )
    answer = extract_text(response)
    log_path = append_chat_log(
        session_id,
        {
            "event": "direct_fit_analysis",
            "fit_path": str(path),
            "question": question,
            "answer": answer,
            "response": response,
        },
    )
    summary_path = None
    if update_summary:
        summary_path = update_guided_summary(
            path,
            parsed,
            answer,
            session_id=session_id,
            log_path=log_path,
            readable_log_path=readable_chat_log_path(log_path),
            source="fit-ask",
            user_question=question,
        )
    return {
        "answer": answer,
        "fit_path": str(path),
        "session_id": session_id,
        "log_path": str(log_path),
        "readable_log_path": str(readable_chat_log_path(log_path)),
        "summary_path": str(summary_path) if summary_path else None,
    }


def resolve_fit_path(value: str | Path) -> Path:
    text = str(value)
    if text == "latest":
        fit_files = sorted(
            _iter_candidate_fit_files(),
            key=lambda path: path.stat().st_mtime,
        )
        if not fit_files:
            raise FileNotFoundError("No FIT file found. Pass a FIT path explicitly.")
        return fit_files[-1].resolve()

    path = Path(value).expanduser()
    if path.is_dir():
        fit_files = sorted(path.glob("*.fit"), key=lambda item: item.stat().st_mtime)
        if not fit_files:
            raise FileNotFoundError(f"No *.fit found in {path}")
        return fit_files[-1].resolve()
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.lower() != ".fit":
        raise ValueError(f"Expected a .fit file: {path}")
    return path.resolve()


def build_fit_activity_context(
    fit_path: Path,
    parsed: dict[str, Any],
    *,
    history_before: dict[str, Any] | None,
    include_deep_data: bool,
) -> dict[str, Any]:
    """构建 guided/direct 模式的静态背景上下文.

    include_deep_data=True 时,预先计算所有数据视图(overview/summary/60s/1km/history)
    放入 precomputed_data_views.LLM 收到的是一份静态快照,无法再请求新窗口.

    Args:
        fit_path: FIT 文件路径.
        parsed: parse_fit() 的返回值.
        history_before: 历史活动数据.
        include_deep_data: 是否预计算完整数据视图.

    Returns:
        dict: {fit_path, fit_name, fit_summary, precomputed_data_views?, data_note?}
    """
    context: dict[str, Any] = {
        "fit_path": str(fit_path),
        "fit_name": fit_path.name,
        "fit_summary": parsed.get("summary", {}),
    }
    if not include_deep_data:
        return context

    # guided/direct 模式不会动态调用工具,一次性预计算所有数据视图作为静态快照
    context["precomputed_data_views"] = {
        "activity_overview": call_fit_analysis_tool(
            "get_activity_overview", {}, parsed=parsed, history_before=history_before,
        ).get("result"),
        "activity_summary": call_fit_analysis_tool(
            "get_activity_summary",
            {"sections": ["activity_identity", "duration_distance", "speed_pace", "power", "heart_rate", "cadence", "elevation", "energy_load", "data_availability"]},
            parsed=parsed, history_before=history_before,
        ).get("result"),
        "time_intervals_60s": call_fit_analysis_tool(
            "get_time_intervals", {"bucket_seconds": 60}, parsed=parsed, history_before=history_before,
        ).get("result"),
        "distance_intervals_1km": call_fit_analysis_tool(
            "get_distance_intervals", {"bucket_distance_m": 1000}, parsed=parsed, history_before=history_before,
        ).get("result"),
        "history": call_fit_analysis_tool(
            "get_history", {}, parsed=parsed, history_before=history_before,
        ).get("result"),
    }
    return {
        **context,
        "data_note": (
            "precomputed_data_views 是程序一次性预计算出的聚合数据视图(60s 时间窗口 + 1km 距离窗口)."
            "它们是静态快照,不是动态工具调用接口."
            "你可以基于这些数据分析,但不能声称调用了真实外部工具,也不能请求新的数据窗口."
        ),
    }


def update_guided_summary(
    fit_path: Path,
    parsed: dict[str, Any],
    markdown: str,
    *,
    session_id: str,
    log_path: str | Path | None,
    readable_log_path: str | Path | None,
    source: str,
    user_question: str | None = None,
) -> Path:
    summary_path = _summary_path(fit_path)
    summary = _read_existing_summary(summary_path)
    summary.setdefault("schema_version", "guided_fit_summary.v1")
    summary.setdefault("status", "guided_only")
    summary["fit_path"] = str(fit_path)
    summary["fit_summary"] = parsed.get("summary", {})

    updated_at = datetime.now(timezone.utc).isoformat()
    guided_analysis = {
        "schema_version": "guided_activity_analysis.v1",
        "source": source,
        "updated_at": updated_at,
        "session_id": session_id,
        "log_path": str(log_path) if log_path else None,
        "readable_log_path": str(readable_log_path) if readable_log_path else None,
        "user_question": user_question,
        "markdown_report": markdown,
    }
    summary["guided_analysis"] = guided_analysis

    history = summary.get("guided_analysis_history")
    if not isinstance(history, list):
        history = []
    history.append(
        {
            "source": source,
            "updated_at": updated_at,
            "session_id": session_id,
            "log_path": str(log_path) if log_path else None,
            "readable_log_path": str(readable_log_path) if readable_log_path else None,
            "user_question": user_question,
        }
    )
    summary["guided_analysis_history"] = history[-20:]

    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return summary_path


def _history_for_parsed(parsed: dict[str, Any]) -> dict[str, Any]:
    return query_activity_history(before=parsed.get("summary", {}).get("start_time"), days=90, limit=50)


def _iter_candidate_fit_files() -> list[Path]:
    roots = [
        Path("data") / "fit",
        Path("garmin_cn_fit_files"),
        Path.cwd(),
    ]
    files: list[Path] = []
    for root in roots:
        if root.exists():
            files.extend(path for path in root.glob("*.fit") if path.is_file())
    return files


def _summary_path(fit_path: Path) -> Path:
    return Path("data") / "summaries" / f"{fit_path.stem}.summary.json"


def _read_existing_summary(summary_path: Path) -> dict[str, Any]:
    if not summary_path.exists():
        return {}
    try:
        data = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}
