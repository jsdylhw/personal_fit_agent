"""Runtime state for the workflow agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AgentContext:
    """Mutable state shared across one workflow-agent run."""

    session_id: str
    current_fit_file: Path | None = None
    current_activity_key: str | None = None
    current_summary_path: Path | None = None
    history_enabled: bool = True
    pending_action: dict[str, Any] | None = None
    last_tool_result: dict[str, Any] | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)

    # Internal runtime cache used by the current workflow loop.
    parsed: dict[str, Any] | None = None
    history_before: dict[str, Any] | None = None
