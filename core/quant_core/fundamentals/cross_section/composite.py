from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

CORE_PILLAR_COLUMNS = ("pillar_val", "pillar_qual", "pillar_fmom")
LEGACY_PILLAR_COLUMNS = CORE_PILLAR_COLUMNS + ("pillar_pmom",)


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
    legacy_scores = []
    coverage = []
    attribution = []
    for _, row in out.iterrows():
        core_vals = {col: _finite(row.get(col)) for col in CORE_PILLAR_COLUMNS}
        legacy_vals = {col: _finite(row.get(col)) for col in LEGACY_PILLAR_COLUMNS}
        core_present = {col.replace("pillar_", ""): val for col, val in core_vals.items() if val is not None}
        legacy_present = {col.replace("pillar_", ""): val for col, val in legacy_vals.items() if val is not None}
        if len(core_present) >= min_pillars:
            scores.append(float(np.mean(list(core_present.values()))))
        else:
            scores.append(float("nan"))
        if len(legacy_present) >= min_pillars:
            legacy_scores.append(float(np.mean(list(legacy_present.values()))))
        else:
            legacy_scores.append(float("nan"))
        coverage.append(len(core_present) / float(len(CORE_PILLAR_COLUMNS)))
        attribution.append(core_present)
    out["sfc"] = scores
    out["sfc_legacy"] = legacy_scores
    out["pmom"] = pd.to_numeric(out.get("pillar_pmom"), errors="coerce")
    out["coverage_ratio"] = coverage
    out["pillar_attribution"] = attribution
    out["is_covered"] = out["sfc"].apply(lambda v: math.isfinite(float(v)) if v is not None else False)
    out["is_covered_legacy"] = out["sfc_legacy"].apply(lambda v: math.isfinite(float(v)) if v is not None else False)
    return out
