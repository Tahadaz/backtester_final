from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

PILLAR_COLUMNS = ("pillar_val", "pillar_qual", "pillar_fmom", "pillar_pmom")


def _finite(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def compute_sfc(panel: pd.DataFrame, *, min_pillars: int = 2) -> pd.DataFrame:
    out = panel.copy()
    if out.empty:
        return out
    scores = []
    coverage = []
    attribution = []
    for _, row in out.iterrows():
        vals = {col: _finite(row.get(col)) for col in PILLAR_COLUMNS}
        present = {col.replace("pillar_", ""): val for col, val in vals.items() if val is not None}
        if len(present) >= min_pillars:
            scores.append(float(np.mean(list(present.values()))))
        else:
            scores.append(float("nan"))
        coverage.append(len(present) / float(len(PILLAR_COLUMNS)))
        attribution.append(present)
    out["sfc"] = scores
    out["coverage_ratio"] = coverage
    out["pillar_attribution"] = attribution
    out["is_covered"] = out["sfc"].apply(lambda v: math.isfinite(float(v)) if v is not None else False)
    return out
