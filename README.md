# Personal FIT Agent

这是一个本地 Garmin 中国 FIT 下载和大模型优先的运动分析工具.

当前主流程:

```text
Garmin 中国 -> 下载 FIT 文件 -> 单个 FIT 分析 / 对话分析 -> 生成报告 / 总结 / 历史记录 -> 上传 FIT 和总结到 Strava
```

现在使用文件式 workflow,不依赖本地 SQLite 数据库.程序会保留原始 FIT 文件,Markdown 报告,每条活动的 JSON summary,完整对话日志,以及一份 JSONL 训练历史.

## 功能

- 从 Garmin 中国下载最近的活动为 `.fit` 文件.
- 如果本地已经存在对应 FIT,则跳过重复下载.
- 支持分析单个 FIT 文件.
- 支持对 FIT 文件进行单轮直接提问,或进入多轮人为引导分析.
- 分析走隐藏的大模型 tool loop:
  - 第一次只发送简短 FIT 摘要;
  - 模型按需请求活动概览,结构化摘要,时间/距离区间或历史记录;
- 完整隐藏交互会保存到 `log/`,同时生成同名 `.md` 可读日志.
- 每次分析生成:
  - 完整 Markdown 活动报告;
  - 约 200 个中文字符,适合 Strava 的活动总结;口吻会加权随机选择,包含正常训练日志,专业教练,轻松骑友,简洁复盘,轻微自嘲和猫娘风格,其中猫娘概率会稍高;
  - 用于后续对比的紧凑 `history_entry`.
- 支持上传原始 FIT 到 Strava,并把生成的 Strava 总结作为活动描述.

## 安装

推荐 Python 3.12.

```bash
pip install -r requirements.txt
```

也可以使用 editable 模式:

```bash
pip install -e .
```

## 配置

在项目根目录创建 `config.yaml`.这个文件已经被 git 忽略.

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

athlete:
  ftp: 250
  weight_kg: 70
  max_heart_rate: 190
  resting_heart_rate: 50
  threshold_heart_rate: 170
  goals: "提升有氧耐力和 FTP"
  notes: "可写伤病,训练偏好,近期目标等"

strava:
  client_id: "your-strava-client-id"
  client_secret: "your-strava-client-secret"
  refresh_token: "your-strava-refresh-token"
  timeout_seconds: 120
```

`agent.base_url` 需要兼容 Anthropic Messages API 的 `/v1/messages`.

Strava 上传需要 token 具备 `activity:write` 权限.推荐配置 `client_id`,`client_secret` 和 `refresh_token`,程序会在请求前自动刷新短期 access token.

检查 Strava 认证是否可用:

```bash
python -m app.cli strava-check-auth
```

如果上传时报 `activity:write_permission missing`,说明当前 Strava token 没有写入权限,需要重新授权:

```bash
python -m app.cli strava-auth-url
```

打开命令输出的 URL,授权后浏览器会跳转到一个带 `code` 参数的地址.复制这个 `code`,然后执行:

```bash
python -m app.cli strava-exchange-code "PASTE_CODE_HERE"
```

把返回结果里的 `refresh_token` 写回 `config.yaml` 的 `strava.refresh_token`.

## 下载 FIT

下载 Garmin 中国最近活动:

```bash
python -m app.cli sync-garmin
```

临时覆盖下载数量:

```bash
python -m app.cli sync-garmin --count 1
```

本地已有的 FIT 文件会自动跳过.

## 分析 FIT

分析单个 FIT 文件:

```bash
python -m app.cli analyze-file "garmin_cn_fit_files/path/to/activity.fit" --history --force
```

`--history` 表示可以参考已经生成的紧凑历史.`--force` 表示即使 summary 已经存在,也重新请求大模型分析.

## Agent 工作流模式

如果希望让大模型自己决定调用下载 / 分析 / 上传工具,可以使用完整工具集 agent:

```bash
python -m app.cli agent "下载最近 3 条 Garmin 活动,分析最新一条,先不要上传 Strava"
```

如果要让 agent 围绕某个本地 FIT 文件继续查询细节,传入 `--fit`:

```bash
python -m app.cli agent "看一下 100-200 秒是不是有短冲刺,然后给训练建议" --fit latest
```

`agent` 模式会暴露 11 个工具:5 个单活动只读数据工具 + 3 个活动发现工具 + `sync_garmin_activities`,`analyze_fit_file`,`upload_to_strava`.上传 Strava 仍然需要二次确认,第一次只返回预览.

## 输出文件

```text
garmin_cn_fit_files/          # 下载的原始 FIT 文件
data/summaries/               # 每条活动的 JSON summary(包含 markdown_report + strava_summary)
data/activity_index.json      # 本地活动索引,用于按日期/范围发现活动
data/activity_history.jsonl   # 大模型生成的紧凑训练历史
log/                          # 完整大模型请求 / 响应 / tool loop 日志,含 jsonl 和 md
```

`data/summaries/*.summary.json` 是分析结果的唯一权威数据源,包含:

- FIT 摘要;
- 完整 Markdown 报告(`markdown_report`);
- Strava 总结(`strava_summary`);
- 本次随机选择的 Strava 总结口吻;
- 大模型生成的历史条目;
- 原始 FIT 文件路径;
- 工具循环日志路径.

`log/*.jsonl` + `log/*.md` 保存完整 LLM 交互记录,每次分析生成一对同名文件.

## 上传到 Strava

分析完成后,可以上传原始 FIT,并把生成的 Strava 总结作为活动描述:

```bash
python -m app.cli upload-strava "data/summaries/activity.summary.json"
```

自定义 Strava 活动标题:

```bash
python -m app.cli upload-strava "data/summaries/activity.summary.json" --title "Morning Ride"
```

如果活动已经在 Strava 上,只想更新描述:

```bash
python -m app.cli update-strava-description STRAVA_ACTIVITY_ID "data/summaries/activity.summary.json"
```

`upload-strava` 会从 summary JSON 里读取 `fit_path` 和 `strava_summary`.默认会等待 Strava 处理上传结果;如果只想拿到上传请求返回,可以加 `--no-wait`.

如果上传看起来"卡住",通常是等待 Strava 处理上传状态.可以先用:

```bash
python -m app.cli upload-strava "data/summaries/activity.summary.json" --no-wait
```

本地 Web 界面的"上传 Strava"按钮默认不等待处理完成,只确认上传请求已提交.

## 分析工具

FIT 分析 workflow(`analyze-file`)通过隐藏的 LLM tool loop 工作:模型按需调用以下 5 个数据工具获取结构化信息,然后自行完成分析推理和报告写作.

| 工具 | 用途 |
|---|---|
| `get_activity_overview` | 高层活动概览(运动类型,时长,距离,基础指标,数据可用性) |
| `get_activity_summary` | 按模块获取结构化摘要(功率,心率,踏频,海拔,训练负荷等) |
| `get_time_intervals` | 固定时间窗口的聚合平均值,支持按时间范围过滤 |
| `get_distance_intervals` | 固定距离窗口的聚合平均值,支持按距离范围过滤 |
| `get_history` | 获取历史训练记录用于纵向对比 |

正常 CLI 分析时,这些工具调用不会展示给用户,但完整记录会保存在 `log/`.其中 `.jsonl` 适合程序读取,`.md` 适合直接查看.

完整 `agent` 模式在上面 5 个数据工具之外,还会暴露:

| 工具 | 用途 |
|---|---|
| `list_activities` | 列出 `data/activity_index.json` 中的本地活动 |
| `resolve_activity` | 按日期、文件名、activity_key、运动类型解析单条活动 |
| `get_activities_in_range` | 获取一段日期范围内的活动,用于周/月总结 |
| `sync_garmin_activities` | 下载 Garmin 中国最近活动,自动跳过已有 FIT |
| `analyze_fit_file` | 批处理生成/刷新 summary JSON 和 Strava 总结 |
| `upload_to_strava` | 上传 FIT 到 Strava,并写入生成的 Strava 总结;需要二次确认 |

## 对话式分析 FIT 文件

`fit-ask`(单轮直接发送):程序会预计算活动 overview,summary 和 60s/1km 区间聚合数据,作为静态背景上下文发送给模型,模型基于这些数据直接回答.

```bash
python -m app.cli fit-ask "garmin_cn_fit_files/path/to/activity.fit" "分析这次骑行,并给下一次训练建议"
```

`fit-chat`(多轮人为引导分析):程序同样预计算数据视图,然后进入终端对话.你可以补充体感,目标,睡眠,补给,路况和下一次可训练时间,最后输入 `/final` 生成总结.

最终总结写入 `data/summaries/*.summary.json` 的 `guided_analysis` 字段,不覆盖自动分析生成的 `markdown_report` 和 `strava_summary`.

```bash
python -m app.cli fit-chat "garmin_cn_fit_files/path/to/activity.fit"
```

也可以用最新的本地 FIT 文件启动:

```bash
python -m app.cli fit-chat latest
```

如果只想对话,不写回 summary:

```bash
python -m app.cli fit-chat latest --no-update-summary
```
