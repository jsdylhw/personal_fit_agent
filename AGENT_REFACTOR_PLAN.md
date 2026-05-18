# Agent Refactor Plan

目标:让 agent 从"把 11 个工具都丢给大模型"升级为"程序先判断任务边界和工具范围,大模型在受控范围内完成分析和表达"。

## 当前问题

现在 `agent` 的工作方式大致是:

```text
用户输入
→ workflow_chat.py 构建消息
→ 把完整 agent_workflow_tool_catalog() 发给大模型
→ 大模型自己决定调用哪个工具
→ call_fit_analysis_tool() 执行
```

主要风险:

- 工具太多,模型容易选错。
- `analyze_fit_file` 这种批处理工具容易被误用成详细分析工具。
- `upload_to_strava` 有副作用,只靠 prompt 约束还不够。
- `current_fit_file`、最近活动、待确认上传等状态没有统一管理。
- "4 月 1 日"、"这一周"、"最近一次骑行"这类任务需要先解析活动范围,不能直接让模型猜。

## 与 debug_cli 的关系

先做哪个?

结论:先保留并完善 `debug_cli`,再做 agent 预处理架构。

原因:

- `debug_cli` 是工具调试台,可以直接验证每个 tool 的真实返回。
- agent selector/planner 改完之后,需要用 `debug_cli list-tools` 和 `debug_cli tool-call` 排查工具描述和返回结构。
- 如果没有 debug_cli,后面 prompt 或 selector 出问题时,只能看大模型日志,调试效率低。

当前优先级:

```text
1. debug_cli 保持轻量可用
2. 新增 AgentContext
3. 新增 Tool Registry / Selector
4. 改 workflow_chat.py 使用 selector 给模型缩小工具范围
5. 再做 Result Parser 和 Planner
```

也就是说,`debug_cli` 是基础设施,不是主产品入口。README 不写调试命令,调试说明放在 `DEBUG_CLI.md`。

## 目标结构

建议逐步演进到:

```text
agent/
  context.py          # AgentContext,保存 current_fit_file / pending_action 等状态
  registry.py         # ToolSpec 和工具注册中心
  selector.py         # 根据任务和上下文选择工具子集
  executor.py         # 统一执行工具
  result_parser.py    # 根据工具结果更新 context
  planner.py          # 后续再加,判断任务类型
  workflow_chat.py    # 只保留 loop 编排
  prompts.py
  tools.py            # 可逐步收敛/兼容旧入口
```

不要一次性做成重框架。先把当前痛点拆出来。

## 阶段 0:稳住 debug_cli

状态:已初步完成。

保留命令:

```text
list-tools
tool-call
inspect-fit
index-fit
rebuild-index
list-activities
resolve-activity
activities-in-range
```

用途:

```bash
python -m app.debug_cli list-tools
python -m app.debug_cli tool-call get_activity_summary --fit latest --args '{"sections":["power"]}'
python -m app.debug_cli tool-call get_time_intervals --fit latest --args '{"bucket_seconds":60}'
python -m app.debug_cli rebuild-index
python -m app.debug_cli list-activities
```

验收:

- `python -m app.debug_cli --help` 可用。
- `python -m app.debug_cli list-tools` 能看到当前暴露工具。
- `tool-call` 能直接复现 agent 工具返回。

## 阶段 1:新增 AgentContext

目标:把 workflow_chat.py 中隐含的状态集中起来。

新增:

```text
agent/context.py
```

建议结构:

```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

@dataclass
class AgentContext:
    session_id: str
    current_fit_file: Path | None = None
    current_activity_key: str | None = None
    current_summary_path: Path | None = None
    history_enabled: bool = True
    pending_action: dict[str, Any] | None = None
    last_tool_result: dict[str, Any] | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)
```

改动:

- `run_workflow_agent()` 创建 `AgentContext`。
- `_refresh_current_fit_after_tool()` 先不删,但内部改成更新 context。
- 返回结果从 context 读取。

验收:

- 现有 `agent` CLI 行为不变。
- 测试覆盖 current_fit_file 自动识别。
- 后续可以在 context 里保存 pending upload。

## 阶段 2:Tool Registry

目标:工具不再只是 list of dict,而是有类型和安全属性。

新增:

```text
agent/registry.py
```

建议结构:

```python
from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    arguments: dict[str, Any]
    category: str
    side_effect: bool = False
    requires_current_fit: bool = False
    requires_confirmation: bool = False
```

分类建议:

```text
activity_data
activity_index
workflow
strava
history
```

工具属性示例:

```text
get_activity_summary:
  category=activity_data
  side_effect=False
  requires_current_fit=True

resolve_activity:
  category=activity_index
  side_effect=False
  requires_current_fit=False

upload_to_strava:
  category=strava
  side_effect=True
  requires_confirmation=True
```

兼容:

- `fit_data_tool_catalog()` 继续返回旧格式 list[dict]。
- `agent_workflow_tool_catalog()` 可以先从 registry 转换。

验收:

- 旧测试仍通过。
- `debug_cli list-tools` 输出不变。
- 可以按 category 过滤工具。

## 阶段 3:Tool Selector

目标:不要每次给模型 11 个工具。

新增:

```text
agent/selector.py
```

先用规则,不用大模型规划。

建议规则:

```python
def select_tools(user_message: str, context: AgentContext) -> list[ToolSpec]:
    text = user_message.lower()

    if "上传" in text or "strava" in text:
        return strava tools

    if "下载" in text or "garmin" in text:
        return sync/analyze workflow tools

    if "这一周" in text or "本周" in text or "最近" in text:
        return activity_index + history tools

    if "月" in text or "日" in text:
        return activity_index tools

    if context.current_fit_file:
        return activity_data + history tools

    return activity_index tools + safe workflow tools
```

重要原则:

- 单活动分析时,不给 `upload_to_strava`。
- 已有 `current_fit_file` 时,少给 `analyze_fit_file`。
- 上传任务时,只给 Strava 相关工具和必要的活动解析工具。
- 普通聊天时,不给工具或只给空列表。

验收:

- 用户说"你好",payload 中 available_tools 为空或很少。
- 用户说"分析这次骑行"且有 `--fit`,只暴露数据工具。
- 用户说"分析这一周",暴露活动范围工具。
- 用户说"上传到 Strava",暴露上传相关工具。

## 阶段 4:Executor 独立

目标:把 `call_fit_analysis_tool()` 包装成带 context 的执行器。

新增:

```text
agent/executor.py
```

建议接口:

```python
def execute_tool(name: str, arguments: dict, context: AgentContext) -> dict:
    ...
```

职责:

- 根据 context 提供 parsed FIT。
- 根据 context 提供 history。
- 包装错误结构。
- 检查工具是否允许。
- 检查 side_effect 是否需要确认。

短期可以内部继续调用:

```python
call_fit_analysis_tool(...)
```

验收:

- workflow_chat 不直接调用 `call_fit_analysis_tool()`。
- 工具执行错误结构稳定。

## 阶段 5:Result Parser

目标:工具返回后自动更新 context。

新增:

```text
agent/result_parser.py
```

建议逻辑:

```text
resolve_activity 返回 activity.fit_path
→ context.current_fit_file = fit_path
→ context.current_activity_key = activity_key

analyze_fit_file 返回 fit_path/summary_path
→ context.current_fit_file = fit_path
→ context.current_summary_path = summary_path

upload_to_strava 返回 action_required
→ context.pending_action = {...}

upload_to_strava 返回 uploaded
→ context.pending_action = None
```

验收:

- 用户先 resolve 活动,后续数据工具能自动作用于该活动。
- 上传预览后 context 有 pending_action。

## 阶段 6:Planner / Router

目标:更明确识别任务类型。

新增:

```text
agent/planner.py
```

先做规则版:

```text
casual_chat
single_activity_analysis
activity_lookup
range_summary
garmin_sync
summary_generation
strava_upload
strava_auth
unknown
```

输出:

```python
TaskPlan(
    task_type="range_summary",
    requires_activity_resolution=True,
    allow_side_effects=False,
)
```

Selector 根据 TaskPlan 选工具。

验收:

- "分析这一周活动" -> range_summary。
- "分析 4 月 1 日骑行" -> activity_lookup / single_activity_analysis。
- "上传它到 Strava" -> strava_upload。
- "你好" -> casual_chat。

## 推荐实施顺序

最小可控路径:

```text
1. AgentContext
2. Tool Registry
3. Tool Selector
4. workflow_chat 接入 selector
5. Executor
6. Result Parser
7. Planner
```

不要先做 Planner。因为当前最大收益来自:

```text
工具缩小
状态保存
副作用保护
```

Planner 可以等 selector 工作稳定之后再加。

## 每一步都要保留的验证

```bash
python -m py_compile agent/*.py app/*.py core/*.py
pytest -q
python -m app.debug_cli list-tools
python -m app.cli agent "你好"
python -m app.cli agent "分析这次骑行" --fit latest
```

如果涉及活动索引:

```bash
python -m app.debug_cli rebuild-index
python -m app.debug_cli list-activities
python -m app.debug_cli resolve-activity --date-local YYYY-MM-DD
```

## 预期效果

改完后,agent 行为应该从:

```text
模型看到 11 个工具,自由选择
```

变成:

```text
程序识别任务
→ 程序选择工具子集
→ 模型在工具子集内调用
→ 程序解析工具结果并更新状态
→ 模型输出分析或追问
```

这样能明显减少:

- 误用批处理分析工具。
- 上传类副作用误触发。
- 对日期/范围任务的猜测。
- 多轮上下文丢失。
