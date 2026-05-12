from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.config import ensure_data_dirs


def write_analysis_report(result: dict[str, Any]) -> Path:
    paths = ensure_data_dirs()
    report_path = paths["reports"] / f"activity_{result['activity_id']}.md"
    observations = result["analysis"].get("observations", [])
    lines = [
        f"# Activity {result['activity_id']} Analysis",
        "",
        "## Summary",
        "",
        "```json",
        json.dumps(result["summary"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Observations",
        "",
    ]
    lines.extend([f"- {item}" for item in observations] or ["- 暂无观察。"])
    lines.extend(
        [
            "",
            "## LLM Context",
            "",
            "```json",
            json.dumps(result["analysis"]["llm_context"], ensure_ascii=False, indent=2),
            "```",
        ]
    )
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path
