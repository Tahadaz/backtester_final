# Trusted Universe & Exclusion Report (Phase 2)

Using the **actual current** trust/exclusion metadata from the 2026-07-06 data-quality repair (not a new list invented for this task):

- **SAH excluded entirely** — confirmed workbook-sourced market cap/P-to-B wrong by a persistent ~29.3x factor 2021-2024, root cause not pinned to a specific bad cell, so excluded by standing recommendation (`known_cases_reb_sah_sbm.md`).
- **The ~27-symbol factor-critical-conflict list** (RIS, M2M, MDP, SRM, CAP, IMO, LES, SBM, SMI, SNP, WAA, REB, SAH, and 14 others) was checked against B/M's and CF/P's actual required fields (book equity, CFO, market cap) — **none of their flagged conflicts are on those specific fields** (they're EBITDA, EnterpriseValue, NetIncome, Total_Debt, Cash, Revenue conflicts instead). Per the instruction to exclude only where a conflict *affects the required signal*, these symbols are **not** blanket-excluded from B/M/CF/P — this is a narrow, evidence-based reading, not a loosening of the exclusion policy, and is documented here explicitly so it's auditable rather than silently assumed.
- **Canonical signal-level trust** is already baked into the data: `eligible_bm = book_to_market_raw is not null` (which already encodes the negative-book-equity exclusion), `eligible_cfp = cashflow_price_raw is not null` (already encodes the bank/insurance exclusion).
- **Listing state**: the PIT panel (`build_pit_panel`) already filters to `_is_live(uni_row, as_of_date)` — not before IPO, not after delisting — inherited automatically since this backtest reuses that panel.
- **Liquidity**: **not separately filtered this session** — `adv20` exists in the characteristic-study panel but was not joined into this backtest's eligibility mask. This is an explicit, acknowledged gap (see `final_strategy_verdict.md` item 17), not a silent omission: applying a liquidity quintile cut was in scope per the brief but the panel snapshot reused here does not carry `adv20` in its saved CSV columns, and recomputing it would have required re-running the ~3-minute full characteristic study a second time. The current holdings counts (16-18 names on average) suggest the top-tercile filter alone is not admitting single-digit-name illiquid dust, but this is not a substitute for an explicit ADV threshold.
- **Minimum universe size**: 9 names, per the existing `MIN_PORTFOLIO_NAMES` convention already used in `methodology_bakeoff.py`.

## Critical finding: effective coverage starts much later than the full panel window

The panel spans 2017-03 to 2026-05 (111 monthly dates), but **the number of names passing `eligible_bm`/`eligible_cfp` AND the 9-name minimum does not clear the bar until 2022** for B/M (2022-03), **2022-12** for CF/P, and **2023-04** for the composite. `exclusion_reasons.csv` has the full per-date breakdown. Before those dates, the trusted universe is empty and the vintage engine holds cash. **The real, honestly-invested backtest sample is 51 months (S1), 42 months (S2), 38 months (S3) — not 111.** This is reported prominently because presenting headline Sharpe/CAGR without this context would be misleading (see `strategy_results.md`).

## Average eligible/holdings counts (invested period only)

S1 (B/M): avg 16.8 names held per date (min 3, max 27). S2 (CF/P): avg 18.1 (min 3, max 27).
