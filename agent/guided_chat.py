from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.chat_logger import append_chat_log, new_session_id, readable_chat_log_path
from agent.llm import AnthropicMessagesClient, extract_text
from core.file_workflow import call_fit_analysis_tool
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
                            "下面是本地 FIT 文件解析出的客观数据，只作为对话背景。"
                            "不要假装知道这里没有的数据；需要用户补充主观感受、目标或训练安排时直接询问。"
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
            "请开始一次人为引导的运动分析。先用很短的话说明你看到了哪次活动，"
            "然后提出 2-4 个最关键的问题，帮助我补充主观感受、训练目标和下一次安排。"
            "不要现在直接写完整报告。"
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
        save_report: bool = True,
        update_summary: bool = True,
    ) -> dict[str, Any]:
        final_instruction = (
            "请基于本次多轮对话和活动背景，生成最终运动分析总结。"
            "要求包含：总体评价、关键依据、主观信息如何影响判断、下一次训练建议、"
            "本周安排建议、恢复/拉伸/交叉训练建议。"
            "如果用户没有补充的信息不足，明确写出不确定性。"
        )
        if instruction:
            final_instruction += f"\n用户额外要求：{instruction}"

        result = self.ask(final_instruction)
        report_path = None
        if save_report:
            report_path = write_guided_report(
                self.fit_path,
                result["answer"],
                session_id=self.session_id,
            )
            self._log_event(
                {
                    "event": "guided_activity_final_report",
                    "fit_path": str(self.fit_path),
                    "report_path": str(report_path),
                }
            )

        result["report_path"] = str(report_path) if report_path else None
        if update_summary:
            summary_path = update_guided_summary(
                self.fit_path,
                self.parsed,
                result["answer"],
                session_id=self.session_id,
                log_path=result.get("log_path"),
                readable_log_path=result.get("readable_log_path"),
                report_path=report_path,
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
    save_report: bool = False,
    update_summary: bool = False,
) -> dict[str, Any]:
    path = resolve_fit_path(fit_path)
    parsed = parse_fit(path)
    history_before = _history_for_parsed(parsed) if use_history else None
    client = AnthropicMessagesClient()
    session_id = new_session_id("direct_fit_chat")
    user_payload = {
        "instruction": (
            "请基于下面的 FIT 文件客观数据直接回答用户问题。"
            "这是单轮直接发送模式，不需要再要求用户必须进入多轮对话；"
            "但如果关键信息缺失，需要明确写出不确定性。"
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
    report_path = None
    if save_report:
        report_path = write_guided_report(path, answer, session_id=session_id)
    summary_path = None
    if update_summary:
        summary_path = update_guided_summary(
            path,
            parsed,
            answer,
            session_id=session_id,
            log_path=log_path,
            readable_log_path=readable_chat_log_path(log_path),
            report_path=report_path,
            source="fit-ask",
            user_question=question,
        )
    return {
        "answer": answer,
        "fit_path": str(path),
        "session_id": session_id,
        "log_path": str(log_path),
        "readable_log_path": str(readable_chat_log_path(log_path)),
        "report_path": str(report_path) if report_path else None,
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
    context: dict[str, Any] = {
        "fit_path": str(fit_path),
        "fit_name": fit_path.name,
        "fit_summary": parsed.get("summary", {}),
        "available_tools": [
            "get_activity_overview",
            "get_activity_summary",
            "get_time_intervals",
            "get_distance_intervals",
            "get_history",
        ],
    }
    if not include_deep_data:
        return context

    context["tool_results"] = {
        "get_activity_overview": call_fit_analysis_tool(
            "get_activity_overview",
            {},
            parsed=parsed,
            history_before=history_before,
        ).get("result"),
        "get_activity_summary": call_fit_analysis_tool(
            "get_activity_summary",
            {"sections": ["activity_identity", "duration_distance", "speed_pace", "power", "heart_rate", "cadence", "elevation", "energy_load", "data_availability"]},
            parsed=parsed,
            history_before=history_before,
        ).get("result"),
        "get_time_intervals_60s": call_fit_analysis_tool(
            "get_time_intervals",
            {"bucket_seconds": 60},
            parsed=parsed,
            history_before=history_before,
        ).get("result"),
        "get_distance_intervals_1km": call_fit_analysis_tool(
            "get_distance_intervals",
            {"bucket_distance_m": 1000},
            parsed=parsed,
            history_before=history_before,
        ).get("result"),
        "get_history": call_fit_analysis_tool(
            "get_history",
            {},
            parsed=parsed,
            history_before=history_before,
        ).get("result"),
    }
    return {
        **context,
        "data_note": (
            "这些 tool_results 是程序一次性提取出的客观数据。"
            "模型可以基于它们分析，但不能声称调用了真实外部工具。"
        ),
    }


def write_guided_report(fit_path: Path, markdown: str, *, session_id: str) -> Path:
    reports_dir = Path("data") / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = reports_dir / f"{fit_path.stem}.guided.{timestamp}.md"
    lines = [
        markdown.strip(),
        "",
        "## Guided Chat Metadata",
        "",
        f"- source_fit: `{fit_path}`",
        f"- session_id: `{session_id}`",
        "",
    ]
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def update_guided_summary(
    fit_path: Path,
    parsed: dict[str, Any],
    markdown: str,
    *,
    session_id: str,
    log_path: str | Path | None,
    readable_log_path: str | Path | None,
    report_path: str | Path | None,
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
        "report_path": str(report_path) if report_path else None,
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
            "report_path": str(report_path) if report_path else None,
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


GUIDED_ACTIVITY_CHAT_SYSTEM_PROMPT = """你是一个耐力运动分析对话助手，面向骑行、跑步和其他 FIT 活动。

你的任务不是一次性自动写完报告，而是通过多轮对话让用户补充关键信息，最后形成更可靠的总结。

工作方式：
- 已有本地程序直接从 FIT 文件提取出的摘要、数值统计、lap、采样记录、训练元数据和历史记录。
- 这些数据是客观背景，不等于最终结论。
- 你需要主动询问主观体感、训练目标、疲劳/睡眠、补给、路况、下一次可训练时间等信息。
- 用户只是打招呼或闲聊时，保持正常对话，不要自动输出完整活动报告。
- 用户要求分析时，先确认目标和主观感受；如果信息已经足够，再给阶段性判断。
- 用户输入 /final 对应的最终请求时，输出一份完整中文总结。

分析原则：
- 不允许只根据 TSS、IF、均功率下结论。
- 面向用户描述日期和时间时，优先使用 fit_summary.start_time_local；fit_summary.start_time 是 UTC，不要把 UTC 时间说成用户本地训练时间。
- 可以针对感兴趣片段做具体分析：例如爬坡、短时间冲刺、节奏段、滑行/停车、后半程掉速等。先用 60s、5min、1km、3km 这类粗粒度数据定位片段，再用 3-10s、30s、100-200s 或 2km-3km 这类小窗口解释细节。
- 分析爬坡时同时看海拔、速度、功率、踏频和心率反应；分析短冲刺或加速时同时看功率、踏频、速度变化，以及是否从滑行/低踏频开始。
- 如果数据质量或用户补充信息不足，要明确写出不确定性。
- 如果没有足够历史，不要假装判断长期进步。
- 训练建议要说明依据，并包含下一次训练、本周安排、恢复/拉伸/交叉训练建议。
- 保持中文回答，结构清楚，避免过度诊断。
"""


DIRECT_FIT_ANALYSIS_SYSTEM_PROMPT = """你是一个耐力运动分析助手，正在处理用户直接发送的一次 FIT 文件分析请求。

你会收到本地程序从 FIT 文件提取出的客观上下文，包括摘要、数值统计、lap、采样记录、训练元数据和可能的历史记录。

回答要求：
- 直接回答用户问题，不要要求用户再运行别的命令。
- 不允许只根据 TSS、IF、均功率下结论。
- 面向用户描述日期和时间时，优先使用 fit_summary.start_time_local；fit_summary.start_time 是 UTC，不要把 UTC 时间说成用户本地训练时间。
- 可以针对感兴趣片段做具体分析：例如爬坡、短时间冲刺、节奏段、滑行/停车、后半程掉速等。先用粗粒度数据定位片段，再用小窗口数据解释细节。
- 分析爬坡时同时看海拔、速度、功率、踏频和心率反应；分析短冲刺或加速时同时看功率、踏频、速度变化，以及是否从滑行/低踏频开始。
- 如果数据或主观信息不足，明确说明不确定性。
- 如果用户要求训练建议，给出下一次训练、本周安排、恢复/拉伸/交叉训练建议，并说明依据。
- 如果用户只是要简短回答，就保持简洁；如果用户要求完整分析，再输出结构化报告。
- 使用中文。
"""
