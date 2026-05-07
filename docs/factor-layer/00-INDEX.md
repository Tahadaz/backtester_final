# Factor Layer — Document Index

**Station mandate**: Rigorous OOS evaluation of existing TA signals + macro-factor research layer (VIX/SP500/Brent/DXY/EURUSD/US10Y). Produces defensible, FDR-controlled evidence of whether macro state improves signal performance on MASI equities.

**Status**: Phase 0 complete ✅ (stats library + macro ingestion + analytics surface). Phase 1 complete ✅ (pre-registered factor strategies + evaluation harness). Phase 2 (conditional TA × macro composition) deferred pending Phase 1 results.

---

## Document Map

| # | Document | Status | Description |
|---|---|---|---|
| 01 | [01-overview-and-research-question.md](01-overview-and-research-question.md) | ✅ | Research question, null hypothesis, scope, what this layer does and does not do |
| 02 | [02-literature-and-methodology.md](02-literature-and-methodology.md) | ✅ | Full citation-backed methodology (Harvey/Liu/Zhu, Bailey/LdP, Grinold/Kahn, BH-FDR, NW, Bekaert/Harvey) |
| 03 | [03-universe-and-factor-selection.md](03-universe-and-factor-selection.md) | pending | MASI shortlist rationale, auto-expand ADV rule, factor universe with per-factor economic channel |
| 04 | [04-calendar-alignment.md](04-calendar-alignment.md) | ✅ | Session-close times UTC, lag rules (precede_open/previous_close), look-ahead avoidance, adversarial cases (DST, Eid, holidays) |
| 05 | [05-statistical-battery.md](05-statistical-battery.md) | ✅ | Formal definition of every metric: IC (Newey-West), hit rate (Wilson CI), DSR, PSR, BH-FDR, Harvey-Liu haircut, Sharpe/Sortino/MaxDD/Calmar |
| 06 | [06-descriptive-relevance-study.md](06-descriptive-relevance-study.md) | ✅ | Phase 0.9 methodology: Spearman IC + Newey-West t-stat per (factor, stock), contemporaneous alignment, channel-gate validation |
| 07 | [07-phase1-factor-strategies.md](07-phase1-factor-strategies.md) | ✅ | Phase 1 pure factor-only rule specs (6 signals), parameters, academic citations, channel-filter gating, pre-registration lock |
| 08 | [08-api-data-flow-and-frontend-contracts.md](08-api-data-flow-and-frontend-contracts.md) | ✅ | Every /analytics/* route, Pydantic + Zod schemas, cache strategy, inline IC-chip insertion, error handling |
| 09 | [09-implementation-roadmap.md](09-implementation-roadmap.md) | pending | Step-by-step implementation order with acceptance criteria per step |
| 10 | [10-methodology-and-sources.md](10-methodology-and-sources.md) | ✅ | Phase 1 deliverable-grade summary: research question, methodology (alignment, FDR, cost model), sources, evaluation framework, horizon analysis |
| 11 | [11-pre-registration.md](11-pre-registration.md) | ✅ | Phase 1 pre-registration protocol: integrity rationale, violation definitions, proof of no look-ahead, Phase 2 scoping |
| 12 | [12-phase2-scoping-note.md](12-phase2-scoping-note.md) | ✅ | Phase 2 scoping (conditional TA × factor composition), evidence gates, failure modes, preliminary composition design |
| 17 | [17-factor-selection-runtime-contract.md](17-factor-selection-runtime-contract.md) | ✅ | Per-stock, per-horizon Factor x TA selection schema, monitoring, invalidation, and UI contract |

---

## Cross-layer Dependencies

- **Data layer** → `market_data_store.asset_class = 'factor'` stores macro series; `build_market_store_object_key` unchanged.
- **Signal-generation layer** → `FamilyCombinedSignal` / `VariantCurrentSignal` interfaces feed into `evaluate_signal`; regime paths in `signal_engine/regime.py` and `decision/regime.py` are **untouched**.
- **Backtest layer** → `docs/backtest-layer/08-statistical-validation.md` cross-references `05-statistical-battery.md` as canonical source.
- **Dashboard layer** → New `/analytics` route; inline IC chips added to existing signal pages.
- **Analytics layer** → `docs/analytics-layer/` covers the TA analytics tab (bucket matrix, leaderboard, IC methodology). Shared statistical citations are consolidated in `docs/analytics-layer/06-methodology-and-sources.md`.

## What This Layer Does NOT Do

- Modify `signal_engine/ensemble.py` weighting — Phase 2 territory.
- Change any existing regime path — left intact.
- Add fundamental data.
- Live trading integration.
- Phase 2 conditional TA × factor composition (scoped separately after Phase 0–1 results).
