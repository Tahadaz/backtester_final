# Signal Generation Layer — Architecture Documentation

> **Station mandate:** Transform raw market data into informative signals with measurable predictive power over financial variables. This station does not produce investment strategies — it produces a **catalogued library of findings** (features, signals, indicators) that downstream stations (portfolio construction, execution, risk management) consume.

*Inspired by Marcos López de Prado, "Advances in Financial Machine Learning" (2018), Chapter 1 — the signal generation station is the factory floor where raw data becomes information.*

---

## Documents

| # | File | Scope |
|---|------|-------|
| 01 | [philosophy.md](./01-philosophy.md) | Why signals are not strategies, information-theoretic foundations, research principles |
| 02 | [indicator-catalog.md](./02-indicator-catalog.md) | Every indicator: mathematical definition, implementation, parameters, statistical properties |
| 03 | [strategy-adapters.md](./03-strategy-adapters.md) | All 8 strategy adapters: signal rules, parameter spaces, warmup, edge cases |
| 04 | [signal-semantics.md](./04-signal-semantics.md) | Signal frame contract, intent vs execution, NaN policy, multi-symbol alignment |
| 05 | [indicator-bank.md](./05-indicator-bank.md) | Pre-computation architecture, BankRequest, caching, the optimization fast path |
| 06 | [optimization-engine.md](./06-optimization-engine.md) | Parameter search, trial evaluation, ranking, deduplication, timing |
| 07 | [walk-forward-validation.md](./07-walk-forward-validation.md) | OOS validation, WFO windows, chronology-respecting evaluation, overfitting control |
| 08 | [candidate-universe.md](./08-candidate-universe.md) | Structured archetype design, parameter neighborhoods, horizon scaling |
| 09 | [robustness-and-filtering.md](./09-robustness-and-filtering.md) | Survival gates, redundancy clustering, ensemble weighting (planned layers) |
| 10 | [prompt-context.md](./10-prompt-context.md) | Copy-paste context blocks for LLM-assisted signal development |

---

## The Signal Generation Station

This station is responsible for:

1. **Feature extraction** — Computing technical indicators (SMA, RSI, MACD, OBV, etc.) from raw OHLCV
2. **Signal generation** — Applying decision rules to features → directional intent (+1/0/-1)
3. **Signal cataloguing** — Organizing signals by family, archetype, and parameter neighborhood
4. **Signal validation** — OOS evaluation to measure genuine predictive power vs overfitting
5. **Signal filtering** — Removing redundant, unreliable, or economically insignificant signals
6. **Signal ensembling** — Combining surviving signals into consensus views

What this station does **NOT** do:
- Portfolio construction (how much to buy)
- Execution (when/how to fill orders)
- Risk management (position limits, stop losses)
- Strategy selection (which signals to trade)

These are downstream responsibilities. A signal is a **finding**, not a **strategy**.

---

## Key References

- López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley. — Chapters 2–9 (features), 17–19 (backtesting pitfalls)
- López de Prado, M. (2020). *Machine Learning for Asset Managers*. Cambridge. — Chapter 6 (feature importance)
- Bailey, D.H., Borwein, J.M., López de Prado, M., Zhu, Q.J. (2014). "Pseudo-Mathematics and Financial Charlatanism." *Notices of the AMS*. — Why multiple testing correction matters
- Harvey, C.R., Liu, Y., Zhu, H. (2016). "... and the Cross-Section of Expected Returns." *Review of Financial Studies*. — 316 factors, most are false discoveries
- White, H. (2000). "A Reality Check for Data Snooping." *Econometrica*. — Bootstrap tests for strategy evaluation
