现在路线规划这一步还只是占了一个粗粒度 step：

```python
generate_route_advice
```

位置在 [agent/plan_schema.py](/home/liuhaowen/codes/personal_fit_agent/agent/plan_schema.py:154)，selector 里目前只给了：

```python
allowed_tools=("read_activity_summary", "get_history")
```

也就是说：**现在路线建议还没真正打通，只是预留了“根据历史和活动报告给路线类型建议”的入口。**

我建议路线模块先分两层做。

**第一层：训练状态判断工具**
这些工具不直接生成路线，只回答“今天适合骑什么”：

- `read_activity_summary`
  读取最近活动 summary，拿疲劳、强度、爬升、间歇、TSS/IF 等摘要。
- `get_history`
  获取近期训练历史，比如最近 7/14/30 天总量、强度分布、恢复情况。
- `summarize_recent_training_load`
  可以后面补成显式工具，输出：最近训练负荷、是否疲劳、适合强度。
- `infer_route_constraints`
  根据用户目标和训练状态生成路线约束：
  - 距离范围
  - 爬升范围
  - 强度目标
  - 是否避开高强度爬坡
  - 是否适合恢复骑 / 耐力骑 / 间歇路线

这一层适合接 LLM，因为它是“分析和建议”。

**第二层：路线候选工具**
这些工具负责真实路线数据，不能让 LLM 瞎编：

- `search_route_candidates`
  按起点、距离、爬升、路线类型找候选路线。
- `get_route_elevation_profile`
  分析路线爬升分布、坡段、坡度、长爬坡。
- `score_route_for_training_goal`
  给候选路线打分，比如恢复骑不适合大爬升，间歇日需要稳定路段。
- `export_route_gpx`
  用户确认后导出 GPX。
- `save_route_plan`
  保存路线建议和候选结果，方便后续复用。

这一层尽量本地/确定性工具做，LLM 只读结果后组织语言。

我觉得 `generate_route_advice` 的 allowed tools 应该逐步变成：

```python
ROUTE_ADVICE_TOOLS = (
    "read_activity_summary",
    "get_history",
    "summarize_recent_training_load",
    "infer_route_constraints",
    "search_route_candidates",
    "get_route_elevation_profile",
    "score_route_for_training_goal",
)
```

其中第一阶段先实现前三四个就够了：

```python
("read_activity_summary", "get_history", "infer_route_constraints")
```

先不做 GPX、不做真实地图路线，输出“路线约束”最稳。比如用户说“明天想骑 50 公里”，结果应该是：

```text
建议路线类型: Z2 耐力骑
距离: 45-55 km
爬升: 200-500 m
强度: 避免长时间阈值以上
路线偏好: 平路或缓坡环线
依据: 最近两次活动强度偏高/爬升较多/恢复不足
```

等这个跑顺了，再接 `route-agent` 或本地路线库做候选路线搜索。