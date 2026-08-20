---
name: sync-garmin-activities
description: Download recent Garmin activities into the local library and stop. Use only for pure sync or download requests that do not also request analysis, reports, summaries, or Strava upload.
---

# Sync Garmin Activities

Call `sync_garmin_activities` once with the requested count. This operation downloads and indexes activities only. Do not generate reports, invoke an analysis agent, publish to Strava, or create a multi-step workflow.

Set `force_download=true` only when the user explicitly says an already downloaded Garmin activity itself was edited or asks to refresh its original FIT. A newly synced phone activity uses the normal path.
