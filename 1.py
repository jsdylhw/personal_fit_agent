
import json
from fit.parser import parse_fit
from agent.tools import call_fit_analysis_tool

parsed = parse_fit("594588818_ACTIVITY.fit")

# |---|---|
# | `get_activity_overview` | 高层活动概览(运动类型,时长,距离,基础指标,数据可用性) |
# | `get_activity_summary` | 按模块获取结构化摘要(功率,心率,踏频,海拔,训练负荷等) |
# | `get_time_intervals` | 固定时间窗口的聚合平均值,支持按时间范围过滤 |
# | `get_distance_intervals` | 固定距离窗口的聚合平均值,支持按距离范围过滤 |
# | `get_history` | 获取历史训练记录用于纵向对比 |
for tool, args in [
    ("get_activity_summary", {}),
    # ("get_time_intervals", {"bucket_seconds": 30, "start_s":200, "end_s": 500}),
    # ("get_distance_intervals", {"bucket_distance_m": 500})

    # ("get_laps", {}),
    # ("get_training_metadata", {}),
    # ("get_sampled_records", {"max_records": 20}),
    # ("get_interval_series", {"interval_seconds": 60}),
]:
    result = call_fit_analysis_tool(
        tool,
        args,
        parsed=parsed,
        history_before=None,
    )
    print("\n" + "=" * 80)
    print(tool)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

