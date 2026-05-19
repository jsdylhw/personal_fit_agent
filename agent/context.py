"""workflow agent 的运行期状态."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AgentContext:
    """一次 workflow-agent 运行内共享的可变状态."""

    session_id: str
    current_fit_file: Path | None = None
    current_activity_key: str | None = None
    current_summary_path: Path | None = None
    selected_activities: list[dict[str, Any]] = field(default_factory=list)
    selected_activity_range: dict[str, Any] | None = None
    history_enabled: bool = True
    pending_action: dict[str, Any] | None = None
    last_tool_result: dict[str, Any] | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)

    # 当前 workflow loop 使用的内部运行期缓存.
    parsed: dict[str, Any] | None = None
    history_before: dict[str, Any] | None = None
