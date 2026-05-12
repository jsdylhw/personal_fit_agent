from typing import Any

from analysis import analyze_parsed
from analysis.report import write_analysis_report
from .config import ensure_data_dirs
from fit.parser import parse_fit
from .plotting import plot_activity
from .storage import archive_fit, get_activity, latest_activity, update_activity_summary


def import_fit(path: str, source: str = "manual") -> dict[str, Any]:
    return archive_fit(path, source=source)


def analyze_activity(activity_id: int | str = "latest", make_plot: bool = True) -> dict[str, Any]:
    activity = latest_activity() if activity_id == "latest" else get_activity(int(activity_id))
    if not activity:
        raise RuntimeError("还没有归档的活动")
    parsed = parse_fit(activity["fit_path"])
    analysis = analyze_parsed(parsed)
    update_activity_summary(activity["id"], summary=parsed["summary"], analysis=analysis)

    result = {
        "activity_id": activity["id"],
        "fit_path": activity["fit_path"],
        "summary": parsed["summary"],
        "analysis": analysis,
    }
    if make_plot:
        paths = ensure_data_dirs()
        plot_path = paths["plots"] / f"activity_{activity['id']}.png"
        result["plot_path"] = str(plot_activity(parsed, plot_path))

    report_path = write_analysis_report(result)
    result["report_path"] = str(report_path)
    return result
