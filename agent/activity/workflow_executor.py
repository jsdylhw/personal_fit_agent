"""ActivityRun 的最小执行入口：保存检查点并调用通用 Runtime。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.activity.workflow_handlers import activity_task_handlers
from agent.runtime.executor import execute_ready_tasks
from agent.runtime.workflow_store import save_workflow


def execute_activity_run(
    run: dict[str, Any],
    *,
    directory: str | Path,
) -> dict[str, Any]:
    """执行已注册的活动任务，每次状态变更都原子保存同一 Run。"""
    return execute_ready_tasks(
        run,
        handlers=activity_task_handlers(),
        checkpoint=lambda current: save_workflow(current, directory=directory),
    )
