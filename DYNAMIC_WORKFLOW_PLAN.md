# Dynamic Workflow Plan

目标:把当前 `workflow_agent` 从"模型直接看工具并调用"演进为"先动态规划业务步骤,再由程序校验,选择工具并执行"。

这份文档描述后续架构方向。当前阶段只先定义粗粒度 planner 语言,不急着让 planner 直接驱动执行。

## 总体思路

后续工作流应该变成:

```text
用户输入
→ Planner 选择粗粒度业务步骤
→ Validator 校验计划合法性和风险
→ Selector 把业务步骤映射到底层工具范围
→ Executor 执行工具或子流程
→ Result Parser 更新 AgentContext
→ Responder 汇总最终回答
```

核心原则:

- Planner 只做计划,不执行工具。
- Planner 选择的是业务步骤,不是底层工具名。
- 任何副作用动作都必须经过程序校验。
- 上传类动作必须有明确确认。
- 单活动分析,周期总结,训练建议,路线建议都应该是可组合步骤。

## 当前状态

已经具备:

```text
agent/context.py       # AgentContext,集中保存 workflow 状态
agent/plan_schema.py   # 粗粒度工作流步骤定义
agent/planner.py       # 构建 planner payload,调用 LLM 生成初始 WorkflowPlan
agent/workflow_chat.py # 当前仍是工具 loop 主入口
agent/tools.py         # 当前底层工具 catalog 和执行路由
app/debug_cli.py       # 工具调试入口,包含 plan-workflow 初始规划调试命令
```

当前还没有做:

```text
Plan Validator
Step Selector
Executor
Result Parser
Responder
```

## 粗粒度步骤层

Planner 应该从业务步骤中选择,例如:

```text
casual_chat
ask_user_clarification

resolve_current_activity
resolve_activity_by_date
resolve_activity_range
resolve_recent_activities

analyze_single_activity
summarize_activity_range
compare_with_history
generate_training_advice
generate_route_advice

sync_garmin_activities
analyze_new_fit_files
generate_summary_file

prepare_strava_upload
confirm_strava_upload

final_response
```

这些步骤比工具更粗:

```text
analyze_single_activity
→ get_activity_overview
→ get_activity_summary
→ get_time_intervals
→ get_distance_intervals
→ get_history
```

```text
sync_garmin_activities + analyze_new_fit_files
→ sync_garmin_activities
→ analyze_fit_file for each new FIT
```

这样可以让 LLM 做意图理解,但不直接控制工具和副作用。

## 动态规划输出

Planner 后续应该输出固定 JSON:

```json
{
  "task_type": "garmin_sync_and_analysis",
  "steps": [
    {
      "name": "sync_garmin_activities",
      "reason": "用户要求同步最近两条 Garmin 活动",
      "arguments": {"count": 2}
    },
    {
      "name": "analyze_new_fit_files",
      "reason": "用户要求同步后分析新下载的 FIT 文件",
      "arguments": {}
    },
    {
      "name": "final_response",
      "reason": "向用户汇总同步和分析结果",
      "arguments": {}
    }
  ],
  "activity_scope": {"type": "newly_synced"},
  "allow_side_effects": true,
  "requires_confirmation": false,
  "needs_user_clarification": false,
  "clarifying_question": null,
  "final_output": ["synced_files", "analysis_summary", "log_paths"]
}
```

要求:

- `steps[].name` 必须来自 `available_steps`。
- `arguments` 只能是步骤级参数,不能写底层工具参数细节。
- 如果信息不足,使用 `ask_user_clarification`。
- 如果需要上传,先输出 `prepare_strava_upload`,不能直接 `confirm_strava_upload`。

## Validator

新增:

```text
agent/validator.py
```

职责:

- 校验所有 step 名称存在。
- 校验步骤顺序是否合理。
- 校验副作用步骤是否被允许。
- 校验上传确认逻辑。
- 校验 `requires_current_fit` 是否满足。
- 校验日期范围,count 等参数边界。

示例规则:

```text
confirm_strava_upload
→ 必须已有 pending_action
→ 必须用户明确确认

analyze_single_activity
→ 必须已有 current_fit_file
→ 或者前面存在 resolve_current_activity / resolve_activity_by_date

analyze_new_fit_files
→ 前面必须有 sync_garmin_activities
→ 或 context 里已有 last_synced_fit_files
```

Validator 输出:

```json
{
  "valid": true,
  "errors": [],
  "warnings": []
}
```

## Selector

新增:

```text
agent/selector.py
```

职责:

- 把粗粒度步骤映射为允许的底层工具子集。
- 不执行工具。
- 不把无关工具暴露给执行 LLM。

映射示例:

```text
resolve_activity_range
→ list_activities
→ get_activities_in_range
```

```text
analyze_single_activity
→ get_activity_overview
→ get_activity_summary
→ get_time_intervals
→ get_distance_intervals
→ get_history
```

```text
prepare_strava_upload
→ resolve_activity
→ upload_to_strava with confirmed=false
```

```text
confirm_strava_upload
→ upload_to_strava with confirmed=true
```

Selector 依赖后续 `Tool Registry` 中的工具属性:

```text
category
side_effect
requires_current_fit
requires_confirmation
```

## Executor

新增:

```text
agent/executor.py
```

职责:

- 执行 selector 允许的工具。
- 包装统一错误结构。
- 将 `AgentContext` 中的 parsed/history 传给数据工具。
- 对副作用工具做最后一道保护。
- 支持一个 step 内执行多个底层工具。

短期可以继续复用:

```text
call_fit_analysis_tool()
```

长期可以让 `workflow_chat.py` 不再直接调用 `call_fit_analysis_tool()`。

## Result Parser

新增:

```text
agent/result_parser.py
```

职责:

- 根据工具结果更新 `AgentContext`。
- 把当前 `_refresh_current_fit_after_tool()` 中的逻辑迁移出来。

关键状态:

```text
resolve_activity 返回 activity.fit_path
→ context.current_fit_file
→ context.current_activity_key
→ context.current_summary_path

sync_garmin_activities 返回 downloaded files
→ context.last_synced_fit_files

analyze_fit_file 返回 fit_path/summary_path
→ context.current_fit_file
→ context.current_summary_path

upload_to_strava 返回 action_required
→ context.pending_action

upload_to_strava uploaded
→ context.pending_action = None
```

## Responder

新增:

```text
agent/responder.py
```

职责:

- 根据 user_message, plan, tool_results, context 组织最终中文回答。
- 不再执行工具。
- 让最终回答和执行过程分离。

例如:

```text
同步完成 2 条 Garmin 活动,并分别完成分析:

1. 2026-05-18 21:10 青浦区公路骑行
   - summary_path: ...
   - log_path: ...

2. 2026-05-18 08:36 青浦区公路骑行
   - summary_path: ...
   - log_path: ...
```

## 训练建议工作流

用户请求:

```text
最近有点累,明天怎么骑?
```

期望计划:

```text
resolve_recent_activities
summarize_activity_range
compare_with_history
generate_training_advice
final_response
```

执行逻辑:

```text
读取最近 7-28 天活动
→ 总结训练量,强度,恢复分布
→ 判断是否需要降低强度
→ 生成下一次训练建议和本周安排
```

输出结构:

```text
当前状态判断
关键依据
明天怎么骑
本周安排
恢复建议
不确定性
```

## 骑行路线建议工作流

用户请求:

```text
明天想骑 50 公里,路线怎么安排?
```

期望计划:

```text
resolve_recent_activities
compare_with_history
generate_route_advice
final_response
```

短期输出路线约束:

```text
距离范围
爬升范围
强度目标
路线类型
补给建议
风险提醒
```

长期可以接入路线工具:

```text
route_candidates
route_elevation_profile
route_export_gpx
```

不要让 LLM 凭空编具体道路和 GPX。

## 推荐实施顺序

建议按小步推进:

```text
1. 完善 plan_schema.py 的粗粒度步骤和测试
2. 新增 validator.py,只校验计划,不执行
3. 新增 LLM planner,只输出 WorkflowPlan JSON
4. 新增 Tool Registry,给底层工具补元信息
5. 新增 selector.py,完成 step -> tools 映射
6. 新增 executor.py,从 workflow_chat.py 抽出工具执行
7. 新增 result_parser.py,统一更新 AgentContext
8. 新增 responder.py,把最终表达从执行 loop 中拆出
9. workflow_chat.py 接入动态规划执行链路
```

每一步都要保持旧入口可用:

```bash
python -m app.debug_cli list-tools
python -m app.cli agent "你好"
python -m app.cli agent "分析这次骑行" --fit latest
pytest -q
```

## 阶段验收

### 阶段 A:规划语言

- `available_workflow_steps()` 返回稳定粗粒度步骤。
- 所有 step 名称唯一。
- 副作用和确认属性正确。
- planner payload 不暴露底层工具名。

### 阶段 B:只规划不执行

- 用户输入可以得到 `WorkflowPlan`。
- `python -m app.debug_cli plan-workflow "..."` 可以调试初始计划。
- Planner 输出非法 step 时能被 validator 拒绝。
- 信息不足时 planner 输出 `ask_user_clarification`。

### 阶段 C:选择工具

- 单活动分析只暴露数据工具。
- 周期总结只暴露活动索引和历史工具。
- 训练建议不暴露上传工具。
- 上传流程只暴露 Strava 预览/确认相关工具。

### 阶段 D:动态执行

- `workflow_chat.py` 不再直接把 11 个工具都给模型。
- `analyze_fit_file` 只在 summary generation 或 sync 后分析中出现。
- `upload_to_strava confirmed=true` 只能在用户确认后出现。
- 工具结果能自动更新 context。

## 最终目标

最终系统应该从:

```text
模型看到所有工具,自由选择
```

演进为:

```text
模型规划业务步骤
→ 程序校验计划
→ 程序选择工具范围
→ 模型或程序在受控范围内执行
→ 程序解析结果并更新状态
→ 模型组织最终回答
```

这样可以继续保留 LLM 的理解和表达能力,同时降低误用工具,误触发副作用,日期范围猜测和多轮状态丢失的风险。
