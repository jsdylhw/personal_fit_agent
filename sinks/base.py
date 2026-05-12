from __future__ import annotations

from typing import Protocol


class ActivitySink(Protocol):
    name: str

    def upload_fit(self, fit_path: str, *, title: str | None = None) -> dict:
        """Upload a FIT file to an external platform."""
        ...

    def update_description(self, activity_id: str, markdown: str) -> dict:
        """Update an external activity description."""
        ...
