
import json
from fit.parser import parse_fit
from core.file_workflow import call_fit_analysis_tool

parsed = parse_fit("594588818_ACTIVITY.fit")

for tool, args in [
    # ("get_activity_overview", {}),
    # ("get_time_intervals", {"bucket_seconds": 30, "start_s":200, "end_s": 500}),
    ("get_distance_intervals", {"bucket_distance_m": 500})

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

