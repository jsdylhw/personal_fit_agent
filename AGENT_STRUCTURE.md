# Personal FIT Agent — 项目结构

## 顶层

```text
.
├── app/              # CLI + API 入口
├── agent/            # LLM 交互、tool-use 运行时、工具定义、活动分析
├── core/             # 配置、索引、FIT 数据工具、Garmin/Strava 工作流
├── fit/              # FIT 二进制解析
├── sinks/            # Strava API 客户端
└── tests/            # pytest 测试套件
```

## 主链路

```text
用户消息
  -> agent.workflow.intent.route_intent()
  -> agent.workflow.tool_loop.agent_loop()
  -> LLM tool_use
  -> agent.workflow.tool_runtime.run_tool_step()
  -> 本地 handler
  -> tool_result
  -> 最终中文回答
```

旧的 planner / validator / selector / executor 流程已删除。当前大模型直接使用原生 tool_use，本地只保留权限、guard、handler 分发和上下文管理。

## 关键模块

```text
agent/
├── llm.py                    # Anthropic Messages API 兼容客户端
├── context.py                # AgentContext: 当前 FIT、已选活动、待确认动作、对话历史
├── chat_logger.py            # session + Markdown/JSONL 日志
├── tools/
│   ├── spec.py               # ToolDef + renderer + 类别常量
│   ├── agent_tools.py        # AGENT_TOOLS: 外层 tool-use 工具清单
│   ├── fit_query.py          # 单 FIT 分析内部只读数据工具
│   └── index_query.py        # 活动索引查询工具定义
├── workflow/
│   ├── tool_loop.py          # 原生 tool_use 循环与 CLI 入口编排
│   ├── tool_runtime.py       # tool name -> direct handler
│   ├── tool_handlers.py      # 汇总/上传/summary 生成等业务 handler
│   ├── hooks.py              # 日志、permission、guard、TODO 展示
│   ├── permission.py         # 副作用确认策略
│   ├── tool_guard.py         # 前置条件与参数检查
│   ├── turn_control.py       # 确认/重试等控制轮次
│   └── todos.py              # todo_write 状态
├── activity/
│   ├── report.py             # show_selected_activity_report_tool
│   ├── comparison.py         # compare_selected_activities_tool
│   ├── training_load.py      # summarize_recent_training_load_tool
│   └── resolution/           # 活动定位
└── route/
    └── advice.py             # generate_route_advice_tool
```

## FIT 分析

单活动分析仍由 `core/file_workflow.py` 内部 tool loop 完成。外层只调用 `analyze_single_activity` / `generate_summary_file` 等业务工具，内部再使用 `agent/tools/fit_query.py` 的只读 FIT 数据工具。
