# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Personal FIT Agent is a local sports data assistant: download Garmin China FIT files, generate activity reports via LLM, maintain a local activity index, and optionally upload to Strava. The LLM backend uses an Anthropic Messages API-compatible endpoint (configured in `config.yaml`).

## Commands

```bash
# Install
pip install -r requirements.txt

# Run tests (all)
python -m pytest

# Run a single test file
python -m pytest tests/test_workflow_executor.py

# Run a single test function
python -m pytest tests/test_workflow_executor.py::test_specific_name

# CLI - analyze a FIT file
python -m app.cli analyze-file "garmin_cn_fit_files/path/to/activity.fit" --force
python -m app.cli analyze-file latest

# CLI - workflow (natural language → plan → execute)
python -m app.cli workflow "分析最新的活动"
python -m app.cli workflow "比较昨天的两次活动" --json

# CLI - sync Garmin activities
python -m app.cli sync-garmin --count 5

# CLI - upload to Strava
python -m app.cli upload-strava "data/summaries/activity.summary.json"

# Debug CLI - inspect planner output without executing
python -m app.debug_cli plan-workflow "比较昨天的两次活动"

# Debug CLI - list indexed activities
python -m app.debug_cli list-activities --limit 10
```

## Architecture

### Workflow Pipeline (the main path)

```
User message → Planner (LLM picks coarse steps) → Validator → Selector (maps to handlers) → Executor (runs sequentially)
```

- **`agent/workflow/plan_schema.py`**: Defines ~17 coarse-grained workflow steps (`resolve_recent_activities`, `analyze_single_activity`, `upload_strava_activity`, etc.) that the LLM planner may choose. These are business-level steps, not tool names.
- **`agent/workflow/planner.py`**: Sends user message + catalog of available steps to LLM, gets back a `WorkflowPlan` (ordered list of steps with arguments).
- **`agent/workflow/plan_validator.py`**: Validates the plan structure.
- **`agent/workflow/step_selector.py`**: Maps each business step to a `StepExecutionSpec` (handler name, executor type, allowed tools).
- **`agent/workflow/executor.py`**: Dispatches each step to its handler. Activity resolution steps go to `agent/activity/resolution/executor.py`; analysis steps have inline handlers here.
- **`agent/workflow/runner.py`**: Orchestrates the full pipeline: plan → normalize → execute → write log.

### Single FIT Analysis (hidden tool loop)

When `analyze_single_activity` or `analyze_fit_file_tool` is called, `core/file_workflow.py:analyze_with_llm()` runs a hidden LLM tool loop (up to 8 turns). The LLM can request:

| Tool | Purpose |
|------|---------|
| `get_activity_overview` | Lightweight overview for listings |
| `get_activity_summary` | Primary structured data for full reports |
| `scan_activity_segments` | High-power intervals >= 30s, climb detection |
| `get_time_intervals` | Fixed time-window aggregates |
| `get_distance_intervals` | Fixed distance-window aggregates |
| `get_history` | Prior training history |

These tools are routed in `agent/tools/fit_analysis.py:call_fit_analysis_tool()` → implementations in `core/data_tools.py`.

### Key Modules

- **`core/`**: Config loading, activity index (CRUD for `data/activity_index.json`), Garmin download client, Strava upload workflow, FIT data query tools, stats, history management, and `file_workflow.py` (single-FIT analysis orchestration).
- **`agent/`**: LLM client (`llm.py`), prompts (`prompts.py`), runtime context (`context.py`), workflow engine (`workflow/`), activity report/comparison/training-load logic (`activity/`), tool routing (`tools/`).
- **`fit/parser.py`**: Wraps `fitdecode` to parse `.fit` binary files into structured dicts with records/laps/sessions/sports/training_metadata.
- **`sinks/strava.py`**: Strava v3 API client with OAuth (refresh token → short-lived access token), FIT upload, status polling, description updates.
- **`app/cli.py`**: Typer CLI for end users. `app/debug_cli.py` for dev inspection.

### Data Flow

1. Garmin sync downloads `.fit` → `core/garmin_cn.py`
2. `fit/parser.py:parse_fit()` extracts structured data
3. LLM tool loop (`core/file_workflow.py`) generates markdown report + Strava summary + history entry
4. Results saved to `data/summaries/*.summary.json`
5. `core/activity_index.py` maintains `data/activity_index.json` (discoverable catalog linking activity_key → fit_path/summary_path/dates/sport_type)
6. Strava upload reads summary JSON → `sinks/strava.py` uploads FIT + writes description

### Runtime State

`AgentContext` (in `agent/context.py`) is the mutable state bag shared across a single workflow execution: `current_fit_file`, `selected_activities`, `selected_activity_range`, `last_tool_result`, `messages`. It is populated by activity resolution steps and consumed by analysis/upload steps.

### Config

`config.yaml` at repo root (gitignored) with sections: `garmin_username`/`garmin_password`, `agent:` (base_url/api_key/model), `strava:` (client_id/client_secret/refresh_token), `download_count`, `output_dir`. `data/athlete.json` supplies FTP/max_HR/resting_HR/threshold_HR for analysis (copy from `data/athlete.example.json`).

### Tests

All tests in `tests/` with pytest. `conftest.py` provides fixtures: `sample_parsed_fit`, `sample_records`, `mock_llm_response`, `mock_final_llm_response`, `temp_config_file`. Tests mock the LLM client and Strava API; FIT parsing uses real `fitdecode`.
