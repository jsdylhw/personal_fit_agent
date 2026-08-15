"""Stable runtime results shared by CLI, evaluation and future HTTP adapters."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolExecution:
    """One attempted tool call with enough evidence for logs and presentation."""

    index: int
    tool: str
    input: dict[str, Any] = field(default_factory=dict)
    status: str = "completed"
    message: str | None = None
    error: str | None = None
    result: Any = None
    navigation_before: dict[str, Any] | None = None
    navigation_after: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_step(self) -> dict[str, Any]:
        return {"tool": self.tool, "input": self.input}


@dataclass
class TurnResult:
    """Transport-neutral result of one user turn.

    ``to_dict`` preserves the legacy keys used by the CLI and tests while
    adding a uniform ``executions`` collection for Chat API and Artifacts.
    """

    answer: str
    status: str
    context: Any
    intent: str
    skill_id: str | None = None
    executions: list[ToolExecution] = field(default_factory=list)
    selected_activities: list[dict[str, Any]] = field(default_factory=list)
    current_fit_file: str | None = None
    log_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        value = {
            "answer": self.answer,
            "status": self.status,
            "context": self.context,
            "intent": self.intent,
            "skill_id": self.skill_id,
            "steps": [execution.to_step() for execution in self.executions],
            "executions": [execution.to_dict() for execution in self.executions],
            "selected_activities": self.selected_activities,
            "current_fit_file": self.current_fit_file,
        }
        if self.log_path:
            value["log_path"] = self.log_path
        return value


def executions_from_trace(
    trace: list[dict[str, Any]] | None,
    *,
    steps: list[dict[str, Any]] | None = None,
) -> list[ToolExecution]:
    """Normalize both full traces and legacy ``steps`` into one contract."""
    executions: list[ToolExecution] = []
    for position, item in enumerate(trace or []):
        if not isinstance(item, dict):
            continue
        executions.append(ToolExecution(
            index=int(item.get("index", position)),
            tool=str(item.get("tool") or ""),
            input=item.get("input") if isinstance(item.get("input"), dict) else {},
            status=str(item.get("status") or "completed"),
            message=str(item["message"]) if item.get("message") is not None else None,
            error=str(item["error"]) if item.get("error") is not None else None,
            result=item.get("result"),
            navigation_before=item.get("navigation_before") if isinstance(item.get("navigation_before"), dict) else None,
            navigation_after=item.get("navigation_after") if isinstance(item.get("navigation_after"), dict) else None,
        ))
    if executions:
        return executions
    for position, step in enumerate(steps or []):
        if isinstance(step, dict):
            executions.append(ToolExecution(
                index=position,
                tool=str(step.get("tool") or ""),
                input=step.get("input") if isinstance(step.get("input"), dict) else {},
            ))
    return executions
