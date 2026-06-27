# Personal FIT Agent — 项目结构

## 顶层

```
.
├── app/              # CLI + API 入口
├── agent/            # LLM 交互、工作流引擎、工具定义、活动分析
├── core/             # 配置、索引、FIT 数据工具、Garmin/Strava 工作流
├── fit/              # FIT 二进制解析
├── sinks/            # Strava API 客户端
├── tests/            # pytest 测试套件
├── config.yaml       # 本地配置 (gitignored)
├── requirements.txt
└── pyproject.toml
```

## agent/ — LLM & 工作流

```
agent/
├── llm.py                   # AnthropicMessagesClient (create_message / create_messages + tools)
│                              extract_text, extract_tool_use_blocks, build_tool_result_block
├── prompts.py               # FIT analysis system prompt (模块化组装)
│                              FIT_ANALYSIS_CORE / TOOL_GUIDANCE / OUTPUT_CONTRACT
├── context.py               # AgentContext — workflow 运行时可变状态
├── chat_logger.py           # session + markdown/jsonl 日志
├── fit_paths.py             # resolve_fit_path("latest") 路径解析
│
├── tools/                   # 工具定义 — 统一在 tools/ 下
│   ├── spec.py              # ToolDef + ToolRegistry + 类别常量
│   ├── fit_query.py         # FIT_DATA_TOOLS (6 个 ToolDef) + build_tool_handlers()
│   ├── index_query.py       # INDEX_TOOLS (3 个 ToolDef)
│   ├── planner_tools.py     # PLANNER_TOOLS (18 个, 原生 API 格式)
│   └── workflow_ops.py      # 业务操作函数 (sync/analyze/upload, 非 LLM 工具)
│
├── workflow/                # Planner → Executor 链路
│   ├── plan_schema.py       # WorkflowStepSpec — 18 个粗粒度步骤定义
│   ├── planner.py           # plan_initial_workflow() — LLM 选步骤
│   ├── plan_validator.py    # 校验依赖/副作用
│   ├── step_selector.py     # 步骤 → handler 映射
│   ├── executor.py          # 按步骤名分发执行
│   └── runner.py            # 编排: plan → normalize → execute → log
│
├── activity/                # 活动分析 handler
│   ├── report.py            # show_selected_activity_report
│   ├── comparison.py        # compare_selected_activities
│   ├── training_load.py     # summarize_recent_training_load
│   └── resolution/          # 活动定位
│       ├── executor.py      # execute_activity_resolution_step
│       ├── context_update.py
│       └── date_parser.py
│
└── route/                   # 路线建议
    └── advice.py            # generate_route_advice — LLM 生成结构化建议
```

## 数据流

```
用户消息
  → Planner (LLM 选 step) → Validator → Selector → Executor (for loop)
                                                            ├─ activity_resolution → core/activity_index
                                                            ├─ analyze → core/file_workflow (tool loop)
                                                            ├─ upload → core/strava_workflow → sinks/strava
                                                            └─ route → agent/route/advice (LLM)
```

## 三层工具

| 层 | 定义 | 数量 | 调用者 | 协议 |
|---|---|---|---|---|
| Planner | `planner_tools.py` | 18 | Planner LLM | 原生 `tools` dict |
| Index | `index_query.py` | 3 | executor | `ToolDef` |
| Data | `fit_query.py` | 6 | tool loop LLM | `ToolDef` + handler 工厂 |

## 核心链路

**Workflow (主链路):**
```
Planner LLM → WorkflowPlan → Validator → StepSelector → Executor → log
```

**FIT 分析 (tool loop):**
```
analyze_with_llm()
  → AnthropicMessagesClient.create_messages(tools=FIT_DATA_TOOLS)
  → for block in response.content:
      if block["type"] == "tool_use":
          handler = handlers[block["name"]]
          handler(**block["input"])
  → 最终 JSON: markdown_report + strava_summary + history_entry
```

**路线建议:**
```
Planner 选 generate_route_advice
  → AgentContext (location/duration/goal + 可选 training_load)
  → LLM 生成 {answer, strategy, constraints, needs_clarification}
```

## Strava

`sinks/strava.py` — OAuth (refresh token → access token), FIT 上传, 状态轮询, 描述更新。

## 配置

`config.yaml` (gitignored):
- `garmin_username` / `garmin_password`
- `agent:` — Anthropic Messages API 兼容 endpoint
- `strava:` — client_id / client_secret / refresh_token
- `download_count`, `output_dir`

`data/athlete.json` — FTP / max_HR / resting_HR / threshold_HR。
