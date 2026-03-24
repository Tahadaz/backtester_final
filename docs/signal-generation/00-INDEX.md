# Signal Generation Layer — Architecture Documentation

> **Station mandate:** Transform raw market data into informative signals with measurable predictive power, using a rigorous out-of-sample pipeline that eliminates overfitting, redundancy, and data-snooping bias. This station produces **evaluated, filtered, ensembled signals** — not investment strategies.

*The fundamental insight driving this architecture: a signal that "works" in-sample is worth nothing. Only out-of-sample, cost-adjusted, robustness-filtered signals carry genuine information. This is not a convention — it is a statistical necessity (White 2000, Harvey et al. 2016, Bailey et al. 2014).*

---

## Documents

| # | File | Scope |
|---|------|-------|
| 01 | [philosophy.md](./01-philosophy.md) | Why signals ≠ strategies, multiple testing problem, information theory, the case for OOS ensemble |
| 02 | [candidate-universe.md](./02-candidate-universe.md) | Layer A — structured candidate generation: 4 families × 30 variants, archetype design, horizon scaling |
| 03 | [oos-evaluation.md](./03-oos-evaluation.md) | Layer B — walk-forward OOS windows, signal dispatch, cost model, return computation, cooldown mechanism |
| 04 | [robustness-scoring.md](./04-robustness-scoring.md) | Layer C — 4-component reliability score, viability gate, component weights and their rationale |
| 05 | [survivor-filtering.md](./05-survivor-filtering.md) | Layer D — competitive percentile filter, absolute floor, two-stage elimination |
| 06 | [redundancy-reduction.md](./06-redundancy-reduction.md) | Layer E — greedy signal-correlation clustering, Pearson threshold, diversity preservation |
| 07 | [current-signal-and-ensemble.md](./07-current-signal-and-ensemble.md) | Layers F+G — current-bar signal dispatch, reliability-weighted ensemble, family-specific labels |
| 08 | [variant-detail.md](./08-variant-detail.md) | Trade register, execution model, cost-adjusted carry price, per-window plots, performance metrics |
| 09 | [api-and-frontend.md](./09-api-and-frontend.md) | API endpoints, Pydantic schemas, frontend 3-level drill-down, caching, batch scores |
| 10 | [methodology-and-sources.md](./10-methodology-and-sources.md) | Academic justification for every design choice, full bibliography, honest limitations |

---

## The 7-Layer Pipeline (A → G)

The signal engine processes each (family, symbol, horizon) tuple through seven sequential layers:

```
Layer A  CANDIDATE GENERATION     30 variants per family (structured, not random)
  ↓
Layer B  OOS EVALUATION           Walk-forward windows, cost-adjusted returns
  ↓
Layer C  ROBUSTNESS SCORING       4-component reliability score [0, 1]
  ↓
Layer D  SURVIVOR FILTERING       Viability gate + competitive percentile
  ↓
Layer E  REDUNDANCY REDUCTION     Greedy correlation clustering (|r| < 0.85)
  ↓
Layer F  CURRENT SIGNAL           Live signal from each representative
  ↓
Layer G  ENSEMBLE                 Reliability-weighted combination → score [-100, +100]
```

**Each layer has a clear statistical justification:**

| Layer | Problem it solves | Reference |
|-------|-------------------|-----------|
| A | Structured search prevents data-mining (vs random parameter search) | López de Prado (2018) Ch. 8 |
| B | OOS evaluation prevents in-sample overfitting | Pardo (2008), Bailey & López de Prado (2012) |
| C | Multi-metric scoring prevents single-metric gaming | Harvey et al. (2016) |
| D | Survival gate removes noise variants | White (2000) |
| E | Redundancy filtering prevents correlated double-counting | López de Prado (2020) Ch. 6 |
| F | Signal dispatch uses same causal indicators as evaluation | Murphy (1999), Elder (1993) |
| G | Ensemble reduces variance and improves robustness | Breiman (1996), Dietterich (2000) |

---

## The 4 Indicator Families

| Family | Category | Signal Type | Archetype | Academic Foundation |
|--------|----------|-------------|-----------|---------------------|
| **SMA** | Tendance | Trend | `price_vs_sma` | Murphy (1999) — price/moving-average crossover as trend proxy |
| **RSI** | Oscillation | Oscillator | `rsi_level` | Wilder (1978) — relative strength as mean-reversion signal |
| **MACD** | Tendance | Trend | `macd_cross` | Appel (2005) — EMA convergence/divergence as momentum |
| **OBV** | Volume | Volume | `obv_trend` | Granville (1963) — cumulative volume as confirmation |

Each family generates exactly **30 candidates** per horizon — a deliberate choice that balances search breadth against multiple-testing cost.

---

## What This Station Does NOT Do

- **Portfolio construction** — how much capital to allocate to each signal
- **Execution** — order routing, slippage modeling, market microstructure
- **Risk management** — position limits, stop losses, drawdown controls
- **Strategy selection** — which signals to trade (that's the decision layer)

A signal is a **finding** — a measured relationship between an indicator and future returns, validated out-of-sample. A strategy is a **system** that acts on findings. This station produces findings.

---

## Key Design Principles

1. **Out-of-sample or it didn't happen** — No in-sample metric is reported or used for filtering. Every number the user sees comes from test windows the model never trained on.

2. **Parsimony over complexity** — 4 families, 1 archetype each, 30 parameter points. No neural networks, no feature engineering, no kitchen-sink approaches. Each indicator has decades of practitioner literature and a clear economic interpretation.

3. **Cost-adjusted from the start** — Transaction costs (configurable, default 10 bps) are deducted at every position change. A signal that trades too frequently is penalized automatically.

4. **Ensemble over selection** — Rather than picking "the best" variant (which is a form of overfitting), the engine combines all surviving representatives via reliability-weighted averaging.

5. **Transparency** — Every stage of the pipeline is visible: the user can see all 30 candidates, their OOS windows, their reliability decomposition, why each was kept or eliminated, and the final ensemble weights.

---

## Key References

- López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley.
- López de Prado, M. (2020). *Machine Learning for Asset Managers*. Cambridge.
- Bailey, D.H., Borwein, J.M., López de Prado, M., Zhu, Q.J. (2014). "Pseudo-Mathematics and Financial Charlatanism." *Notices of the AMS*.
- Harvey, C.R., Liu, Y., Zhu, H. (2016). "... and the Cross-Section of Expected Returns." *Review of Financial Studies*.
- White, H. (2000). "A Reality Check for Data Snooping." *Econometrica*.
- Pardo, R. (2008). *The Evaluation and Optimization of Trading Strategies*. Wiley.
- Murphy, J.J. (1999). *Technical Analysis of the Financial Markets*. NYIF.
- Elder, A. (1993). *Trading for a Living*. Wiley.
- Wilder, J.W. (1978). *New Concepts in Technical Trading Systems*. Trend Research.
- Appel, G. (2005). *Technical Analysis: Power Tools for Active Investors*. FT Press.
- Granville, J. (1963). *Granville's New Key to Stock Market Profits*. Prentice-Hall.
- Chan, E. (2008). *Quantitative Trading*. Wiley.
- Breiman, L. (1996). "Bagging Predictors." *Machine Learning*.
- Dietterich, T. (2000). "Ensemble Methods in Machine Learning." *MCS 2000*.
