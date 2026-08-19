---
name: plan-routes
description: Recommend and persist riding routes, then optionally enrich them with nearby Strava Segment context. Do not use for activity analysis, Garmin sync, or Strava activity upload.
---

# Plan Routes

For general training strategy without concrete places, call `generate_route_advice`.

For a concrete single-day route, call `create_route_plan` with one to three explicit candidate waypoint sequences:

- Use `country_code=CN` for mainland China; the service uses AMap bicycling and converts its display geometry to WGS-84.
- Use the actual country code elsewhere; the service uses Google Places and Google Routes. Japan may return the documented DRIVE fallback for virtual-only use.
- Set `route_type=loop` when the route must return to its first waypoint. Do not repeat the first waypoint yourself.
- Distinct candidates must use meaningfully different waypoint skeletons, not cosmetic names for the same sequence.
- Named landmarks or corridors requested by the user must appear explicitly in `waypoints`; never assume the provider will pass through an omitted place.
- `target_distance_km` is a validation target, not proof that the provider result will match. Report the actual returned distance.
- For mainland China, use `segment_strategy=auto` unless the user explicitly asks for the shortest/provider-only route (`ignore`) or requires Strava evidence (`require`). Explicit waypoints remain hard anchors. The planner may use compact Strava Segment evidence between anchors, but only provider-connected candidates replace the baseline.
- Put preferences such as popular roads, lake views, low climbing or classic climbs in `segment_preferences`; do not encode them as invented waypoint names.

For a multi-day trip or one day split into morning and afternoon, call `create_itinerary_plan`:

- Use `schedule_type=multi_day` for two or more days and `schedule_type=day_parts` for stages within one day.
- Each candidate contains ordered `stages`. Every stage has `day`, `period`, `label` and its own explicit waypoint sequence.
- Adjacent stages may use different named anchors, but their resolved endpoints must be within `handoff_tolerance_km` (default 5 km). This represents a short transfer, not hotel selection.
- Large differences between daily distances are warnings, not route failures. Report them and let the user adjust a stage conversationally.
- Use `period=full_day` for a whole riding day; use `morning` and `afternoon` when the user requests an intra-day split.
- The same `segment_strategy` applies independently to every stage; failed `auto` enrichment keeps that stage's verified baseline route.

For follow-up changes to the current route, call `update_route_plan`. Use `replace_waypoints` for a complete single-day candidate, `replace_stage` for a complete itinerary stage, and `replace_waypoint` when only one named point changes. Use `reverse_candidate` or `reverse_stage` for deterministic direction reversal; do not reconstruct the reversed list yourself. Use `undo` when the user asks to revert the last persisted route edit, and `select_candidate` when the user chooses an existing candidate. The tool loads the latest persisted plan when `plan_id` is omitted.

Call `get_route_plan` when the user asks to restore, show or summarize the current saved route without changing it.

Call `explore_route_segments` after a route exists when the user asks which popular Strava riding segments are on or near it. The result is a bounded popularity-ranked Explorer sample, not a complete road inventory. Treat Segment distance and grade as route context; do not silently replace the provider-verified route with Segment geometry.

Treat elevation as reference enrichment only. Do not claim live traffic, road safety, street-view continuity, exact road-surface grade, hotel availability or weather unless a dedicated verified source is added.
