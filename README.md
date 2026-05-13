# Personal FIT Agent

这是一个本地 Garmin 中国 FIT 下载和大模型优先的运动分析工具。

当前主流程：

```text
Garmin 中国 -> 下载 FIT 文件 -> 按时间顺序分析 FIT -> 生成报告 / 总结 / 历史记录 -> 上传 FIT 和总结到 Strava
```

现在推荐使用文件式 workflow，不依赖本地数据库。程序会保留原始 FIT 文件、Markdown 报告、每条活动的 JSON summary、完整对话日志，以及一份 JSONL 训练历史。旧的 SQLite 命令还保留在代码里，但不是当前推荐路径。

## 功能

- 从 Garmin 中国下载最近的活动为 `.fit` 文件。
- 如果本地已经存在对应 FIT，则跳过重复下载。
- 支持分析单个 FIT 文件或整个 FIT 文件夹。
- 文件夹分析会按 FIT 的 `start_time` 从早到晚执行。
- 分析走隐藏的大模型 tool loop：
  - 第一次只发送简短 FIT 摘要；
  - 模型需要更多信息时，再请求分段、数值统计、采样记录、训练元数据或历史记录；
  - 完整隐藏交互会保存到 `data/chat_logs/`。
- 每次分析生成：
  - 完整 Markdown 活动报告；
  - 约 200 个中文字符、适合 Strava 的活动总结；口吻会加权随机选择，包含正常训练日志、专业教练、轻松骑友、简洁复盘、轻微自嘲和猫娘风格，其中猫娘概率会稍高；
  - 用于后续对比的紧凑 `history_entry`。
- 支持上传原始 FIT 到 Strava，并把生成的 Strava 总结作为活动描述。

## 安装

推荐 Python 3.12。

```bash
pip install -r requirements.txt
```

也可以使用 editable 模式：

```bash
pip install -e .
```

## 配置

在项目根目录创建 `config.yaml`。这个文件已经被 git 忽略。

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
  notes: "可写伤病、训练偏好、近期目标等"

strava:
  client_id: "your-strava-client-id"
  client_secret: "your-strava-client-secret"
  refresh_token: "your-strava-refresh-token"
  timeout_seconds: 120
```

`agent.base_url` 需要兼容 Anthropic Messages API 的 `/v1/messages`。

Strava 上传需要 token 具备 `activity:write` 权限。如果你已经有可用的短期 `access_token`，也可以在 `strava.access_token` 里直接配置。

如果上传时报 `activity:write_permission missing`，说明当前 Strava token 没有写入权限，需要重新授权：

```bash
python -m app.cli strava-auth-url
```

打开命令输出的 URL，授权后浏览器会跳转到一个带 `code` 参数的地址。复制这个 `code`，然后执行：

```bash
python -m app.cli strava-exchange-code "PASTE_CODE_HERE"
```

把返回结果里的 `refresh_token` 写回 `config.yaml` 的 `strava.refresh_token`。

## 下载 FIT

下载 Garmin 中国最近活动：

```bash
python download_garmin_cn_fit.py --config config.yaml
```

临时覆盖下载数量或输出目录：

```bash
python download_garmin_cn_fit.py --count 1 --output-dir garmin_cn_fit_files
```

本地已有的 FIT 文件会自动跳过。

## 分析 FIT

按时间顺序分析下载目录中的所有 FIT：

```bash
python -m app.cli analyze-folder garmin_cn_fit_files --history --force
```

`--history` 表示后面的活动可以参考前面已经生成的紧凑历史。第一条活动没有历史可参考。`--force` 表示即使 summary 已经存在，也重新请求大模型分析。

只分析还没有 summary 的文件：

```bash
python -m app.cli analyze-folder garmin_cn_fit_files --history
```

分析单个 FIT 文件：

```bash
python -m app.cli analyze-file "garmin_cn_fit_files/path/to/activity.fit" --history --force
```

## 输出文件

```text
garmin_cn_fit_files/          # 下载的原始 FIT 文件
data/reports/                 # Markdown 报告，包含 Strava Summary 小节
data/summaries/               # 每条活动的 JSON summary
data/activity_history.jsonl   # 大模型生成的紧凑训练历史
data/chat_logs/               # 完整大模型请求 / 响应 / tool loop 日志
```

`data/reports/*.md` 包含完整活动报告，以及 `## Strava Summary` 小节。

`data/summaries/*.summary.json` 包含：

- FIT 摘要；
- 完整 Markdown 报告；
- Strava 总结；
- 本次随机选择的 Strava 总结口吻；
- 大模型生成的历史条目；
- 原始 FIT 文件路径；
- 隐藏 tool loop 日志路径。

## 上传到 Strava

分析完成后，可以上传原始 FIT，并把生成的 Strava 总结作为活动描述：

```bash
python -m app.cli upload-strava "data/summaries/activity.summary.json"
```

自定义 Strava 活动标题：

```bash
python -m app.cli upload-strava "data/summaries/activity.summary.json" --title "Morning Ride"
```

如果活动已经在 Strava 上，只想更新描述：

```bash
python -m app.cli update-strava-description STRAVA_ACTIVITY_ID "data/summaries/activity.summary.json"
```

`upload-strava` 会从 summary JSON 里读取 `fit_path` 和 `strava_summary`。默认会等待 Strava 处理上传结果；如果只想拿到上传请求返回，可以加 `--no-wait`。

## 隐藏分析工具

FIT 分析 workflow 会把这些内部工具暴露给大模型：

- `get_fit_summary`
- `get_laps`
- `get_numeric_stats`
- `get_sampled_records`
- `get_training_metadata`
- `get_history`

正常 CLI 分析时，这些工具调用不会展示给用户，但完整记录会保存在 `data/chat_logs/`，方便调试。

## 常用命令

预览普通聊天 payload：

```bash
python -m app.cli chat-payload "你好" --mode plain
```

运行交互式 tool-loop 聊天：

```bash
python -m app.cli chat-tools "分析我的最新一次 FIT 活动"
```

查看工具目录：

```bash
python -m app.cli tools-catalog
```


