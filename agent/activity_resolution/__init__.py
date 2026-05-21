"""activity_resolution —— 活动解析与定位。

将 WorkflowPlanStep 中的活动范围参数解析为本地活动记录，
并更新 AgentContext。

子模块:
- executor: 步骤分发与执行入口
- date_parser: 日期 / 范围 / 排序参数解析（纯函数）
- context_update: AgentContext 副作用更新
"""

from agent.activity_resolution.executor import ACTIVITY_RESOLUTION_STEPS, execute_activity_resolution_step

__all__ = ["ACTIVITY_RESOLUTION_STEPS", "execute_activity_resolution_step"]
