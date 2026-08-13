---
name: manage-activity-library
description: Find and inspect activities already stored in the local library. Use for locating one or more activities without analysis, Garmin sync, Strava publishing, or training advice.
---

# Manage Activity Library

Translate the user's date, count, sport, time-of-day, name, or activity-key constraints into exactly one typed `resolve_activities` call. Return what is stored; do not generate reports or infer missing metrics.

- Use `kind=recent` for “latest/recent N activities”; do not add a date range.
- Use `kind=date` for one calendar day and `kind=range` for a period. A range `limit`, when requested, is applied after date filtering.
- Use `kind=all` only for explicit all-history requests.
- Use `kind=key`, `kind=index`, or `kind=name` only for an explicit stable identifier, global catalogue index, or name.
- Never mix fields belonging to different kinds.

Treat bare “latest” or “recent” as ordering. Treat an explicit plural count, time period, “all”, or comparison range as multiple activities. Use `navigate_selection` for references such as “the second one”, back, or root instead of resolving the frozen collection again. Ask one focused question only when two materially different selections remain possible.
