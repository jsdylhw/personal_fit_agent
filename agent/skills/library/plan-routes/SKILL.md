---
name: plan-routes
description: Recommend a route type, duration, distance, terrain, and training constraints. Use for route or riding-destination advice, not for activity analysis or Garmin and Strava operations.
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

For follow-up changes to the current route, call `update_route_plan`. Use `replace_waypoints` when the user changes required places, direction or loop shape; use `select_candidate` when the user chooses an existing candidate. The tool loads the latest persisted plan when `plan_id` is omitted.

Call `get_route_plan` when the user asks to restore, show or summarize the current saved route without changing it.

Treat elevation as reference enrichment only. Do not claim live traffic, road safety, street-view continuity, exact road-surface grade, hotel availability or weather unless a dedicated verified source is added.
