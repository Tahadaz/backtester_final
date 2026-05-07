# 01 — The Four-Station Architecture

## The Meta-Strategy Paradigm

This platform follows López de Prado's meta-strategy paradigm — a production-line model where investment strategies are built through specialized, sequential stations rather than by individual researchers working in silos.

> *"Amateurs develop individual strategies, believing that there is such a thing as a magical formula for riches. In contrast, professionals develop methods to mass-produce strategies. The money is not in making a car, it is in making a car factory."*
> — López de Prado (2018), *Advances in Financial Machine Learning*, Ch.1, p.11

De Prado identifies five stations in a quantitative investment production line (Ch.1, §1.3.1):

1. **Data Curators** — "collecting, cleaning, indexing, storing, adjusting, and delivering all data to the production chain" (p.7)
2. **Feature Analysts** — "transforming raw data into informative signals" (p.7)
3. **Strategists** — "informative features are transformed into actual investment algorithms" (p.7)
4. **Backtesting** — evaluating whether strategies work on unseen data
5. **Portfolio Oversight** — allocation, monitoring, decommissioning

Our platform implements the first four as distinct pages in a web application. Portfolio oversight is a future concern.

---

## Our Four Stations

| Station | Page | Route | Mandate |
|---------|------|-------|---------|
| Data Curators | **Données** | `/data` | Manage market data: ingestion, storage, freshness, quality |
| Feature Analysts | **Signaux** | `/signals` | Discover which indicators carry predictive power via OOS pipeline |
| Strategists | **Stratégie** | `/strategy` | Define trading rules and parameters using signal findings |
| Backtesting | **Backtest** | `/backtest` | Evaluate strategies via Walk-Forward Analysis, produce verdict |

### Station 1 — Données (Data)

The data page is the **control center** for the entire data pipeline. Every backtest and every signal computation depends on data managed here.

**Produces:** Canonical OHLCV parquet files at `market_data_store/{symbol}/1D`, stock catalog, freshness metadata, holiday calendar.

**Does NOT:** Compute indicators, generate signals, define strategies, or run backtests.

### Station 2 — Signaux (Signals)

The signals page transforms raw OHLCV into evaluated, filtered, ensembled signals with measurable predictive power.

> *"[Feature analysts] collect and catalogue libraries of findings that can be useful to a multiplicity of stations. [...] A common error is to believe that feature analysts develop strategies. Instead, feature analysts collect and catalogue libraries of findings."*
> — López de Prado (2018), Ch.1, p.7

This is the key distinction: **a signal is a finding, not a strategy.** The signal page discovers that SMA-20 has predictive power on IAM stock at medium horizon, with reliability 0.72. It does not decide what to do with that finding.

**Produces:** Ensemble scores per (family, symbol, horizon), surviving representatives with reliability weights, variant detail with OOS windows, continuous indicator scores for exploration.

**Does NOT:** Define entry/exit rules, set position sizes, configure risk parameters, or run backtests.

### Station 3 — Stratégie (Strategy)

The strategy page transforms signal findings into actionable trading configurations — per-stock specifications defining which indicators to use, when to enter, when to exit, and how much to risk.

**Produces:** SavedStrategy objects with portfolio config + per-stock strategy configs + WFO parameter manifest.

**Does NOT:** Run optimization, compute WFE, produce Kelly sizing, or validate strategies against unseen data.

### Station 4 — Backtest

The backtest page evaluates fully defined strategies through Walk-Forward Analysis.

> *"Walk-Forward Analysis is the closest possible simulation of the way in which an optimizable trading strategy is typically used in real time."*
> — Pardo (2008), *The Evaluation and Optimization of Trading Strategies*, Ch.11, p.237

> *"Research has clearly demonstrated that robust trading strategies have WFEs greater than 50 or 60 percent and in the case of extremely robust strategies, even higher."*
> — Pardo (2008), Ch.11, p.239

**Produces:** WFE verdict, per-window IS/OOS results, optimization profiles, Kelly sizing from OOS trades, Monte Carlo p-value, Deflated Sharpe Ratio, test period equity curve.

**Does NOT:** Define strategies, modify strategy parameters automatically, or perform signal research.

---

## Why Separate Pages

### Cognitive separation prevents overfitting

> *"Backtesting is not a research tool. Feature importance is."*
> — López de Prado (2018), Ch.8, Snippet 8.1

If signal research and backtesting happen on the same page, the user unconsciously optimizes the research to produce good backtests — this is the multiple testing problem. Separating them forces a one-way flow: discover → configure → evaluate.

### Each station has exactly one responsibility

Mixing concerns creates ambiguity about what the page is for. When a page does one thing, its success criterion is clear:

| Station | Success criterion |
|---------|------------------|
| Data | Is the data fresh, complete, and correct? |
| Signal | Do the indicators carry OOS predictive power? |
| Strategy | Is the trading plan fully and explicitly specified? |
| Backtest | Does optimization reliably transfer to unseen data? |

### The stations mirror professional workflow

De Prado's model is not theoretical — it describes how successful quantitative firms actually operate. Each station has specialists who understand its domain deeply. In our platform, the "specialist" is the user wearing a different hat on each page.

---

## Unidirectional Data Flow

```
Data ──OHLCV──→ Signal ──findings──→ Strategy ──config──→ Backtest ──verdict──→
```

Data flows forward through the stations. There is no backward automatic flow:

- Backtest results **do not** auto-modify the strategy. The user reviews results and chooses whether to revise.
- Strategy configuration **does not** change signal research. The signal engine runs independently.
- Signal findings **do not** modify market data. The data layer is upstream of everything.

The only backward flow is **user-initiated**: reviewing backtest results and deciding to revise the strategy, or noticing signal weakness and checking data freshness. These are human decisions, not system automation.

---

## What This Architecture Prevents

### 1. Overfitting via iterative backtesting

> *"Even if your backtest is flawless, it is probably wrong. Why? Because only an expert can produce a flawless backtest. Becoming an expert means that you have run tens of thousands of backtests over the years. In conclusion, this is not the first backtest you produce, so we need to account for the possibility [of selection bias]."*
> — López de Prado (2018), Ch.11, p.152–153

By separating signal research from backtesting, we prevent the cycle of "tweak signal → backtest → tweak again until it looks good." The signal engine's 7-layer pipeline produces findings independently of any backtest.

### 2. Strategy-data snooping

The strategy page consumes signal findings but cannot see raw backtest results until the strategy is handed off. This prevents designing rules to fit historical equity curves.

### 3. Conflation of research and execution

> *"A strategy is merely the experiment designed to test the validity of [a] theory."*
> — López de Prado (2018), Ch.1, p.7

The signal page produces the theory (indicators have predictive power). The strategy page designs the experiment (trading rules). The backtest page runs the experiment. Collapsing these into one page conflates discovery with validation.

---

## References

- López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley. Ch.1 (Meta-Strategy Paradigm), Ch.7 (Cross-Validation), Ch.8 (Feature Importance), Ch.11 (Dangers of Backtesting).
- Pardo, R. (2008). *The Evaluation and Optimization of Trading Strategies*. 2nd Edition. Wiley. Ch.11 (Walk-Forward Analysis).
- Elder, A. (1993). *Trading for a Living*. Wiley. (Indicator category classification.)
