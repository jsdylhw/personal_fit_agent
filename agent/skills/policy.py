"""Runtime policy for validating skill activation and tool calls."""

from __future__ import annotations

from agent.skills.catalog import get_skill
from agent.skills.models import SkillSelection, SkillSpec

SKILL_CONFIDENCE_THRESHOLD = 0.70


def validate_skill_selection(selection: SkillSelection) -> SkillSpec | None:
    """Activate one known skill only when it clears the single threshold."""
    if selection.confidence < SKILL_CONFIDENCE_THRESHOLD:
        return None
    return get_skill(selection.skill_id)


def skill_allows_tool(skill: SkillSpec | None, tool_name: str) -> bool:
    """Enforce the second guard independently of disclosed tool schemas."""
    return skill is not None and tool_name in skill.tool_names
