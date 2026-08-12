# Agent Evaluation

这套评测把 Main Agent 的路由、真实模型工具选择、任务结果、回答约束、耗时和 Token 用量写成可重复比较的报告。

## 两种模式

- `router`：只运行本地 Intent Router，不调用模型，不产生外部副作用，适合每次提交和 CI。
- `live`：调用 `config.yaml` 中配置的真实模型，但把所有工具替换为评测 Sandbox。不会同步 Garmin、写 Strava 或修改活动数据。

## 运行

```bash
python -m evaluation.cli list-cases
python -m evaluation.cli run
python -m evaluation.cli run --cases evaluation/cases/live.jsonl --mode live --repeats 3
```

报告默认写入 `evaluation/artifacts/<UTC timestamp>/`：

- `results.jsonl`：每次 Case 的 Result、Trace 和评分。
- `summary.json`：汇总指标，适合版本对比或 CI。
- `report.md`：人工可读报告和失败原因。

如果已知模型单价，可以计算估算成本：

```bash
python -m evaluation.cli run \
  --cases evaluation/cases/live.jsonl \
  --mode live \
  --input-price 1.0 \
  --output-price 2.0 \
  --cache-write-price 1.0 \
  --cache-read-price 0.1
```

价格单位为每百万 Token 的美元价格。如果模型返回了缓存 Token，而对应缓存价格没有提供，成本也会显示为 `not configured`，避免产生不完整估算。

## Case 约束

每行是一个 `agent_eval_case.v1` JSON 对象。工具评分使用约束而不是要求完整轨迹逐字相同：

- `required_tools`：必须出现，且参数匹配。
- `forbidden_tools`：不能出现。
- `ordered_tools`：只约束关键调用的相对顺序。
- `completion`：检查 Agent 结果和指定工具结果。
- `answer_assertions`：检查关键事实必须出现或禁止出现。

真实模型评测具有波动性；建议 `--repeats 3`，离线路由评测保持单次即可。

GitHub Actions 会运行无模型、无副作用的 Router 套件，并要求当前回归集保持 `100%`。真实模型套件需要本地 `config.yaml`，不在普通 PR 中自动运行。
