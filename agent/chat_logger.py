from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


DEFAULT_CHAT_LOG_DIR = Path("data") / "chat_logs"


def new_session_id(prefix: str = "chat") -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}_{timestamp}_{uuid4().hex[:8]}"


def append_chat_log(
    session_id: str,
    event: dict[str, Any],
    *,
    log_dir: str | Path = DEFAULT_CHAT_LOG_DIR,
) -> Path:
    target_dir = Path(log_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{session_id}.jsonl"
    record = {
        "logged_at": datetime.now(timezone.utc).isoformat(),
        **event,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    return path
