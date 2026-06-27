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


这个组织方式**很好**，而且我觉得比“主 agent 直接暴露几十个 FIT 细工具”更合理。

你可以把它理解成：

```text
主 Agent：负责理解用户意图、选择业务能力
子 Agent：负责某个领域的多步推理和细工具调用
底层 Tool：负责确定性数据读取/计算
```

也就是：

```text
用户
 ↓
Main Agent
 ├─ analyze_activity        → ActivityAnalysisAgent
 ├─ upload_activity         → UploadWorkflow
 ├─ download_activities     → DownloadWorkflow
 ├─ compare_activities      → ActivityCompareAgent
 ├─ find_activity           → ActivityResolver
 └─ route_advice            → RouteAdviceAgent
```

然后 `ActivityAnalysisAgent` 内部才暴露：

```text
get_activity_overview
get_activity_summary
get_time_intervals
get_distance_intervals
scan_activity_segments
analyze_hr_drift
analyze_pacing
detect_intervals
```

这个设计是对的。

---

## 为什么这样更好？

因为主 Agent 不应该关心：

```text
要不要 60s interval
要不要 scan segment
要不要看 distance bucket
要不要检查心率漂移
```

这些是“活动分析专家”的事情。

主 Agent 只需要知道用户想干嘛：

```text
分析这次骑行
上传到 Strava
下载 Garmin 活动
比较最近几次
找昨天那条活动
```

这样主 Agent 的工具会很少，也更稳定。

---

## 推荐结构

我建议分两层 tool。

### 第一层：Main Agent Tools

主 Agent 只看到粗粒度工具：

```python
MAIN_AGENT_TOOLS = [
    "analyze_activity",
    "compare_activities",
    "find_activity",
    "download_activities",
    "upload_activity",
    "sync_activities",
    "generate_route_advice",
]
```

这些工具是业务级别的。

---

### 第二层：Sub Agent Tools

比如 `analyze_activity` 的 handler 内部启动一个子 agent：

```text
analyze_activity(...)
  ↓
ActivityAnalysisAgent
  ↓
get_activity_summary
get_time_intervals
scan_activity_segments
...
  ↓
返回 markdown_report / strava_summary / history_entry
```

这里的细工具只给子 Agent，不给主 Agent。

---

## 大概代码形态

可以这样：

```python
def handle_analyze_activity(
    activity_id: str | None = None,
    fit_path: str | None = None,
    user_request: str = "",
    analysis_depth: str = "normal",
) -> dict:
    activity = resolve_activity_handle(activity_id=activity_id, fit_path=fit_path)

    result = run_activity_analysis_agent(
        activity=activity,
        user_request=user_request,
        analysis_depth=analysis_depth,
        tools=FIT_ANALYSIS_TOOLS,
    )

    return {
        "status": "completed",
        "activity": activity.to_dict(),
        "markdown_report": result.markdown_report,
        "strava_summary": result.strava_summary,
        "history_entry": result.history_entry,
    }
```

主 Agent 只调用：

```json
{
  "name": "analyze_activity",
  "arguments": {
    "activity_id": "xxx",
    "user_request": "分析这次骑行，看看有没有掉功率"
  }
}
```

它不需要知道 `get_time_intervals`。

---

## ActivityAnalysisAgent 内部工具

这里才暴露你那组细工具：

```python
FIT_ANALYSIS_TOOLS = [
    get_activity_overview,
    get_activity_summary,
    get_time_intervals,
    get_distance_intervals,
    scan_activity_segments,
    analyze_hr_drift,
    analyze_pacing,
    detect_intervals,
]
```

这个子 Agent 的 system prompt 可以更专业：

```text
你是单次耐力运动分析 agent。
你只能分析当前 activity。
你可以调用 FIT data tools 获取客观数据。
你不能上传、删除、同步活动。
最终返回结构化报告。
```

这样边界非常清楚。

---

## Compare 也建议做成子 Agent

比如：

```text
Main Agent tool:
compare_activities
```

内部：

```text
ActivityCompareAgent
 ├─ resolve_activity_range
 ├─ get_activity_summary for each activity
 ├─ compare_activity_metrics
 ├─ get_training_trend
 └─ final comparison report
```

这里不要直接复用单次分析 agent 输出一堆长报告。

对比 Agent 应该返回：

```text
共同点
差异点
进步/退步
训练负荷变化
下一步建议
```

也就是说：

```text
单次分析 agent：看一场活动细节
历史对比 agent：看多场活动之间的变化
```

---

## 上传/下载不一定需要 LLM 子 Agent

这点要注意。

比如：

```text
download_activities
upload_activity
sync_activities
```

这些最好是**确定性 workflow**，不一定需要子 Agent。

因为上传下载是副作用操作，越少 LLM 参与越好。

推荐：

```text
Main Agent
  → upload_activity tool
  → 权限确认
  → deterministic upload workflow
  → 返回结果
```

不要让 upload 子 Agent 自己决定要不要传、传哪个、要不要更新描述。它最多接收已经确认好的参数。

---

## 我建议你最终分成这样

```text
Main Agent Tools

├── Activity
│   ├── find_activity
│   ├── analyze_activity          # 内部是子 agent
│   └── compare_activities        # 内部是子 agent
│
├── Data IO
│   ├── download_activities       # 确定性 workflow
│   ├── import_fit_file           # 确定性 workflow
│   └── sync_activity_index       # 确定性 workflow
│
├── Publishing
│   ├── upload_activity           # 确定性 workflow + confirmation
│   └── update_strava_description # 确定性 workflow + confirmation
│
└── Route
    └── generate_route_advice     # 子 agent 或普通 LLM
```

---

## 最关键的边界

我觉得你要坚持这几个规则：

### 1. 主 Agent 不看细 FIT 工具

主 Agent 不应该有：

```text
get_time_intervals
scan_activity_segments
detect_intervals
```

否则它会乱用。

---

### 2. 子 Agent 不能有副作用工具

ActivityAnalysisAgent 只能读数据，不能上传、删除、同步。

```text
分析子 Agent：read-only
上传 workflow：side-effect
```

这两个必须分开。

---

### 3. 子 Agent 返回结构化结果

不要只返回一段文本。

建议：

```python
class ActivityAnalysisResult(BaseModel):
    markdown_report: str
    strava_summary: str
    history_entry: dict
    used_tools: list[str]
    data_quality_notes: list[str]
```

主 Agent 收到之后，可以决定：

```text
展示给用户
保存历史
后续上传 Strava 描述
```

---

### 4. 避免无限嵌套

不要搞成：

```text
Main Agent → Sub Agent → Sub Agent → Sub Agent
```

最多两层：

```text
Main Agent → Domain SubAgent → Data Tools
```

这个就够了。

---

## 结论

你的想法是对的。更推荐这样：

```text
主 Agent 暴露粗粒度业务工具
活动分析作为一个子 Agent
FIT 细工具只给活动分析子 Agent
上传/下载保持确定性 workflow
历史对比单独做 CompareAgent
```

这个架构会比“主 Agent 直接拿所有工具”稳定很多，也更容易扩展到跑步、公路车、Strava、训练计划。
