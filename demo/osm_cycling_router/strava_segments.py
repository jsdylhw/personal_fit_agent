#!/usr/bin/env python3
"""Fetch a bounded Strava segment sample for route-ranking experiments.

This tool intentionally does not fetch athlete activities or scrape public
tracks.  It only stores the documented, bounded Segment Explorer response.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def explore_segments(
    bounds: str,
    access_token: str,
    *,
    base_url: str = "https://api-v3.strava.com",
    timeout_s: float = 30.0,
    retry_attempts: int = 2,
) -> dict[str, Any]:
    """Return Strava's top segment sample in one geographic bounding box."""
    values = [float(value.strip()) for value in bounds.split(",")]
    if len(values) != 4:
        raise ValueError("bounds must be south,west,north,east")
    query = urlencode({"bounds": ",".join(str(value) for value in values), "activity_type": "riding"})
    request = Request(
        f"{base_url.rstrip('/')}/segments/explore?{query}",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
    )
    payload = _read_json_with_retry(request, timeout_s=timeout_s, retry_attempts=retry_attempts)
    return {
        "schema_version": "strava_segment_sample.v1",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "bounds_wgs84": values,
        "source": "strava_segments_explore",
        "segment_count": len(payload.get("segments") or []),
        "segments": payload.get("segments") or [],
    }


def _read_json_with_retry(request: Request, *, timeout_s: float, retry_attempts: int) -> dict[str, Any]:
    """Retry only transient network/5xx failures; never weaken TLS validation."""
    attempts = max(1, int(retry_attempts))
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=timeout_s) as response:
                payload = json.load(response)
            if not isinstance(payload, dict):
                raise RuntimeError("Strava returned a non-object JSON response")
            return payload
        except HTTPError as exc:
            last_error = exc
            retryable = exc.code == 429 or 500 <= exc.code < 600
        except URLError as exc:
            last_error = exc
            retryable = True
        if not retryable or attempt == attempts - 1:
            break
        time.sleep(1 + attempt)
    assert last_error is not None
    raise RuntimeError(
        "Strava Segment Explorer request failed. "
        "Check the current network/TLS path or retry later; do not disable certificate validation."
    ) from last_error


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bounds", required=True, help="south,west,north,east in WGS-84")
    parser.add_argument("--output", type=Path, default=Path("data/strava-segment-sample.json"))
    parser.add_argument("--token-env", default="STRAVA_ACCESS_TOKEN")
    parser.add_argument("--base-url", default="https://api-v3.strava.com")
    args = parser.parse_args()
    token = os.environ.get(args.token_env, "").strip()
    if not token:
        parser.error(f"environment variable {args.token_env} is required")
    sample = explore_segments(args.bounds, token, base_url=args.base_url)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(sample, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {sample['segment_count']} segments to {args.output}")


if __name__ == "__main__":
    main()
