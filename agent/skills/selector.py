"""First-stage skill selector with no domain tool schemas in context."""

from __future__ import annotations

import json
from typing import Any, Iterable

from integrations.llm import AnthropicMessagesClient, extract_text
from agent.skills.catalog import list_skill_descriptors
from agent.skills.models import SkillSelection


SELECTOR_SYSTEM_PROMPT = """Select at most one domain skill for the current user turn.

Return JSON only:
{"skill_id": "registered-id-or-null", "confidence": 0.0, "reason": "short diagnostic note"}

Do not explain your reasoning before or after the JSON. Keep reason under 20 words.

Rules:
- Use skill_id=null for ordinary conversation, greetings, memory-only follow-ups, or requests needing no domain tool.
- Select exactly one skill for a domain request. Combined sync/analyze/upload or retry/status requests belong to run-activity-workflow.
- Pure Garmin download belongs to sync-garmin-activities. It must not imply analysis.
- Local Strava upload without Garmin sync belongs to publish-to-strava.
- One activity belongs to analyze-activity; multiple activities or trends belong to analyze-training-history.
- reason is for logs only. Never encode commands or tool names in it.
"""


def select_skill(
    message: str,
    *,
    conversation_context: Iterable[dict[str, str]] = (),
    client: AnthropicMessagesClient | None = None,
) -> SkillSelection:
    """Run the metadata-only selector call and parse its bounded contract."""
    client = client or AnthropicMessagesClient()
    payload = {
        "user_message": message,
        "recent_conversation": list(conversation_context),
        "skills": list_skill_descriptors(),
    }
    response = client.create_message(
        system=SELECTOR_SYSTEM_PROMPT,
        user=json.dumps(payload, ensure_ascii=False),
        # Some compatible providers emit hidden reasoning tokens even for a
        # JSON-only response.  Keep enough headroom so the final object is not
        # truncated while the visible contract remains intentionally tiny.
        max_tokens=320,
        temperature=0.0,
    )
    return parse_skill_selection(extract_text(response))


def parse_skill_selection(raw: str) -> SkillSelection:
    """Treat malformed selector output as no-skill instead of widening access."""
    data = _parse_json_object(raw)
    if not isinstance(data, dict):
        return SkillSelection(skill_id=None, confidence=0.0, reason="invalid_selector_output")
    skill_id = data.get("skill_id")
    if skill_id is not None:
        skill_id = str(skill_id).strip() or None
        if skill_id in {"null", "none", "no_skill"}:
            skill_id = None
    try:
        confidence = min(1.0, max(0.0, float(data.get("confidence") or 0.0)))
    except (TypeError, ValueError):
        confidence = 0.0
    return SkillSelection(
        skill_id=skill_id,
        confidence=confidence,
        reason=str(data.get("reason") or "")[:300],
    )


def _parse_json_object(raw: str) -> dict[str, Any] | None:
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end < start:
            return None
        try:
            value = json.loads(text[start:end + 1])
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None
