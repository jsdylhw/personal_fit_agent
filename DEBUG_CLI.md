# Debug CLI

`app.debug_cli` 是开发和调试入口,用于检查底层工具返回、FIT 解析结果和本地活动索引。

主入口仍然是:

```bash
python -m app.cli ...
```

调试入口是:

```bash
python -m app.debug_cli ...
```

## 查看工具列表

列出 agent 当前暴露的工具:

```bash
python -m app.debug_cli list-tools
```

只看 FIT hidden tool loop 的只读工具:

```bash
python -m app.debug_cli list-tools --no-all-tools
```

## 直接调用工具

查看活动摘要:

```bash
python -m app.debug_cli tool-call get_activity_summary --fit latest --args '{"sections":["power"]}'
```

查看 60 秒时间窗口聚合:

```bash
python -m app.debug_cli tool-call get_time_intervals --fit latest --args '{"bucket_seconds":60}'
```

查看 100-200 秒窗口:

```bash
python -m app.debug_cli tool-call get_time_intervals --fit latest --args '{"bucket_seconds":5,"start_s":100,"end_s":200}'
```

查看 1 公里距离窗口聚合:

```bash
python -m app.debug_cli tool-call get_distance_intervals --fit latest --args '{"bucket_distance_m":1000}'
```

## 初始工作流规划

调用 LLM planner 生成粗粒度步骤计划,只输出计划,不执行任何工具:

```bash
python -m app.debug_cli plan-workflow "帮我同步最近两条 Garmin 活动并分析"
```

如果当前请求涉及当前 FIT,可以传 `--fit`:

```bash
python -m app.debug_cli plan-workflow "分析这次骑行并给明天建议" --fit latest
```

调试 planner 输入 payload:

```bash
python -m app.debug_cli plan-workflow "最近一周训练怎么样" --include-payload
```

## 检查 FIT 解析

```bash
python -m app.debug_cli inspect-fit latest
```

也可以传具体文件:

```bash
python -m app.debug_cli inspect-fit garmin_cn_fit_files/activity.fit
```

## 活动索引

把单个 FIT 登记到 `data/activity_index.json`:

```bash
python -m app.debug_cli index-fit latest
```

扫描本地 FIT 和 summary,重建索引:

```bash
python -m app.debug_cli rebuild-index
```

列出活动:

```bash
python -m app.debug_cli list-activities
```

按日期解析活动:

```bash
python -m app.debug_cli resolve-activity --date-local 2026-05-14
```

获取日期范围内活动:

```bash
python -m app.debug_cli activities-in-range 2026-05-01 2026-05-07
```

## 使用建议

- 调 prompt 前,先用 `tool-call` 看工具真实返回。
- 调周/月分析前,先用 `rebuild-index` 和 `list-activities` 确认活动索引是否完整。
- 如果 agent 选错工具,优先检查 `list-tools` 里的 description 是否容易误导模型。
