# Personal FIT Agent

本项目是一个本地运动数据助手:下载 Garmin 中国 FIT 文件,用大模型生成活动报告,维护本地活动索引,再按需要上传到 Strava。

当前主链路是:

```text
Garmin 中国 / 本地 FIT -> 活动索引 -> Planner 生成粗粒度计划 -> 固定 Executor 执行 -> Markdown 报告 / summary JSON / Strava 上传
```

Planner 只负责选择粗粒度 workflow step,不会直接调用底层 FIT 工具。真正执行由程序侧的 validator、selector 和 executor 控制。

## 功能

- 下载 Garmin 中国最近活动为 `.fit` 文件,本地已存在时跳过。
- 分析单个 FIT,生成 Markdown 活动报告和 `data/summaries/*.summary.json`。
- 通过 `workflow` 用自然语言定位活动、分析单次活动、汇总活动范围、比较活动、总结训练负荷和上传 Strava。
- 单活动分析内部仍是隐藏 LLM tool loop:模型只能按需读取概览、结构化摘要、区间数据、冲刺/爬坡扫描和历史记录。
- workflow 日志以可读 Markdown 为主,记录 planner、归一化计划、执行步骤、选中活动和关键结果。
- Strava 上传使用本地 summary 中的 `fit_path` 和 `strava_summary`;workflow 上传步骤会直接执行上传,再把工具返回结果交给大模型组织说明。

## 安装

推荐 Python 3.12 或更高版本。

```bash
pip install -r requirements.txt
```

也可以使用 editable 模式:

```bash
pip install -e .
```

## 配置

在项目根目录创建 `config.yaml`.这个文件不会提交到 git。

```yaml
download_count: 5
output_dir: "garmin_cn_fit_files"

garmin_username: "your-garmin-cn-username"
garmin_password: "your-garmin-cn-password"
garmin_tokenstore: ".garmin_cn_tokens"
disable_curl_cffi: false

agent:
  base_url: "https://your-api-base-url"
  api_key: "your-api-key"
  model: "your-model"
  max_tokens: 4000
  temperature: 0.3
  anthropic_version: "2023-06-01"
  timeout_seconds: 300
  max_retries: 2

strava:
  client_id: "your-strava-client-id"
  client_secret: "your-strava-client-secret"
  refresh_token: "your-strava-refresh-token"
  timeout_seconds: 120
```

`agent.base_url` 需要兼容 Anthropic Messages API 的 `/v1/messages`。

运动员档案已经迁移到 `data/athlete.json`,用于补全 FIT 缺失的 FTP、最大心率、静息心率、阈值心率和区间信息。可以从示例文件复制:

```bash
cp data/athlete.example.json data/athlete.json
```

示例结构:

```json
{
  "ftp": 250,
  "max_heart_rate": 190,
  "resting_heart_rate": 50,
  "threshold_heart_rate": 170,
  "weight": 70,
  "height": 175
}
```

Strava 上传需要 `activity:write` 权限。推荐配置 `client_id`、`client_secret` 和 `refresh_token`,程序会在请求前刷新短期 access token。

检查 Strava 认证:

```bash
python -m app.cli strava-check-auth
```

生成授权 URL:

```bash
python -m app.cli strava-auth-url
```

拿浏览器回调地址里的 `code` 换 token:

```bash
python -m app.cli strava-exchange-code "PASTE_CODE_HERE"
```

把返回里的 `refresh_token` 写回 `config.yaml`。

## 常用命令

下载 Garmin 中国最近活动:

```bash
python -m app.cli sync-garmin --count 1
```

分析单个 FIT:

```bash
python -m app.cli analyze-file "garmin_cn_fit_files/path/to/activity.fit" --force
```

分析最近的本地 FIT:

```bash
python -m app.cli analyze-file latest
```

运行规划执行 workflow:

```bash
python -m app.cli workflow "分析最新的活动"
```

围绕某个 FIT 运行 workflow:

```bash
python -m app.cli workflow "看一下 100-200 秒是不是有短冲刺" --fit latest
```

输出完整 JSON 方便调试:

```bash
python -m app.cli workflow "分析所有历史活动的整体情况" --json --include-details
```

从 summary 上传到 Strava:

```bash
python -m app.cli upload-strava "data/summaries/activity.summary.json"
```

更新已有 Strava 活动描述:

```bash
python -m app.cli update-strava-description STRAVA_ACTIVITY_ID "data/summaries/activity.summary.json"
```

## Workflow 设计

外层 workflow 的步骤定义在 `agent/workflow/plan_schema.py`。大模型只允许选择这些业务步骤,例如:

- `resolve_recent_activities`
- `resolve_activity_by_date`
- `resolve_activity_range`
- `analyze_single_activity`
- `summarize_activity_range`
- `compare_activities`
- `summarize_recent_training_load`
- `sync_garmin_activities`
- `ensure_activity_summaries`
- `upload_strava_activity`

执行映射在 `agent/workflow/step_selector.py`,具体执行在 `agent/workflow/executor.py`。如果 step 没有 handler,执行层会明确报 `handler_not_implemented`,不会让大模型假装已经完成。

## 输出文件

```text
garmin_cn_fit_files/          # 下载的原始 FIT 文件
data/activity_index.json      # 本地活动索引,用于按日期/序号/范围定位活动
data/activity_history.jsonl   # 大模型生成的紧凑训练历史
data/summaries/               # 每条活动的 summary JSON
log/                          # workflow 和单活动分析日志,以 Markdown 可读日志为主
```

`data/summaries/*.summary.json` 是分析结果的主要结构化数据源,通常包含:

- `fit_path`
- `fit_summary`
- `markdown_report`
- `strava_summary`
- `history_entry`
- `activity_key`

这些文件都是本地运行产物。仓库只保留必要示例,新的运行结果默认不应提交。

## FIT 分析工具

单活动分析内部可用的数据工具在 `agent/tools/fit_analysis.py`:

| 工具 | 用途 |
|---|---|
| `get_activity_overview` | 活动高层概览,适合清单和快速判断 |
| `get_activity_summary` | 单活动完整分析的主要结构化数据 |
| `scan_activity_segments` | 扫描 30 秒以上高功率区间,并标记明显爬升 |
| `get_time_intervals` | 固定时间窗口聚合 |
| `get_distance_intervals` | 固定距离窗口聚合 |
| `get_history` | 读取历史训练记录 |

外层 planner 不直接调用这些工具;它只选择 `analyze_single_activity` 或 `summarize_activity_range` 等粗粒度步骤。

## 调试入口

`app.debug_cli` 保留给开发调试,例如查看 planner 输出:

```bash
python -m app.debug_cli plan-workflow "比较昨天的两次活动"
```

列出本地索引活动:

```bash
python -m app.debug_cli list-activities --limit 10
```

## 实验脚本

`demo/` 目录只放独立验证脚本,不接入主 workflow。

- `demo/onelap_download_demo.py`: 验证 OneLap/迈金 FIT 下载链路。
- `demo/codoon_tcx_to_strava.py`: 上传咕咚导出的 TCX 到 Strava,描述格式为 `同步自咕咚：YYYY-MM-DD HH:MM:SS`。

第三方迁移脚本和本地临时文件不要混入主流程;确认稳定后再抽成正式模块。
