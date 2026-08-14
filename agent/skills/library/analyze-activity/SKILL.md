---
name: analyze-activity
description: Read or generate one activity report and answer focused FIT questions about intervals, sprints, power, heart rate, pace, or running dynamics. Use only for a single cycling, running, or walking activity.
---

# Analyze Activity

Resolve exactly one activity with a typed `resolve_activities` request before analysis and let successful resolution freeze the navigation focus.

- Use `kind=recent, limit=1` for the latest activity and `kind=date, limit=1` for a single activity on a specified day.
- If a frozen collection already exists and the user says “the second one”, use `navigate_selection`; do not resolve it by date or description again.

- For a general request, call `inspect_selection`; it reuses the lightweight FIT overview and does not create a report.
- For general sprint, interval, climb, or ordinal segment language, call `find_segments` first, then `analyze_selection` with a bounded objective. These are import-time candidates, not exact raw-data proof.
- If the user gives an explicit time or distance window (for example `100–200 秒`, `最后 20 分钟`, or `3–5 km`), first resolve exactly one activity and then call `query_activity_detail` with the original question. Its child Agent receives the matching raw interval tool and must use local FIT evidence; do not answer from candidates alone.
- For a typed objective use `analyze_selection`; use `answer_question` plus the original question only for a long-tail question.
- For a complete report explicitly requested by the user, call `analyze_activity`; reuse the stored V2 report unless rebuild was requested.
- Use `navigate_selection` for follow-ups such as "the second one", back, or root. Do not resolve a frozen recent set again.
- Do not call analysis once per item in a range.
- Base conclusions on returned evidence and identify missing sensors instead of inventing values.

The runtime appends the cycling, running, or walking reference only after a selected database activity identifies the sport.
