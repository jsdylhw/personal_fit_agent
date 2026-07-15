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

旧的 planner / validator / selector / executor 流程已删除。当前大模型直接使用原生 tool_use，本地只保留权限、guard、handler 分发和上下文管理。

## 关键模块

```text
agent/
├── llm.py                    # Anthropic Messages API 兼容客户端
├── context.py                # AgentContext: 当前 FIT、已选活动、待确认动作、对话历史
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
│   ├── handlers.py           # 汇总/上传/summary 生成等主 agent handler
│   ├── hooks.py              # 日志、permission、guard、TODO 展示
│   ├── permission.py         # 副作用确认策略
│   ├── guard.py              # 前置条件与参数检查
│   ├── turn_control.py       # 确认/重试等控制轮次
│   └── todos.py              # todo_write 状态
├── activity/
│   ├── analysis_agent.py     # ActivityAnalysisAgent: 单活动分析边界
│   ├── report.py             # show_selected_activity_report_tool
│   ├── comparison.py         # compare_selected_activities_tool
│   ├── training_load.py      # summarize_recent_training_load_tool
│   └── resolution/           # 活动定位
└── route/
    └── advice.py             # generate_route_advice_tool
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
