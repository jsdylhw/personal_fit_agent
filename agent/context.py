"""workflow agent 的运行期状态.

AgentContext 是一次 workflow 执行内共享的状态容器.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.activity.models import ActivityHandle


@dataclass
class AgentContext:
    """一次 workflow-agent 运行内共享的可变状态.

    活动定位:
      selected_handles       — 新接口: list[ActivityHandle]
      selected_activities    — 旧接口(兼容): list[dict], 与 handles 保持同步
      selected_activity_range — 活动范围元数据

    单活动快捷字段(兼容旧代码):
      current_fit_file / current_activity_key / current_summary_path

    内部缓存:
      pending_action / last_failed_action / current_todos / parsed / history_before
    """

    session_id: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    history_enabled: bool = True
    last_tool_result: dict[str, Any] | None = None
    last_failed_action: dict[str, Any] | None = None

    # 活动定位 — 新旧接口并存
    selected_handles: list[ActivityHandle] = field(default_factory=list)
    selected_activities: list[dict[str, Any]] = field(default_factory=list)
    selected_activity_range: dict[str, Any] | None = None

    # 单活动快捷字段
    current_fit_file: Path | None = None
    current_activity_key: str | None = None
    current_summary_path: Path | None = None

    # 内部缓存
    pending_action: dict[str, Any] | None = None
    current_todos: list[dict[str, Any]] = field(default_factory=list)
    todo_rounds_since_update: int = 0
    parsed: dict[str, Any] | None = None
    history_before: dict[str, Any] | None = None

    # -- 更新方法 --------------------------------------------------------

    def set_selected_activities(
        self,
        handles: list[ActivityHandle],
        *,
        scope: dict[str, Any] | None = None,
    ) -> None:
        """设置当前选中的活动(新旧字段同步)."""
        self.selected_handles = handles
        self.selected_activities = [h.to_dict() for h in handles]
        if scope is not None:
            self.selected_activity_range = scope
        if len(handles) == 1:
            self._sync_single_activity_fields(handles[0])

    def set_single_activity(self, handle: ActivityHandle) -> None:
        """设置单个选中活动."""
        self.set_selected_activities([handle], scope={"type": "single_activity"})

    def clear_activities(self) -> None:
        """清空活动选择."""
        self.selected_handles = []
        self.selected_activities = []
        self.selected_activity_range = None
        self.current_fit_file = None
        self.current_activity_key = None
        self.current_summary_path = None

    # -- 内部 ------------------------------------------------------------

    def _sync_single_activity_fields(self, handle: ActivityHandle) -> None:
        if handle.fit_path:
            self.current_fit_file = Path(handle.fit_path).expanduser()
        self.current_activity_key = handle.activity_key
        if handle.summary_path:
            self.current_summary_path = Path(handle.summary_path).expanduser()
