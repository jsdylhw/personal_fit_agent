# Personal FIT Agent — 项目结构

## 顶层

```text
.
├── app/              # CLI + API 入口
├── agent/            # LLM 交互、tool-use 运行时、工具定义、活动分析
├── core/             # 配置、索引、通用统计/时间工具、Garmin/Strava 本地业务能力
├── fit/              # FIT 二进制解析
├── sinks/            # Strava API 客户端
└── tests/            # pytest 测试套件
```

## 主链路

```text
用户消息
  -> agent.main_agent.intent.route_intent()
  -> agent.main_agent.loop.agent_loop()
  -> LLM tool_use
  -> agent.main_agent.tools.TOOL_HANDLERS[name]
  -> 本地 handler
  -> tool_result
  -> 最终中文回答
```

旧的 planner / validator / selector / executor 流程已删除。当前大模型直接使用原生 tool_use，本地只保留 guard、handler 分发和上下文管理；批量副作用操作由持久化工作流负责恢复和重试。

批量本地活动不以 AgentContext 或 LLM TODO 为事实来源，而以持久化 `ActivityRun` 为准：模型只调用“创建 / 查询 / 重试”高层工具；通用 Runtime 根据任务依赖推进原子能力。

## 关键模块

```text
agent/
├── llm.py                    # Anthropic Messages API 兼容客户端
├── context.py                # AgentContext: 当前 FIT、已选活动、对话历史
├── chat_logger.py            # session + Markdown/JSONL 日志
├── tools/
│   ├── spec.py               # ToolDef + renderer + 类别常量
│   ├── agent_tools.py        # MAIN_AGENT_TOOLS: 外层业务工具清单
│   ├── fit_query.py          # 旧路径兼容导出
│   ├── fit_analysis/         # 单 FIT 分析内部只读数据工具
│   │   ├── catalog.py        # FIT_DATA_TOOLS: 子 agent 工具清单
│   │   ├── handlers.py       # tool name -> 数据工具 handler
│   │   ├── data.py           # activity_overview / summary / intervals
│   │   └── scan.py           # 区间/爬升/冲刺扫描
│   └── index_query.py        # 活动索引查询工具定义
├── main_agent/
│   ├── loop.py               # 原生 tool_use 循环与 CLI 入口编排
│   ├── tools.py              # tool name -> handler 直接分发表
│   ├── handlers.py           # 会话范围汇总等主 agent handler
│   ├── hooks.py              # 日志、guard
│   ├── guard.py              # 前置条件与参数检查
│   ├── turn_control.py       # 重试控制轮次
├── activity/
│   ├── analysis_agent.py     # ActivityAnalysisAgent: 单活动分析边界
│   ├── report.py             # show_selected_activity_report_tool
│   ├── comparison.py         # compare_selected_activities_tool
│   ├── training_load.py      # summarize_recent_training_load_tool
│   ├── selection/            # 用户条件 -> 本地活动选择 + AgentContext 更新
│   ├── operations/           # 无 AgentContext 的目录 / 分析 / Garmin / Strava / 聚合操作
│   │   └── service.py        # 操作服务，编排 core 与分析 Agent
│   ├── workflow_factory.py   # 冻结活动快照，创建 per-activity 任务图
│   ├── workflow_handlers.py  # 活动任务 kind -> operations 映射
│   ├── workflow_executor.py  # ActivityRun 的检查点执行入口
│   └── workflow_service.py   # 创建、查询、失败重试的高层接口
├── runtime/
│   ├── workflow_models.py    # 通用 Run/Task 状态机、重试与依赖恢复
│   ├── workflow_store.py     # 原子 JSON Run 存储
│   └── executor.py           # 通用依赖调度器
└── route/
    └── advice.py             # generate_route_advice_tool

agent/operations.py           # 旧 Python import 的兼容 re-export；新代码不应使用
```

```text
core/
├── config.py                 # config.yaml / athlete 配置读取
├── activity_index.py         # 本地活动索引
├── history.py                # activity_history.jsonl
├── garmin_cn.py              # Garmin 中国下载能力
├── strava_upload.py          # Strava 上传与描述更新
├── stats.py                  # 统计/格式化工具
└── time_utils.py             # 本地时间字符串规范化
```

## FIT 分析

单活动分析由 `agent/activity/analysis_agent.py` 承接。它会独立启动 `fit_analysis` 子会话，只向子 agent 暴露 `agent/tools/fit_analysis/` 的只读 FIT 数据工具，并负责写入 summary/history。

## 分层边界

- `main_agent/`：只负责对话、工具选择与展示；不串接多活动副作用。
- `activity/selection/`：把聊天工具的事实条件解析成活动，并且是唯一更新 `AgentContext` 选择状态的地方。
- `activity/operations/`：同步、单 FIT 分析、上传和聚合等无会话状态能力；CLI、API、工作流均复用它。
- `activity/workflow_*.py` + `runtime/`：冻结目标活动、保存每项任务状态、按依赖执行和重试；不依赖聊天上下文。
- `core/` 与 `sinks/`：配置、索引、Garmin 和 Strava 等外部/存储适配实现。HTTP API 会在入口处做路径和权限检查，再调用 operations 服务。

## ActivityRun

```text
本地活动目录
  -> workflow_factory（冻结活动快照）
  -> runtime.executor（依赖调度）
  -> operations.ensure_summary / operations.upload_summary
  -> operations.aggregate_summaries
  -> data/activity_runs/<workflow_id>.json
```

Run 状态为 `active | paused | completed | partial | cancelled`；任务状态为 `pending | running | completed | skipped | failed`。依赖等待不是额外 task 状态。失败重试会保留旧尝试记录，并恢复因依赖失败跳过的任务；允许失败依赖的聚合任务会重新计算，避免继续展示过期 partial 结果。
