---
name: plan-routes
description: Recommend a route type, duration, distance, terrain, and training constraints. Use for route or riding-destination advice, not for activity analysis or Garmin and Strava operations.
---

# Plan Routes

Call `generate_route_advice` with the user's location, duration or distance, goal, terrain, and preferences. Treat the result as route strategy rather than verified navigation: without map, weather, or traffic data, do not invent road names, live conditions, or precise directions.
