# CLAUDE.md

This file provides guidance when working in this repository.

## Overview

Personal FIT Agent is a local sports data assistant: download Garmin China FIT files, generate activity reports via an LLM, maintain a SQLite activity catalogue, and optionally upload to Strava. The LLM backend uses an Anthropic Messages API-compatible endpoint from `config.yaml`.

## Commands

```bash
pip install -r requirements.txt
python -m pytest

python -m app.cli chat
python -m app.cli chat "分析最新的活动"
python -m app.cli analyze-file latest --force
python -m app.cli sync-garmin --count 5
python -m app.cli upload-strava ACTIVITY_KEY

python -m app.debug_cli list-activities --limit 10
python -m app.debug_cli inspect-fit latest
python -m app.debug_cli storage-status
```

## Architecture

The main path is native tool use:

```text
User message -> intent routing -> main_agent loop -> LLM tool_use -> TOOL_HANDLERS[name] -> direct local handler -> tool_result
```

There is no separate planner / validator / selector / executor stack. The LLM is capable of choosing tools directly; local code keeps the runtime thin and handles permission, guard checks, context, retries, and tool result formatting.

Key files:

- `agent/tools/agent_tools.py`: `MAIN_AGENT_TOOLS`, the coarse business tools exposed to the main agent.
- `agent/main_agent/loop.py`: LLM tool-use loop and CLI orchestration.
- `agent/main_agent/tools.py`: direct dispatch from tool name to Python handler.
- `agent/main_agent/handlers.py`: upload, summary generation, range summary handlers.
- `agent/main_agent/hooks.py`: logging, permission checks, guard checks, TODO display.
- `agent/activity/analysis_agent.py`: ActivityAnalysisAgent boundary for single-activity analysis.
- `agent/activity/report_jobs.py`: in-process bulk V2 report rebuilds.
- `core/storage/`: authoritative SQLite activity/report repositories.
- `agent/activity/resolution/executor.py`: direct activity resolution tool implementation.
- `agent/activity/report.py`, `comparison.py`, `training_load.py`: activity business handlers.
- `agent/route/advice.py`: route advice handler.

Single FIT analysis is owned by `agent/activity/analysis_agent.py`. It starts an independent `fit_analysis` child-agent session, exposes only read-only FIT data tools from `agent/tools/fit_analysis/`, and commits the current V2 report to SQLite. JSON is produced only by an explicit export and is never read as report state.
