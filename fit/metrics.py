from __future__ import annotations

from typing import Any

import pandas as pd

from analysis.derived import derived_metrics
from analysis.stats import sample_statistics


def compute_fit_metrics(summary: dict[str, Any], df: pd.DataFrame) -> dict[str, Any]:
    samples = sample_statistics(df)
    return {
        "sample_statistics": samples,
        "derived": derived_metrics(summary, samples, df),
    }
