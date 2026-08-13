---
name: analyze-training-history
description: Summarize, compare, or calculate trends across multiple activities using structured metrics. Use for recent ranges, weekly or monthly load, progress, consistency, fatigue signals, and matched-session comparisons.
---

# Analyze Training History

Resolve the requested range once with a typed `resolve_activities` call; successful resolution freezes its activity order. Use `kind=recent` for a count, `kind=range` for a period, and `kind=all` only for explicit all-history requests. A requested range limit belongs in that same call and is applied after filtering. Use `inspect_selection` for a report-free structured overview. Use `summarize_activities` only when generated report narratives are explicitly useful, and use `compare_activities` for the established deterministic cross-activity comparison. Use `analyze_selection` for a bounded structured objective that the older specialized tools do not cover. Use `calculate_history_metrics` for weekly/monthly trends and `summarize_recent_training_load` for load-specific facts.

Use `navigate_selection` for "the second one" and similar follow-ups. Never call a single-activity report tool once per item in the range, and never generate missing reports merely to inspect a collection.

Read structured activity metrics rather than extracting numbers from generated prose. Separate sports unless the user asks for combined volume. Distinguish observed changes from interpretation and state coverage, missing sensors, threshold changes, and confounders before claiming fitness or fatigue.
