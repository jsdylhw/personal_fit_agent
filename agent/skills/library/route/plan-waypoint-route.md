---
name: plan-waypoint-route
description: Create and edit routes with explicit endpoints, waypoint sequences, days, or day parts.
---

# Plan Waypoint Route

Use `create_route_plan` for a concrete single-day route with one to three meaningfully different waypoint sequences. Use `create_itinerary_plan` for multiple days or one day split into morning and afternoon.

- Mainland China uses AMap bicycling; other countries use Google Places and Google Routes.
- A `loop` closes itself. Never repeat the first waypoint at the end.
- Every landmark or corridor explicitly required by the user must be an explicit waypoint.
- `target_distance_km` is a target; report provider-returned distance.
- For mainland China, `segment_strategy=auto` may enrich the route between hard waypoint anchors. Use `ignore` for provider-only routing and `require` only when Strava evidence is mandatory.
- For staged plans, adjacent stage endpoints must remain within the handoff tolerance. A short transfer does not require selecting a hotel.

Use `update_route_plan` for follow-up edits: `replace_waypoint`, `replace_waypoints`, `replace_stage`, deterministic `reverse_candidate` or `reverse_stage`, `select_candidate`, and `undo`. Use `get_route_plan` to restore the latest saved plan. Use `explore_route_segments` only when the user asks for nearby Strava context after a route exists.

Elevation is reference enrichment only. Do not claim live traffic, road safety, street-view continuity, or exact surface grade.
