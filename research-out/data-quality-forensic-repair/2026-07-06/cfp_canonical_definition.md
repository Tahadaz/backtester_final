# Canonical Cash-Flow-to-Price (CF/P) Definition (Phase 10)

## Definition (implemented, tested, applied)

```
CF/P = operating_cash_flow / market_cap,  set to None for financial-sector issuers (bank/insurance archetype)
```

- **Numerator**: `METRIC_ALIASES["cash_flow_ops"]` = first non-null of `(Operating_Cash_Flow, Cash_Flow_Operations, CFO)`. This is CFO, **not** free cash flow (a separate alias group, `free_cash_flow`, exists but is unused in this characteristic) and **not** TTM — it is the latest available annual statement figure, same PIT convention as book equity.
- **Negative CFO**: **kept, signed** (unlike book equity). A negative operating cash flow is a real, economically meaningful signal (operationally cash-burning), unlike negative book equity which changes the *regime* of what B/M measures. This is a deliberate, evidence-backed distinction, not an oversight — implemented via `_ratio_or_none` which only requires the denominator (market cap) to be positive.
- **Financial-firm applicability**: chosen policy is **(C) unavailable for financials** — implemented this session as `cashflow_price_raw = None` when `is_financial` (bank/insurance archetype). Rationale: banks'/insurers' reported operating cash flow is dominated by deposit-taking, policyholder float, and loan-book movements rather than the operating cash generation the CF/P characteristic is meant to capture (Lakonishok-Shleifer-Vishny cash-flow yield), so a numerically large or small CFO/MarketCap ratio for a bank does not carry the same economic meaning as for a non-financial firm. This decision was made from accounting logic before any IC results were examined for this specific change, per the brief's governance rule.
- **Known gap**: the `is_financial` flag used for this exclusion is bank/insurance only (`FINANCIAL_ARCHETYPES`), not the broader leasing/financing definition used elsewhere in the codebase (`FINANCIAL_SECTOR_TOKENS`) — see `sector_accounting_applicability.md`. Leasing/financing names (MAB, EQD, SLF, MLE) are NOT excluded from CF/P this session; flagged as a follow-on fix, not silently claimed as done.
- **Market-cap timing / stale-observation / conflict behavior / unavailable-data behavior**: identical to B/M's policy (see `bm_canonical_definition.md`) — same PIT panel, same resolver, same `None`-on-missing convention.

## Where this is applied

- `characteristic_study.py:266-271` (fixed this session — added the `is_financial` exclusion)
- `methodology_bakeoff.py` does **not** compute a standalone CF/P signal at all (only `book_to_market`, `profitability`, `investment_conservative`, and the fundamental-momentum change signals) — so there was no second implementation to reconcile for CF/P, unlike B/M.
- `final_model_validation.py` inherits this via `characteristic_study.py`'s output panel.

## Test coverage

`core/tests/test_characteristic_study.py::test_cashflow_price_excluded_for_financial_sector_issuers` — passing.

## What is still open

- Extend the exclusion to leasing/financing companies (broader `is_financial` definition).
- No TTM (trailing-twelve-month) variant was built or compared against the annual-only convention used here — Phase 10 asked whether CF/P should use CFO vs TTM; the decision made is annual-only (matching the existing PIT panel's annual-statement granularity), not independently validated against a TTM alternative this session.
