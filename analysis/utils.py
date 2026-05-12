from __future__ import annotations

from datetime import datetime
from typing import Any


def num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def serialize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value
