# Analytics Page — Overview

## Purpose

The analytics page answers one core question: **does a signal have genuine predictive edge over the MASI universe?**

It does this by replaying historical signal scores bar-by-bar and measuring whether those scores actually predicted forward price movements. This is not a backtest — there are no position sizes, no P&L, no transaction costs. It is a pure statistical evaluation of signal quality.

---

## Page Structure

The `/analytics` route has three top-level tabs:

| Tab | Content |
|---|---|
| **TA** | Technical analysis signal evaluation — this document covers this tab |
| **Macro** | Macro-factor relevance (covered in `docs/factor-layer/`) |
| **Factors** | Phase 1 factor signal evaluation (covered in `docs/factor-layer/`) |

### TA Tab — Two Subtabs

**Top signaux** — The leaderboard. Ranks every `(symbol × source)` pair by mean Information Coefficient across the selected engine horizon's forward horizons. Answers: *which signals are most predictive across the entire universe?*

**Par action** — The per-stock drill-down. For a selected symbol, source, and horizon, shows the full bucket × forward-horizon matrix. Answers: *for this specific symbol, what does the signal predict, and how reliably?*

---

## User Workflow

```
1. Open /analytics → TA tab → Top signaux
2. Select engine horizon: short | medium | long
3. See leaderboard sorted by mean IC
   → Positive IC (green) = signal predicts correctly
   → Negative IC (red) = signal is inverted
   → Check N — rows with low N are unreliable
4. Click a row (or switch to Par action tab)
5. Select: symbol, source (engine_legacy | engine_expanded | wfo), horizon
6. See the bucket × forward-horizon matrix
   → Each cell = (mean expected return, hit rate, N)
   → Confidence intervals on both
7. Optionally: select a subset of categories (tendance, momentum, oscillation, volume)
   to see how the matrix changes when categories are included/excluded
8. Check the category-combinations panel
   → Ranked by monotonicity score Δ
   → Identifies which category subset gives the best signal separation
```

---

## Signal Sources

Three sources are supported, each producing a continuous per-bar score in `[−100, +100]`:

| Source | Description |
|---|---|
| `engine_legacy` | Signal engine with the legacy category/family mapping |
| `engine_expanded` | Signal engine with the expanded category/family mapping (more families) |
| `wfo` | Walk-forward optimization — OOS-selected representatives per category |

All three are stored in `signal_score_history` and evaluated identically by the analytics layer.

---

## Engine Horizons vs. Forward Horizons

These are two different concepts that are easy to confuse:

- **Engine horizon** (`short` / `medium` / `long`): the time horizon for which the signal was *optimized and selected* during the signal engine or WFO run. A signal optimized for `short` was selected to predict short-term moves.

- **Forward horizon** (1, 2, 3, 5, 10, 21, … trading days): the look-ahead window used in the *analytics evaluation*. The matrix shows mean return over the next N days if you followed this signal today.

The leaderboard groups forward horizons by engine horizon:

| Engine horizon | Forward horizons evaluated |
|---|---|
| short | 1, 2, 3, 4, 5 days |
| medium | 6, 10, 15, 21 days |
| long | 30, 60, 120, 200 days |

The per-stock matrix always evaluates all 13 forward horizons: `[1, 2, 3, 4, 5, 6, 10, 15, 21, 30, 60, 120, 200]`.

---

## Four Signal Categories

Each signal source decomposes the composite score into 4 categories:

| Category | What it captures |
|---|---|
| `tendance` | Trend-following indicators (SMA crossovers, momentum direction) |
| `momentum` | Rate-of-change, MACD-style indicators |
| `oscillation` | Mean-reversion oscillators (RSI, Bollinger, stochastic) |
| `volume` | Volume-based indicators (OBV, volume ratio, VWAP) |

The composite score is the mean of the 4 category scores. The analytics page lets users evaluate any subset of categories to identify which ones drive predictive ability.
