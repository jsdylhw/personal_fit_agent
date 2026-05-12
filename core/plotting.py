from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from fit.parser import records_dataframe


def plot_activity(parsed: dict[str, Any], output_path: str | Path) -> Path:
    df = records_dataframe(parsed["records"])
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    fields = [
        ("heart_rate", "Heart Rate", "bpm"),
        ("power", "Power", "W"),
        ("speed", "Speed", "m/s"),
        ("altitude", "Altitude", "m"),
    ]
    available = [(f, title, unit) for f, title, unit in fields if f in df.columns]
    if df.empty or not available:
        raise RuntimeError("没有可绘图的时序字段")

    x = df["elapsed_s"] / 60 if "elapsed_s" in df.columns else df.index
    xlabel = "Elapsed time (min)" if "elapsed_s" in df.columns else "Record index"

    fig, axes = plt.subplots(len(available), 1, figsize=(10, 2.6 * len(available)), sharex=True)
    if len(available) == 1:
        axes = [axes]
    for ax, (field, title, unit) in zip(axes, available):
        ax.plot(x, df[field], linewidth=1)
        ax.set_ylabel(unit)
        ax.set_title(title)
        ax.grid(True, alpha=0.25)
    axes[-1].set_xlabel(xlabel)
    fig.tight_layout()
    fig.savefig(output, dpi=150)
    plt.close(fig)
    return output
