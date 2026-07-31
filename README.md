# Personal FIT Agent

本项目是一个本地运动数据助手:下载 Garmin 中国 FIT 文件,用大模型生成活动报告,维护本地活动索引,再按需要上传到 Strava。

当前主链路是:

```text
Garmin 中国 / 本地 FIT -> 活动索引 -> 原生 tool-use loop -> 本地工具函数 -> Markdown 报告 / summary JSON / Strava 上传
```

当前主路径是 `python -m app.cli chat`:大模型直接通过 tool_use 选择工具,运行时按工具名调用本地 handler；批量副作用操作统一创建持久化工作流，guard 只校验参数和数据前置条件。

## 功能

- 下载 Garmin 中国最近活动为 `.fit` 文件,本地已存在时跳过。
- 分析单个 FIT,生成 Markdown 活动报告和 `data/summaries/*.summary.json`。
- 通过 `chat` 用自然语言定位活动、分析单次活动、汇总活动范围、比较活动、总结训练负荷，以及创建可恢复的 Strava 上传工作流。
- 对本地已有的多条活动，可创建持久化工作流：逐条确保 summary、按需上传 Strava，并在所有单条结果后生成汇总；进程中断后可从同一 Run 继续。
- 单活动分析由 ActivityAnalysisAgent 子会话完成:模型只能按需读取概览、结构化摘要、区间数据、冲刺/爬坡扫描和历史记录。
- 分析会按 `sport_type` 区分骑行和跑步：跑步报告使用配速、公里分段、心率、步频和存在的跑步动态数据；没有跑步动态传感器时会明确标为数据缺失。
- Main Agent 日志以可读 Markdown 为主,记录 intent、工具调用步骤、选中活动和关键结果。
- Strava 上传使用本地 summary 中的 `fit_path` 和 `strava_summary`；批量上传由 ActivityRun 的原子任务执行并持久化结果。

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

# Web API 默认仅允许本机访问；如需经局域网或反向代理访问，必须设置随机 token。
web_api_token: "replace-with-a-long-random-token"
```

配置 `web_api_token` 后，内置 Web UI 首次打开会显示 401；在页面上方的 **API Token** 输入框填写同一 Token 后即可使用。Token 只保存在当前浏览器会话的 `sessionStorage`，不会写入仓库或配置文件。通过局域网/反向代理访问时应启用 HTTPS。

`agent.base_url` 需要兼容 Anthropic Messages API 的 `/v1/messages`。

运动员档案位于 `data/athlete.json`，按运动专项保存阈值。旧平铺的 `ftp` 仍兼容为骑行 FTP，但不会用于跑步。可以从示例文件复制:

```bash
cp data/athlete.example.json data/athlete.json
```

示例结构:

```json
{
  "shared": {
    "max_heart_rate": 190,
    "resting_heart_rate": 50,
    "weight": 70,
    "height": 175
  },
  "cycling": { "ftp_w": 250, "threshold_heart_rate": 170 },
  "running": {
    "threshold_heart_rate": 175,
    "threshold_power_w": null,
    "threshold_pace_s_per_km": 285,
    "critical_speed_mps": null
  }
}
```

跑步功率阈值只有在 `running.threshold_power_w` 明确配置后才会用于跑步功率强度比；FIT 中可能遗留的骑行 FTP 不会用于跑步 IF/TSS 或功率区间。
`running.threshold_pace_s_per_km` 的单位是秒/公里，例如 `285` 表示 4'45"/km；`critical_speed_mps` 可选，用于保存跑步专属临界速度。

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

授权结果会保存到本地 `.strava_tokens.json`（已被 git 忽略，权限为仅当前用户可读）；无需手动改写 `config.yaml`。

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

运行 Main Agent 对话:

```bash
python -m app.cli chat "分析最新的活动"
```

围绕某个 FIT 运行 Main Agent:

```bash
python -m app.cli chat "看一下 100-200 秒是不是有短冲刺" --fit latest
```

从 summary 上传到 Strava:

```bash
python -m app.cli upload-strava "data/summaries/activity.summary.json"
```

更新已有 Strava 活动描述:

```bash
python -m app.cli update-strava-description STRAVA_ACTIVITY_ID "data/summaries/activity.summary.json"
```

## Main Agent 设计

外层 Main Agent 使用 Anthropic/兼容 Messages API 的原生 tool_use。工具定义在 `agent/tools/agent_tools.py`,循环入口在 `agent/main_agent/loop.py`,工具分发表在 `agent/main_agent/tools.py`,业务 handler 在 `agent/main_agent/handlers.py` 和各 activity/route 模块中。主 Agent 只暴露粗粒度业务工具:

- `find_activity`
- `analyze_activity`
- `query_activity_detail`
- `summarize_activities`
- `compare_activities`
- `summarize_recent_training_load`
- `generate_training_advice`
- `generate_route_advice`
- `sync_and_run_activity_workflow`
- `run_activity_workflow`
- `get_activity_workflow`
- `retry_activity_workflow`

运行时逻辑很薄:循环读取 tool_use,检查 guard,找到同名 handler 执行,把 tool_result 返回给大模型。已删除旧的 planner / validator / selector / executor 层，也不再暴露依赖会话临时状态的“下载后再分析/上传”工具链。

单活动完整报告使用 `analyze_activity`：已有 summary 时只读取报告，缺失时才调用 FIT 子 Agent 生成。只有“100–200 秒有没有冲刺”“第几公里掉速”等必须查询原始 FIT 区间的单条问题才使用 `query_activity_detail`；它不会覆盖原有 summary。多条活动一律使用 `summarize_activities`，优先读取每条已有 summary，仅补齐缺失报告。

## 批量活动工作流

当请求是“本地最近五条分析后上传”或“汇总本地活动”时，Main Agent 使用 `run_activity_workflow`。Run 会在创建时冻结目标活动快照，并持久化每项任务：

```text
ActivityRun
  activity A -> ensure_summary -> upload_strava
  activity B -> ensure_summary -> upload_strava
  ...
  all ensure_summary ----------> aggregate_report
```

- summary、上传与汇总任务会按依赖顺序直接执行；任务状态和每次尝试都保存到 Run，失败后可精确重试。
- 已有的 summary 和已记录的 Strava activity ID 会跳过对应操作。
- 失败任务可通过 `retry_activity_workflow` 重试；其依赖失败而跳过的下游任务、以及旧的 partial 汇总会被重新排队，历史尝试保存在任务快照中。
- 若请求是“同步 Garmin 最近五条，再分析并上传”，使用 `sync_and_run_activity_workflow`。它仅将本次已成功索引的活动写入同一个 Run；同步结果（请求数量、下载/跳过/失败数、活动 key、失败项）保存到 `request.sync`，不会因后续对话重新选择“最近五条”而漂移。
- Run 文件位于 `data/activity_runs/<workflow_id>.json`，是业务事实和恢复依据；对话不再维护独立 TODO 状态。

在 chat 中可直接这样说：

```text
分析本地最近五个活动并生成汇总
分析最近三个上午的活动
把本地最近五个已分析活动上传到 Strava
重试工作流 <workflow_id> 中失败的上传
```

## 输出文件

```text
garmin_cn_fit_files/          # 下载的原始 FIT 文件
data/activity_index.json      # 本地活动索引,用于按日期/序号/范围定位活动
data/activity_history.jsonl   # 大模型生成的紧凑训练历史
data/summaries/               # 每条活动的 summary JSON
data/activity_runs/            # 批量 ActivityRun 的持久化任务快照
log/                          # Main Agent 和单活动分析日志,以 Markdown 可读日志为主
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

单活动分析内部可用的数据工具在 `agent/tools/fit_analysis/`。`agent/tools/fit_query.py` 仅保留旧路径兼容导出:

| 工具 | 用途 |
|---|---|
| `get_activity_overview` | 活动高层概览,适合清单和快速判断 |
| `get_activity_summary` | 单活动完整分析的主要结构化数据 |
| `scan_activity_segments` | 扫描 30 秒以上高功率区间,并标记明显爬升 |
| `get_time_intervals` | 固定时间窗口聚合 |
| `get_distance_intervals` | 固定距离窗口聚合 |
| `get_history` | 读取历史训练记录 |

外层 tool-use loop 不直接暴露这些 FIT 数据工具;它只调用 `analyze_activity` 或 `summarize_activities` 等业务工具,单活动分析内部再按需读取 FIT 数据。

## 调试入口

`app.debug_cli` 保留给开发调试,例如查看 FIT 工具返回或活动索引。

列出本地索引活动:

```bash
python -m app.debug_cli list-activities --limit 10
```

## 实验脚本

`demo/` 目录只放独立验证脚本,不接入 Main Agent 主路径。

- `demo/onelap_download_demo.py`: 验证 OneLap/迈金 FIT 下载链路。
- `demo/codoon_tcx_to_strava.py`: 上传咕咚导出的 TCX 到 Strava,描述格式为 `同步自咕咚：YYYY-MM-DD HH:MM:SS`。

第三方迁移脚本和本地临时文件不要混入主流程;确认稳定后再抽成正式模块。
