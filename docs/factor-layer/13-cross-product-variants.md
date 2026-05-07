# 13 — Cross-Product Variants (Factor × TA)

> Station mandate: define the composition semantics, naming convention, channel-tag gating, FDR posture, and architectural constraints for the Phase 2 factor-conditioned signal family.

## 1. Core Thesis

A factor-conditioned variant = one existing TA indicator AND one pre-registered factor condition. The variant fires its underlying signal (+1/−1) only when the macro condition holds on the same evaluation date. When the condition is False, it emits HOLD (0) — it does **not** invert the TA signal.

This is an additive family. Native TA variants remain untouched and continue to run through the A–G pipeline independently. Factor-conditioned variants flow through the **same unchanged** Layers B–G as a new family (`{ta_family}@fx`).

## 2. Composition Semantics

### 2.1 AND-gate

```
conditioned_signal[t] = ta_signal[t]   if condition[t] == True
                       = 0.0            otherwise
```

Implemented in `core/quant_core/research/factors/conditioned_variants.py:compose_and_signal`.

### 2.2 Position-keeping rule

HOLD (0.0) means "no new signal this bar", not "exit now". The OOS evaluator's `signal_to_long_only_positions` converts 0 to "hold previous position". An existing position is kept open until the underlying TA emits an explicit exit (−1).

**Why**: avoids whipsaw on factor-only state flips (e.g. VIX z-score oscillating around the threshold). The entry/exit logic remains fully TA-driven; the factor is a gate on entries only.

### 2.3 No look-ahead

All six factors (VIX, SP500, Brent, DXY, EURUSD, US10Y) close after MASI's 09:00 UTC open. Calendar-aware alignment (`research/alignment.py`, `lag_rule='precede_open'`) ensures factor close at session-date t−1 is used for MASI day t. This is the same alignment built in Phase 0 and verified by the adversarial unit tests in `test_alignment.py`.

## 3. Factor Conditions (Pre-Registered)

| condition_id | factor_ticker | form | lookback | threshold | direction | channel_gate |
|---|---|---|---|---|---|---|
| `vix_z20_below_neg1` | `^VIX` | zscore | 20 | −1.0 | below | all |
| `vix_z20_above_pos2` | `^VIX` | zscore | 20 | +2.0 | above | all |
| `spx_mom5_above_zero` | `^GSPC` | momentum | 5 | 0.0 | above | all |
| `brent_mom20_above_zero` | `BZ=F` | momentum | 20 | 0.0 | above | materials, mining, chemicals |
| `dxy_mom20_below_zero` | `DX-Y.NYB` | momentum | 20 | 0.0 | below | all |
| `eurusd_mom20_above_zero` | `EURUSD=X` | momentum | 20 | 0.0 | above | all |
| `ust10_change5_above_20bp` | `^TNX` | change | 5 | 0.0020 | above | banks, insurance, real_estate |

Full machine-readable spec: `docs/research/phase2_pre_registration.yaml`.

### Condition forms

- **zscore**: rolling z-score of factor vs threshold — `(value − μ_N) / σ_N`
- **momentum**: N-day percentage return vs threshold — `(p_t − p_{t-N}) / p_{t-N}`
- **change**: absolute N-day change vs threshold (used for yield moves in decimal, e.g. 0.0020 = 20 bp)
- **level**: raw value vs threshold
- **direction**: sign of 1-day change (lookback=1, threshold=0)

Implemented in `core/quant_core/research/factors/conditions.py:evaluate_condition`.

## 4. Naming Convention

| Field | Value |
|---|---|
| `family` | `{ta_family}@fx` — e.g. `sma@fx` |
| `archetype` | same as TA variant |
| `params` | TA params + `factor_condition_id` key |
| `variant_id` | SHA256 of extended params → `sv_<hex16>` |
| `description` | `{ta_desc}@{condition_id}` — e.g. `SMA-20 (short)@vix_z20_below_neg1` |

The `factor_condition_id` key in params ensures hash-distinctness from the native TA variant. The `@fx` family suffix ensures distinctness in all family-keyed lookups.

## 5. Channel-Tag Gating

Cross-product is not taken blindly. For each stock, only conditions whose factor has a channel tag matching the stock's sector are included. Most stocks have 3–4 applicable factors, yielding ~30–50 conditioned variants per stock — manageable for BH-FDR at q=0.10.

Channel tags are defined in `docs/research/channel_tags.yaml`.

## 6. Cardinality Budget

- ~8–10 pre-registered conditions
- ~100 TA variants across 20 families per stock
- Naive cross-product: ~800–1,000 per stock
- After channel gating: ~30–50 per stock
- Two independent FDR universes per stock (TA-only and Factor×TA)

## 7. FDR Posture

BH-FDR is applied at q=0.10 per stock, **independently** for the TA-only and Factor×TA variant sets. This avoids penalizing one universe for the size of the other.

Incremental value claim: a factor-conditioned variant is "value-adding" only if the bootstrap 95% CI lower bound on (Sharpe_fx_ta − Sharpe_native_ta_baseline) > 0, using stationary bootstrap with ≥5,000 resamples.

DSR for headline cross-stock claims uses the combined trial count across both universes (honest reflection of search space).

## 8. Architectural Bet

Layers B–G of the signal engine are family-agnostic. Factor-conditioned variants enter Layer A as `VariantDef` instances with `family="{ta_family}@fx"`. The only required change in the existing pipeline is a backward-compatible `precomputed_signal: np.ndarray | None = None` parameter in `evaluate_variant_oos` (Layer B). When provided, the function skips `compute_signal_array` and uses the pre-composed AND-signal directly.

**If Layer B–G needs further changes for factor-conditioned variants, it indicates a family-agnostic abstraction leak and requires a design review before proceeding.**

Verification: see `core/tests/test_signal_engine_factor_x_ta.py` — the Day-1 architectural smoke test.

## 9. Per-Stock Factor Configuration

The `stock_factor_config` database table (Alembic migration in `services/api/app/alembic/`) records which factors are enabled per stock. Default: all 6 enabled. The user can toggle factors per stock on the Factor×TA signal page tab. Disabled factors' conditions are excluded from the cross-product for that stock.
