from __future__ import annotations

from typing import Protocol


class FitSource(Protocol):
    name: str

    def sync_latest(self, limit: int = 10) -> list[dict]:
        """Download or discover FIT files and archive them locally."""
        ...
