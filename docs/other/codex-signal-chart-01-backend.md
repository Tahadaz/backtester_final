# Codex Task: Backend — Per-Representative Indicator Data

## Goal

Modify the zone-chart API endpoint so that each representative in the response includes its own indicator data (not just the single top representative). Also add MACD crossover detection and OBV bar-signal classification helpers.

## File to modify

`services/api/app/routers/strategy_signals.py`

## Existing code context

- `_compute_indicator(close, variant, volume=volume)` is imported from `core.quant_core.signal_engine.variant_detail` and returns indicator dicts per archetype. **Do not modify this function.** It already handles all archetypes:
  - SMA `price_vs_sma`/`slope_confirmed`: `{"type": "overlay", "name": "SMA-{w}", "values": ndarray}`
  - SMA `sma_cross`: `{"type": "overlay_dual", "name": "SMA(f,s)", "fast": ndarray, "slow": ndarray, ...}`
  - RSI `rsi_level`: `{"type": "secondary_yaxis", "name": "RSI({p})", "values": ndarray, "thresholds": [oversold, overbought], "y_range": [0,100]}`
  - MACD `macd_cross`: `{"type": "secondary_yaxis", "name": "MACD(f,s,sig)", "macd_line": ndarray, "signal_line": ndarray, "histogram": ndarray}`
  - OBV `obv_trend`: `{"type": "secondary_yaxis", "name": "OBV-EMA({p})", "obv": ndarray, "ema_values": ndarray}`

- `_get_top_representative_indicator(detail, close, volume)` at line 765 — returns indicator for ONLY the top representative. **Keep this function** for backward compatibility.

- `_get_representatives_info(detail)` at line 799 — returns `[{variant_id, weight, label}]` for reps. **This function will be replaced** by the new `_get_all_representative_indicators`.

- `EnsemblePipelineDetail` has:
  - `all_summaries: list[VariantRobustnessSummary]` — each has `.variant` (VariantDef) and `.reliability_score`
  - `representative_ids: set[str]`
  - `fallback_variant_ids: set[str]`

- `_safe_float_list(arr)` at line 760 — converts numpy array to list of floats, NaN -> None. Already exists.

- `_variant_label(variant)` — already used, returns human-readable label like "SMA-20".

## Step 1: Add MACD crossover detection helper

Add this function BEFORE `_get_top_representative_indicator` (around line 763):

```python
def _detect_macd_crossovers(macd_line: list, signal_line: list) -> list[dict]:
    """Detect MACD / signal-line crossover bar indices."""
    crossovers: list[dict] = []
    for i in range(1, len(macd_line)):
        prev_m, curr_m = macd_line[i - 1], macd_line[i]
        prev_s, curr_s = signal_line[i - 1], signal_line[i]
        if prev_m is None or curr_m is None or prev_s is None or curr_s is None:
            continue
        prev_diff = prev_m - prev_s
        curr_diff = curr_m - curr_s
        if prev_diff <= 0 < curr_diff:
            crossovers.append({"bar_index": i, "direction": "bullish"})
        elif prev_diff >= 0 > curr_diff:
            crossovers.append({"bar_index": i, "direction": "bearish"})
    return crossovers
```

## Step 2: Add OBV bar-signal helper

Add immediately after the function above:

```python
def _compute_obv_bar_signals(obv: list, ema_vals: list) -> list[str]:
    """Per-bar accumulation / distribution / neutral classification."""
    signals: list[str] = []
    for i in range(len(obv)):
        o, e = obv[i], ema_vals[i]
        if o is None or e is None:
            signals.append("neutral")
        elif o > e:
            signals.append("accumulation")
        elif o < e:
            signals.append("distribution")
        else:
            signals.append("neutral")
    return signals
```

## Step 3: Add `_get_all_representative_indicators`

Add after the OBV helper. This replaces `_get_representatives_info` in the response assembly:

```python
def _get_all_representative_indicators(
    detail: EnsemblePipelineDetail,
    close: np.ndarray,
    volume: np.ndarray | None,
) -> list[dict]:
    """Representative entries enriched with per-variant indicator data."""
    reps = [
        s for s in detail.all_summaries
        if s.variant.variant_id in detail.representative_ids
    ]
    if not reps:
        reps = [
            s for s in detail.all_summaries
            if s.variant.variant_id in detail.fallback_variant_ids
        ]

    result: list[dict] = []
    for s in reps:
        entry: dict = {
            "variant_id": s.variant.variant_id,
            "weight": round(s.reliability_score, 4),
            "label": _variant_label(s.variant),
        }

        ind = _compute_indicator(close, s.variant, volume=volume)
        if ind["type"] == "none":
            entry["indicator"] = None
        else:
            ind_serialized: dict = {"type": ind["type"], "name": ind.get("name", "")}
            for key, val in ind.items():
                if key in ("type", "name"):
                    continue
                if isinstance(val, np.ndarray):
                    ind_serialized[key] = _safe_float_list(val)
                else:
                    ind_serialized[key] = val

            # Family-specific enrichments
            if "macd_line" in ind_serialized and "signal_line" in ind_serialized:
                ind_serialized["crossovers"] = _detect_macd_crossovers(
                    ind_serialized["macd_line"], ind_serialized["signal_line"],
                )
            if "obv" in ind_serialized and "ema_values" in ind_serialized:
                ind_serialized["bar_signals"] = _compute_obv_bar_signals(
                    ind_serialized["obv"], ind_serialized["ema_values"],
                )

            entry["indicator"] = ind_serialized

        result.append(entry)
    return result
```

## Step 4: Modify response assembly in `signal_zone_chart`

Find the response assembly block (around lines 896-901):

```python
        families[fam] = {
            "scores": [round(float(s), 2) for s in scores],
            "zones": zones,
            "representatives": _get_representatives_info(detail),
            "indicator": _get_top_representative_indicator(detail, close, volume),
        }
```

Replace with:

```python
        families[fam] = {
            "scores": [round(float(s), 2) for s in scores],
            "zones": zones,
            "representatives": _get_all_representative_indicators(detail, close, volume),
            "indicator": _get_top_representative_indicator(detail, close, volume),
        }
```

The only change is replacing `_get_representatives_info(detail)` with `_get_all_representative_indicators(detail, close, volume)`.

## Do NOT modify

- `_compute_indicator` in `variant_detail.py`
- `_get_top_representative_indicator` — keep for backward compatibility
- Any test files
- Any other endpoint

## Verification

After changes, run:
```bash
python -m pytest core/tests/ -q
```
All existing tests must pass. The backend change is purely additive (existing `indicator` field kept, representative entries now have an extra `indicator` key).
