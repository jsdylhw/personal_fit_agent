# CLAUDE.md

This file provides guidance when working in this repository.

## Overview

Personal FIT Agent is a local sports data assistant: download Garmin China FIT files, generate activity reports via an LLM, maintain a local activity index, and optionally upload to Strava. The LLM backend uses an Anthropic Messages API-compatible endpoint from `config.yaml`.

## Commands

```bash
pip install -r requirements.txt
python -m pytest

python -m app.cli chat
python -m app.cli workflow "分析最新的活动" --json
python -m app.cli analyze-file latest --force
python -m app.cli sync-garmin --count 5
python -m app.cli upload-strava "data/summaries/activity.summary.json"

python -m app.debug_cli list-activities --limit 10
python -m app.debug_cli inspect-fit latest
```

## Architecture

The main path is native tool use:

```text
User message -> intent routing -> tool_loop -> LLM tool_use -> tool_runtime -> direct local handler -> tool_result
```

There is no separate planner / validator / selector / executor stack. The LLM is capable of choosing tools directly; local code keeps the runtime thin and handles permission, guard checks, context, retries, and tool result formatting.

Key files:

- `agent/tools/agent_tools.py`: outer tool-use definitions.
- `agent/workflow/tool_loop.py`: LLM tool-use loop and CLI orchestration.
- `agent/workflow/tool_runtime.py`: direct dispatch from tool name to Python handler.
- `agent/workflow/tool_handlers.py`: upload, summary generation, range summary handlers.
- `agent/workflow/hooks.py`: logging, permission checks, guard checks, TODO display.
- `agent/activity/resolution/executor.py`: direct activity resolution tool implementation.
- `agent/activity/report.py`, `comparison.py`, `training_load.py`: activity business handlers.
- `agent/route/advice.py`: route advice handler.

Single FIT analysis still has an internal hidden tool loop in `core/file_workflow.py`; it uses read-only FIT data tools from `agent/tools/fit_query.py`.
