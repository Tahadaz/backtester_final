# Codex Brief 3 — Commodities vertical

**Program:** `docs/cross-asset-product/00-program-plan.md` — §4 guardrails, §5 reuse, §6 invariants binding.
**Prerequisite:** Briefs 1 and 2 merged and green.
**Base spec:** `docs/ai/commodity-systematic-strategies-plan.md` — implement its MVP (§1 items 1–5) except where §2 below overrides.
**Scope:** contract-aware return construction and curve carry, running through the **Brief 1 engine unchanged**. Fixture + canonical CSV import only.
**Ship gate:** a commodity run completes through the identical engine and is labelled non-tradable from its `warnings`.

## 1. Guardrails (binding)

Program §4 verbatim. Plus, specific to this brief:

- **No new backtester and no new run ledger.** The base spec says this too (§2.4): use `Run` with `run_type="cross_asset_strategy"`, not a `commodity_run` table. The engine is `core/quant_core/cross_asset/backtest.py` from Brief 1.
- **No new frontend components.** The commodity tab lights up by adding `"commodity"` handling to the Brief 2 components. If you are creating a component file, you have taken a wrong turn.
- Do not explore the repo; do not read `graphify-out/*`.

## 2. Overrides against the base plan

**O1 — Data policy is fixture + import only** (program D4). Do **not** attempt free per-contract sourcing (Stooq or otherwise); it is an open-ended time sink and would stall the program. The two doors are:
1. `core/tests/fixtures/cross_asset/commodity_contracts_sample.csv` (created in Brief 1) — tests and demo.
2. The canonical CSV importer from Brief 1 — `instrument_id, date, field, value, currency, contract_expiry, source`, fields `settle|open|high|low|close|volume|open_interest|rate|forward_points`.

Existing yfinance continuous proxies (`BZ=F`, `GC=F` — already registered, `core/quant_core/macro.py:99,107`) may power the **curve explorer and exploratory views only**. They must never produce a result presented as tradable.

**O2 — Every proxy-backed run carries a `warnings` entry** that the Brief 2 banner renders. The run's `data_source` in the transparency envelope says `"proxy"` or `"fixture"`, never `"market"`.

**O3 — Scope the MVP to the base plan's five items.** Nothing beyond: contract metadata + quality gates + delivery-safe chain; curve explorer; nominal curve carry (front/second and front/fourth); preliminary cross-sectional long-short backtest with explicit legs; proxy warnings and upgrade path.

## 3. The financial core

This is where a commodity backtest is either valid or worthless.

**Chain construction must be delivery-safe.** Build the held-contract sequence from contract metadata (expiry, first notice) and the roll rule — `n_days_before_expiry | first_notice | volume_crossover`. A chain that would hold a contract into first notice is a bug, not a warning.

**P&L is reconstructed from contracts actually held and rolled**, with the legs separately inspectable:
```
excess = price_return(held contract) + roll_return + collateral_return
roll_return      = from the front→next price ratio on the roll date, per roll_rule
collateral_return = cash_rate · τ
```
Then converted to base ccy (USD) via same-day FX, timestamped.

**Back-adjusted series are a display aid only.** Brief 1's `test_ca_returns` already asserts that roll-return reconstruction equals the back-adjusted price return minus collateral — keep that test green; it is the guard against a back-adjusted chart quietly manufacturing returns.

**Curve carry is a forecast feature, not a return.** Nominal carry = front/next − 1, annualized (and front/fourth as the second definition). It ranks instruments; it never stands in for realized P&L.

## 4. Files to create

```
core/quant_core/cross_asset/futures_chain.py     # delivery-safe chain construction + roll dates
core/quant_core/cross_asset/curve.py             # curve snapshots, nominal carry (front/second, front/fourth)
services/api/app/services/cross_asset/commodity_data.py   # fixture + import assembly, proxy tier tagging
core/tests/test_ca_futures_chain.py
core/tests/test_ca_curve.py
```

## 5. Files you may modify (nothing else)

- `core/quant_core/cross_asset/returns.py` — `futures_excess` uses `futures_chain` for the held sequence. The dispatch signature does not change.
- `core/quant_core/cross_asset/dataquality.py` — add contract-metadata completeness and roll-jump checks.
- `services/api/app/routers/cross_asset_research.py` — curve-explorer endpoint; commodity strategy support.
- `services/api/app/schemas/cross_asset_research.py` — matching schemas.
- The Brief 2 frontend components — handle `"commodity"`, including the curve explorer view.
- `frontend/lib/api.ts` — schemas/fetchers for the curve endpoint.

## 6. Tests

- `test_ca_futures_chain`: chain never holds past first notice; roll dates match each `roll_rule`; a contract gap produces a warning and never a silent splice.
- `test_ca_curve`: carry definitions on a hand-built curve; an inverted curve gives negative carry with the right sign.
- Extend `test_ca_dataquality`: missing contract metadata blocks the backtest; a roll jump is flagged.
- Extend the router test: a commodity run completes and its envelope `data_source` is `"fixture"` with a non-tradable warning present.

## 7. Acceptance

1. A commodity run completes through the **identical** Brief 1 engine — no second backtester, no second ledger.
2. Legs (outright, roll, collateral, FX, cost) are separately inspectable in the methodology chain.
3. No continuous-ticker return is presented anywhere as tradable; the banner renders from `warnings`.
4. Zero new frontend component files.
5. No file outside §4/§5 created or modified; full suite green.
