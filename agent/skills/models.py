"""Immutable models shared by the skill selector, loader, and guards."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SkillSpec:
    """One domain protocol and the exact main-agent tools it may expose."""

    skill_id: str
    description: str
    tool_names: tuple[str, ...]
    public_intent: str
    allow_side_effects: bool = False

    def public_descriptor(self) -> dict[str, str]:
        """Return metadata safe to include in the selector prompt."""
        return {"skill_id": self.skill_id, "description": self.description}


@dataclass(frozen=True)
class SkillSelection:
    """Structured first-stage result; reason is diagnostic only."""

    skill_id: str | None
    confidence: float
    reason: str = ""

    @property
    def activated(self) -> bool:
        return bool(self.skill_id)
