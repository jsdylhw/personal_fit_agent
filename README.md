# Personal FIT Agent

本项目是一个本地 FIT 文件运动分析 Agent。当前目标是先把本地 FIT 归档、数据分析、简单绘图、结构化上下文和大模型对话流程打通，后续再接 Garmin / 迈金下载、Strava 上传和前端界面。

## 当前能力

- 导入本地 `.fit` 文件并归档到 `data/fit/`
- 解析 FIT 中的 `session`、`lap`、`record` 和部分 Garmin 训练元数据
- 保存活动索引、基础摘要和分析结果到 SQLite
- 输出 Markdown 报告到 `data/reports/`
- 提供 CLI 工具调用接口
- 提供 Anthropic Messages API 兼容的大模型对话入口
- 支持普通聊天和指定活动分析两种模式
- 活动分析会预先生成标准结构化上下文，再交给大模型做最终判断和建议

## 目录结构

```text
app/                 # CLI / API 入口
core/                # 配置、存储、导入和分析 workflow
fit/                 # FIT 解析和基础字段处理
analysis/            # 运动分析模块
agent/               # LLM 对话、工具目录、tool loop
sources/             # 数据来源，Garmin / Magene / local folder
sinks/               # 外部输出，Strava 等
docs/                # 架构和分析流程文档
data/                # 本地数据、FIT 归档、报告、SQLite
```

重要文档：

- `docs/project-architecture.md`
- `docs/activity-analysis-pipeline.md`

## 安装依赖

推荐使用 Python 3.12：

```bash
pip install -r requirements.txt
```

或者以 editable 方式安装：

```bash
pip install -e .
```

## 配置

根目录使用 `config.yaml`。

大模型部分使用 Anthropic Messages API 兼容接口：

```yaml
agent:
  base_url: "https://your-api-base-url"
  api_key: "your-api-key"
  model: "your-model"
  max_tokens: 4000
  temperature: 0.3
  anthropic_version: "2023-06-01"
```

`base_url` 可以填兼容 Anthropic `/v1/messages` 的服务地址。

## 基础命令

导入 FIT：

```bash
python -m app.cli import path/to/activity.fit
```

查看活动列表：

```bash
python -m app.cli list
```

分析最近一条活动：

```bash
python -m app.cli analyze latest
```

分析指定活动：

```bash
python -m app.cli analyze 1
```

分析结果会写入：

```text
data/state.sqlite               # activities.analysis_json
data/reports/activity_<id>.md   # Markdown 报告
data/plots/activity_<id>.png    # 简单图表，如果开启 plot
```

## 工具调用

查看 Agent 工具目录：

```bash
python -m app.cli tools-catalog
```

调用某个工具：

```bash
python -m app.cli tool-call get_activity_summary '{"activity_id":"latest"}'
python -m app.cli tool-call check_activity_data_quality '{"activity_id":"latest"}'
python -m app.cli tool-call analyze_intensity_distribution '{"activity_id":"latest"}'
python -m app.cli tool-call detect_workout_segments '{"activity_id":"latest","bucket_seconds":60}'
python -m app.cli tool-call analyze_fatigue_and_stability '{"activity_id":"latest"}'
python -m app.cli tool-call generate_training_recommendation '{"activity_id":"latest","goal":"base_endurance"}'
```

当前工具分两层：

- `activity_analysis_tools`：优先给大模型使用的专业分析任务工具
- `activity_indicators`：低层指标工具，如 `request_tss`、`request_if`、`request_power`

## 大模型对话

普通聊天：

```bash
python -m app.cli chat "你好"
```

自动模式下，普通问候不会发送活动数据。

明确普通聊天：

```bash
python -m app.cli chat "你好" --mode plain
```

分析最近一条活动：

```bash
python -m app.cli chat "分析最后一条骑行，并给下一次训练建议" --mode activity
```

分析指定活动：

```bash
python -m app.cli chat "分析这次骑行" --mode activity --activity-id 1
```

保存大模型生成的报告：

```bash
python -m app.cli chat "分析最后一条骑行" --mode activity --save-report
```

保存位置：

```text
data/state.sqlite -> analysis_reports
```

## 本地可视化界面

启动 FastAPI 服务：

```bash
uvicorn app.api:app --reload --host 127.0.0.1 --port 8000
```

然后打开：

```text
http://127.0.0.1:8000
```

当前界面支持：

- 左侧选择活动
- 查看活动摘要指标
- 查看数据质量、强度结构、分段、疲劳/稳定性指标
- 查看原始结构化分析数据
- 查看已保存的大模型报告
- 对选中活动发起大模型对话
- 勾选“保存报告”后把大模型回答写入 `analysis_reports`

## 预览发送给大模型的 Payload

不调用 API，只查看实际会发什么：

```bash
python -m app.cli chat-payload "你好"
python -m app.cli chat-payload "分析最后一条骑行，并给下一次训练建议"
```

活动分析模式会把内容拆成多个 text block：

```text
1. 用户问题和总体要求
2. 运动分析 Skill Prompt
3. 结构化运动数据
```

结构化运动数据包括：

- `activity`
- `summary`
- `data_quality`
- `intensity_distribution`
- `workout_segments`
- `fatigue_and_stability`
- `recommendation_context`
- `recent_training_history`

## 分析设计原则

后端不直接写死最终训练建议，而是返回结构化指标和上下文：

- 数据质量只说明数据是否可信、哪些分析可用
- 强度分析返回功率/心率区间分布
- 分段分析返回各时间段的类型和指标
- 疲劳分析返回前后半程对比、漂移、解耦和 caveats
- 训练建议工具返回建议上下文和候选方向

最终判断和自然语言建议由大模型基于这些结构化结果生成。

## 后续计划

- 增加活动选择和历史报告浏览的前端
- 增强历史对比和周/月训练负荷
- 接入 Garmin / 迈金自动下载
- 接入 Strava 上传和活动描述更新
- 将工具暴露为 MCP Server
