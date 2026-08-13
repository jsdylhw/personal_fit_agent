---
name: run-activity-workflow
description: Start, inspect, retry, or rebuild a recoverable multi-step activity job. Use for combined goals such as sync then analyze or upload, local batch report generation, workflow status, and workflow recovery.
---

# Run Activity Workflow

Choose one coarse workflow tool and pass the user's terminal goals. Do not improvise a sequence of atomic operations in the main-agent loop.

- Use `sync_and_run_activity_workflow` only when Garmin sync is explicitly combined with report generation, aggregation, or Strava upload.
- Use `run_activity_workflow` for local activities already present in SQLite.
- Use the report rebuild job for an explicit bulk rebuild.
- Use get or retry tools with the persisted identifier for status and recovery.

Report the persisted workflow or job status. Do not claim completion from a submitted or partial state.
