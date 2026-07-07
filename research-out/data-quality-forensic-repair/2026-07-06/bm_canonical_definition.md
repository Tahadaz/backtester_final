# Canonical Book-to-Market (B/M) Definition (Phase 9)

## Definition (implemented, tested, applied consistently)

```
B/M = book_equity / market_cap
```

- **Numerator**: `book_equity`, resolved via `METRIC_ALIASES["book_equity"]` = first non-null of `(Total_Equity, Shareholders_Equity, Clean_Capitaux_propres, Capitaux_propres, Common_Equity)`. Consolidated-vs-standalone preference is implicit in ingestion order, not independently re-verified this session (flagged unresolved, same caveat as `field_mapping_audit.md`'s net_income finding).
- **Negative book equity**: **excluded** (`None`, not signed). This is the fix applied this session in `characteristic_study.py:264` to match `methodology_bakeoff.py:190`'s pre-existing behavior and Fama-French HML convention. Confirmed 28 real negative-book-equity rows exist (SNA: 11, STR: 8, MDP: 5, IBC: 4) — these are now consistently excluded from B/M in both implementations.
- **Market-cap timing**: PIT — `MarketCap_Calc`/`Market_Cap` as of the panel's `as_of_date`, or `close × Shares_Outstanding` if not directly stored. Uses the *contemporaneous* market cap at the observation date, not a statement-vintage stored value.
- **Annual vs interim hierarchy**: annual statement values only in the current characteristic computation (`fundamental_annual_metric`); no interim/quarterly B/M variant is computed in `characteristic_study.py` (quarterly data exists in `fundamental_period_metric` but isn't wired into this specific ratio).
- **Latest-available PIT rule**: governed by `panel.py:_latest_metric_map` (see `deterministic_resolution_policy.md`) — the most recent `availability_date`-eligible book-equity value as of each monthly panel date.
- **Financial-sector treatment**: **no exclusion** — B/M is computed uniformly for banks/insurers, unlike CF/P. This is intentional: book value is a standard, meaningful metric for financial firms (indeed B/M for banks is a well-established value signal in academic literature), unlike operating cash flow.
- **Stale-observation policy**: none beyond the existing 90-day PIT fallback (see `pit_fallback_audit.md`) — no additional staleness cutoff imposed on top of the panel's own availability-date logic.
- **Conflict behavior**: resolved via the panel's deterministic resolver (`deterministic_resolution_policy.md`); unresolved cross-source conflicts for ~20 symbols (see `duplicate_conflicts.md`) remain a known residual risk not specific to B/M.
- **Unavailable-data behavior**: `None` (row excluded from that characteristic's cross-section for that date) — never imputed or defaulted to zero.

## Where this is applied

- `characteristic_study.py:264` (fixed this session)
- `methodology_bakeoff.py:190` (already correct, unchanged)
- `final_model_validation.py` (consumes `characteristic_study.py`'s output panel directly — inherits the fix automatically once `characteristic_study.py` is re-run, done in Workstream 3 below)

## Test coverage

`core/tests/test_characteristic_study.py::test_negative_book_equity_excludes_book_to_market_not_signs_it` — passing.

## What is still open

- The book-equity numerator's consolidated-vs-standalone and RNPG-vs-total-net-income-style ambiguity (documented in `field_mapping_audit.md`) has not been resolved for book equity specifically — the `book_equity` alias list does not obviously mix group-share vs consolidated the way `net_income` does, but this was not independently re-verified line-by-line for every alias this session.
- No interim/quarterly B/M variant exists to test PIT-freshness sensitivity.
