"""Compatibility exports for pre-V2 Python callers.

New code must import from :mod:`agent.activity.operations.service`.  Keeping
this small facade avoids silently breaking third-party scripts while the V2
layout is adopted.
"""

from agent.activity.operations.service import (
    MAX_SYNC_COUNT,
    analyze_fit_document,
    analyze_fit_file_tool,
    check_garmin_connection,
    sync_garmin_activities_tool,
    upload_summary_document,
    upload_to_strava_tool,
)

__all__ = [
    "MAX_SYNC_COUNT",
    "analyze_fit_document",
    "analyze_fit_file_tool",
    "check_garmin_connection",
    "sync_garmin_activities_tool",
    "upload_summary_document",
    "upload_to_strava_tool",
]
