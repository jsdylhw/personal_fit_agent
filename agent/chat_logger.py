"""对话日志:将 LLM 交互记录写入 log/ 目录的 JSONL + 可读 Markdown.

每次 LLM 调用追加一条日志。JSONL 适合程序读取,
同步生成同名 .md 文件方便人工查看 tool loop 过程。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

DEFAULT_CHAT_LOG_DIR = Path("log")


def new_session_id(prefix: str = "chat") -> str:
    """生成唯一 session ID:{prefix}_{UTC时间}_{随机8位hex}."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}_{timestamp}_{uuid4().hex[:8]}"


def append_chat_log(
    session_id: str, event: dict[str, Any], *, log_dir: str | Path = DEFAULT_CHAT_LOG_DIR,
    file_stem: str | None = None,
) -> Path:
    """追加一条事件记录到 JSONL 日志,同步更新 .md 可读日志.

    Args:
        session_id: 会话标识,记录在日志内容中.
        event: 要记录的事件 dict.
        log_dir: 日志目录,默认 log/.
        file_stem: 日志文件名(不含扩展名).有则用 {file_stem}.jsonl,无则用 {session_id}.jsonl.

    Returns:
        Path: JSONL 文件路径.
    """
    target_dir = Path(log_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    name = file_stem or session_id
    path = target_dir / f"{name}.jsonl"
    record = {"logged_at": datetime.now(timezone.utc).isoformat(), **event}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    append_readable_chat_log(path, record)
    return path


def readable_chat_log_path(path: str | Path) -> Path:
    """将 .jsonl 路径转为对应的 .md 路径."""
    source = Path(path)
    return source.with_suffix(".md")


def append_readable_chat_log(jsonl_path: Path, record: dict[str, Any]) -> Path:
    """追加一条可读事件到对应的 .md 日志."""
    path = readable_chat_log_path(jsonl_path)
    is_new = not path.exists()
    lines: list[str] = []
    if is_new:
        lines.extend([
            f"# Chat Log: {jsonl_path.stem}", "",
            f"- jsonl: `{jsonl_path}`", "",
        ])
    lines.extend(_format_record(record))
    with path.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip() + "\n\n")
    return path


def _format_record(record: dict[str, Any]) -> list[str]:
    event = str(record.get("event") or "event")
    logged_at = record.get("logged_at")
    lines = ["---", "", f"## {event}", "", f"- logged_at: `{logged_at}`"]
    for key in ["fit_path", "activity_key", "summary_path", "session_id"]:
        if record.get(key):
            lines.append(f"- {key}: `{record[key]}`")
    lines.append("")

    if event == "guided_activity_chat_turn":
        lines.extend(_markdown_block("User", record.get("user_message")))
        lines.extend(_markdown_block("Assistant", record.get("answer")))
        return lines

    if event == "direct_fit_analysis":
        lines.extend(_markdown_block("Question", record.get("question")))
        lines.extend(_markdown_block("Answer", record.get("answer")))
        return lines

    if event == "guided_activity_final_report":
        lines.append("Final guided report saved.")
        return lines

    if event == "fit_analysis_tool_loop":
        lines.extend(_format_tool_loop(record))
        return lines

    lines.extend(_markdown_block("Record Summary", _compact_json(record)))
    return lines


def _format_tool_loop(record: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    tone = record.get("strava_summary_tone")
    if tone:
        lines.extend(_markdown_block("Strava Summary Tone", _compact_json(tone)))

    turns = record.get("turns") if isinstance(record.get("turns"), list) else []
    if turns:
        lines.extend(["### Tool Loop Steps", ""])
        for turn in turns:
            if not isinstance(turn, dict):
                continue
            step = turn.get("step")
            kind = turn.get("type")
            lines.append(f"#### Step {step}: {kind}")
            lines.append("")
            if kind == "llm_response":
                parsed = turn.get("parsed")
                if isinstance(parsed, dict):
                    action = parsed.get("action")
                    tool = parsed.get("tool")
                    lines.append(f"- action: `{action}`")
                    if tool:
                        lines.append(f"- tool: `{tool}`")
                    if parsed.get("markdown_report"):
                        lines.extend(_markdown_block("Final Markdown Report", parsed.get("markdown_report")))
                    elif parsed.get("result") and isinstance(parsed["result"], dict):
                        result = parsed["result"]
                        if result.get("markdown_report"):
                            lines.extend(_markdown_block("Final Markdown Report", result.get("markdown_report")))
                else:
                    lines.extend(_markdown_block("Raw Response", turn.get("raw_text")))
            elif kind == "tool_result":
                lines.append(f"- tool: `{turn.get('tool')}`")
                if turn.get("error"):
                    lines.append(f"- error: `{turn.get('error')}`")
                result = turn.get("result")
                if result is not None:
                    lines.extend(_markdown_block("Result Preview", _preview_json(result)))
            lines.append("")

    parsed_response = record.get("parsed_response")
    if isinstance(parsed_response, dict):
        if parsed_response.get("markdown_report"):
            lines.extend(_markdown_block("Final Report", parsed_response.get("markdown_report")))
        if parsed_response.get("strava_summary"):
            lines.extend(_markdown_block("Strava Summary", parsed_response.get("strava_summary")))
    return lines


def _markdown_block(title: str, value: Any) -> list[str]:
    if value is None:
        return []
    text = str(value).strip()
    if not text:
        return []
    return [f"### {title}", "", text, ""]


def _compact_json(value: Any) -> str:
    return "```json\n" + json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n```"


def _preview_json(value: Any, limit: int = 1800) -> str:
    """JSON 预览,超长截断避免 .md 日志膨胀."""
    text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    if len(text) > limit:
        text = text[:limit].rstrip() + "\n... truncated"
    return "```json\n" + text + "\n```"
