---
name: discover-routes
description: Recommend route ideas from an open-ended region, duration, distance, terrain, scenery, or training goal.
---

# Discover Routes

Use this Skill when the user wants suggestions but has not supplied a complete route skeleton. Call `generate_route_advice` for route type and constraints, then create a persisted route only when the conversation contains enough real places.

- When a selected idea is a named or area-specific classic closed loop in mainland China, call `create_popular_loop`.
- When the selected idea has explicit endpoints or waypoints, call `create_route_plan`.
- When the selected idea spans days or morning/afternoon stages, call `create_itinerary_plan`.
- Do not invent precise landmarks merely to make a provider request succeed. Ask for a start point when it materially changes the route.
- Offer at most three meaningfully different candidates and distinguish their actual distance, duration, terrain intent, and provider warnings.

Use `update_route_plan` for subsequent concrete edits and `get_route_plan` to restore a saved plan.
