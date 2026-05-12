from __future__ import annotations

from pathlib import Path
from typing import Any

from core.storage import archive_fit


def import_fit_file(path: str | Path, source: str = "manual") -> dict[str, Any]:
    return archive_fit(path, source=source)


def import_fit_folder(folder: str | Path, source: str = "local_folder") -> list[dict[str, Any]]:
    root = Path(folder).expanduser()
    if not root.exists():
        raise FileNotFoundError(root)
    if not root.is_dir():
        raise NotADirectoryError(root)
    return [archive_fit(path, source=source) for path in sorted(root.glob("*.fit"))]
