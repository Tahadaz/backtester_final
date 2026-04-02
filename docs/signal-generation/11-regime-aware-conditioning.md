# Signal Engine — Regime-Aware Signal Conditioning

> **Status:** v0.1 implemented — single detector (Kaufman ER, window=20). Toggle available on signal page. Equal-weight fallback remains active when regime weighting does not beat equal-weight OOS.

## What

Regime-aware conditioning detects whether a stock is currently in a:

- `trending`
- `ranging`
- `mixed`

environment, then adjusts the signal-family weighting accordingly. The key principle is that the weights are not hand-picked; they are **measured out of sample**.

## Why This Belongs in the Signal Layer

Regime-aware conditioning is a form of **signal research** — it modifies how signal families are combined based on market state. It does not determine trade construction (entry, stop, target, sizing). In the separation between alpha research and portfolio construction (De Prado 2018, Grinold & Kahn 2000), regime conditioning improves the **information coefficient** of the combined signal. Strategy consumes the resulting signal policy as an opaque score.

Concretely:

- The signal engine already runs a 7-layer OOS pipeline (A→G) per family
- Regime detection uses the **same methodology**: walk-forward OOS validation, survivor selection, correlation filtering
- It is architecturally identical to the signal pipeline — just applied to family weighting instead of individual variants

## Why

Technical indicators do not perform equally well in every market context. Blindly averaging trend-following and oscillation-oriented families often dilutes useful information.

For example:

- SMA / MACD / OBV are structurally more useful in trending phases
- RSI is often more useful in range or mean-reverting phases

Without regime conditioning, the consensus treats structurally different signal families as if they were interchangeable.

## Detection Scope

In v1, regime detection runs **per stock**, not at the MASI index level.

This is the recommended v1 approach for three reasons:

1. walk-forward OOS validation will naturally penalize noisy per-stock regime candidates, so weak detectors simply will not survive
2. per-stock detection is consistent with the existing signal pipeline, which operates per `(symbol, horizon)`
3. if a stock is too noisy for any regime candidate to survive, the equal-weight fallback handles that case gracefully

Market-level regime detection, computed for example on the MASI and then applied across stocks, remains a valid future extension. In this architecture it should be introduced as an additional regime-candidate type, not as an implicit replacement for the per-stock default.

## Candidate Set

The layer should test about 14 candidates in total:

### 1. Kaufman Efficiency Ratio

```text
ER(N) = |Price[t] - Price[t-N]| / Sum(|Price[i] - Price[i-1]|)
```

v1 windows:

- 10
- 15
- 20
- 30
- 50

Interpretation:

- close to 1: efficient directional movement, therefore trend
- close to 0: chop / noise

### 2. Rolling Return Autocorrelation

```text
AC(N) = Corr(returns[t], returns[t-1]) over rolling window N
normalized = (AC + 1) / 2
```

v1 windows:

- 10
- 15
- 20
- 30
- 50

Interpretation:

- positive: momentum / persistence
- negative: mean reversion
- near 0: noise

### 3. ADX

```text
ADX normalized = ADX / 100
```

v1 windows:

- 10
- 14
- 20
- 30

Interpretation:

- high: directional market
- low: range

## Walk-Forward Methodology

The logic should follow the philosophy of the existing signal pipeline: out-of-sample validation, not free in-sample tuning.

### Training window

Within each training window:

1. compute the regime candidate value for every day
2. split the days into terciles
3. use:
   - top tercile = `trending`
   - bottom tercile = `ranging`
   - middle tercile = ambiguous zone
4. measure OOS performance by signal family during `trending` and `ranging` days
5. convert those Sharpes into regime-specific weights

Formula:

```text
weight[family][regime] =
  max(0, Sharpe[family][regime]) /
  sum(max(0, Sharpe[all_families][regime]))
```

If all Sharpes are negative in a regime:

- fall back to equal weights inside that regime

### Test window

Within each test window:

1. compute the current candidate value
2. compare it to the tercile bounds learned in training
3. produce:
   - `trending weights`
   - `ranging weights`
   - or a linear blend if the value is in the middle zone
4. recompute consensus using those regime-conditioned weights
5. compare performance against an equal-weighted consensus

## Survivor Logic

After aggregating across all folds:

1. compute average OOS improvement versus equal weight
2. keep only candidates with positive improvement
3. compute pairwise correlation among survivors
4. if two survivors are too correlated (`> 0.85`), keep the stronger one
5. the strongest remaining survivor becomes the active detector

## Why Measured OOS Instead of Hand-Tuned

The tempting shortcut would be to define something like:

- "in trend, use 60% SMA, 30% MACD, 10% RSI"

But that kind of free weighting is dangerous:

- it increases the system's degrees of freedom
- it opens the door to overfitting
- it makes the reasoning less auditable

Measuring the weights from actual OOS family behavior enforces a healthy constraint: the regime layer does not choose a persuasive story, it chooses an observed improvement.

## Outputs

The layer should produce:

- `regime_indicator_value`
- `regime_label`
- `regime_weights`
- `adjusted_consensus`
- `regime_active`
- `regime_improvement`
- `candidate_results`

## How Strategy Consumes This

Strategy does not interact with regime internals. Instead, it selects a **signal policy**:

- `consensus` — equal-weight across enabled families (v1 default)
- `regime_aware_consensus` — regime-conditioned weighting (this document)

The signal engine exposes the selected policy's output as a single score on the [-100, +100] scale. Strategy receives the score and builds trade geometry around it.

## Edge Cases

### No surviving candidate

If no candidate improves equal weight OOS:

- `regime_active = false`
- the signal falls back to equal-weight consensus
- this is functionally identical to the `consensus` policy

### Sparse data

If a symbol lacks enough history for some windows:

- those candidates become non-evaluable for that symbol
- no proxy should be invented

### Mid-zone ambiguity

The middle zone is not an error. It should produce a continuous blend, not a forced binary decision.

## Fallback

- zero survivor → equal-weight consensus
- unavailable candidate → ignore that candidate cleanly
- multi-stock basket → full detail on the focused stock plus a compact basket summary

## v1 Limits

- only one final active detector at a time
- user control limited to allowed detector families and allowed windows
- no meta-ensemble of several active regime detectors in parallel

## References

- Neely, Rapach, Tu, Zhou (2014), *Forecasting the Equity Risk Premium: The Role of Technical Indicators*, Management Science
- Hong & Stein (1999), *A Unified Theory of Underreaction, Momentum Trading, and Overreaction*, Journal of Finance
- Han, Yang, & Zhou (2013), *A New Anomaly: The Cross-Sectional Profitability of Technical Analysis*, JFQA
- Hamilton (1989), *A New Approach to the Economic Analysis of Nonstationary Time Series*, Econometrica
- Ang & Timmermann (2012), *Regime Changes and Financial Markets*, Annual Review of Financial Economics
- Kaufman (1995), *Trading Systems and Methods*
- Stein (2024), *Forecasting the Equity Premium with Frequency-Decomposed Technical Indicators*, IJF

## Implementation Notes (v0.1)

v0.1 implements a single detector: **Kaufman Efficiency Ratio** (window=20).

- Core logic: `core/quant_core/signal_engine/regime.py`
- Domain model: `RegimeResult` dataclass in `core/quant_core/signal_engine/domain.py`
- API endpoint: `POST /strategy/signal/regime-consensus` in `services/api/app/routers/strategy_signals.py`
- Frontend toggle: `technical-analysis-panel.tsx` — "Consensus pondere par regime" switch
- Tests: `core/tests/test_regime.py` (14 tests)

The implementation uses the same walk-forward windows as the main A→G pipeline (`HORIZON_PARAMS`). For each family, the top variant by reliability score is used as representative. Regime weighting is only activated when it beats equal-weight consensus OOS across all test folds.

## Cross-Links

- Signal pipeline: see [00-INDEX.md](./00-INDEX.md) for the A→G layers
- Strategy consumes signal policies: see [../strategy-layer/05-signal-selection-layer.md](../strategy-layer/05-signal-selection-layer.md)
