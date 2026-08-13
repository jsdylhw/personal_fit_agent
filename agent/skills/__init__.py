"""Project-local skill control plane for progressive tool disclosure."""

from agent.skills.catalog import SKILL_CATALOG, get_skill, list_skill_descriptors
from agent.skills.loader import load_skill_instructions, load_sport_references
from agent.skills.models import SkillSelection, SkillSpec
from agent.skills.selector import select_skill

__all__ = [
    "SKILL_CATALOG",
    "SkillSelection",
    "SkillSpec",
    "get_skill",
    "list_skill_descriptors",
    "load_skill_instructions",
    "load_sport_references",
    "select_skill",
]
