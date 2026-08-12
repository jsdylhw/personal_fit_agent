# Personal FIT Agent

![Personal FIT Agent — 运动分析助手主视觉](figure.png)

一个以本地 FIT 运动数据为中心的个人运动助手。它把 Garmin 活动整理为可查询的本地记录，用自然语言回答训练问题、生成活动分析，并可按需上传到 Strava。

## 能做什么

- 从 Garmin 中国同步活动，或直接读取本地 `.fit` 文件。
- 分析骑行与跑步活动：强度、功率/配速、心率、分段、冲刺、爬升和恢复建议。
- 用自然语言查询单次活动，例如“100–200 秒有没有连续冲刺”。
- 汇总最近活动、比较训练表现、查看训练负荷，并给出下一次训练建议。
- 批量生成活动报告、上传 Strava；中断或失败后可继续处理。
- 提供本地 OSM/GraphHopper 骑行路线实验：搜索景点、生成自由环线，或用热门爬坡路段组合训练路线。

## 它如何工作

运动数据、活动索引、分析报告和处理记录默认保存在本地。大模型负责理解问题、选择分析方式和解释结果；FIT 解析、指标计算、路线计算和文件管理由本地程序完成。

只有在你主动使用时才会访问外部服务：Garmin 用于同步、配置的大模型服务用于分析、Strava 用于上传。请把账号和 API 凭据放在本地 `config.yaml`，不要提交到 Git。

## 快速开始

推荐 Python 3.12 或更高版本：

```bash
pip install -r requirements.txt
```

从示例创建本地配置：

```bash
cp config.yaml.example config.yaml
```

编辑 `config.yaml` 并填入凭据：`agent` 用于对话和分析；Garmin 配置仅在同步时需要；Strava 配置仅在上传时需要。若要通过局域网或反向代理访问 Web UI，请设置随机的 `web_api_token`。`config.yaml` 不会提交到 Git。

启动对话：

```bash
python -m app.cli chat
```

可以直接这样提问：

```text
分析最近一次活动
今天上午这次骑行 100–200 秒有没有连续冲刺？
汇总最近一周训练负荷，并建议下次训练
同步最新五个活动，分析后上传到 Strava
```

也可直接分析一个本地文件：

```bash
python -m app.cli analyze-file "garmin_cn_fit_files/path/to/activity.fit"
```

## 本地路线实验

路线 Demo 位于 `demo/osm_cycling_router/`。它使用本地 OpenStreetMap 数据和 GraphHopper 计算路线，适合验证景点检索、自由环线、热门爬坡路段组合与回头路惩罚等能力：

```bash
cd demo/osm_cycling_router
docker compose up --build
```

启动后打开 <http://127.0.0.1:8080>。这是独立实验能力，暂未接入主 Agent 对话链路。

## Agent 评测

项目提供离线路由回归和真实模型工具选择评测。真实模型模式使用无副作用 Sandbox，不会访问 Garmin 或写入 Strava：

```bash
python -m evaluation.cli run
python -m evaluation.cli run --cases evaluation/cases/live.jsonl --mode live --repeats 3
```

评测输出工具选择成功率、任务完成率、回答一致性、响应时间、Token 用量和可选的估算成本。用例格式与报告说明见 [`evaluation/README.md`](evaluation/README.md)。

## 数据与隐私

- 下载的 FIT、分析报告和活动处理记录均为本地运行产物，默认不提交到 Git。
- `config.yaml`、令牌和第三方授权结果应只保留在本机。
- 上传到 Strava 是显式操作；分析与路线建议不等同于安全骑行或医疗建议。
