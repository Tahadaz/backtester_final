# Build Track — Three Builds, In Order

Builds exist here to *teach market content* and to produce interview artifacts.
Notebook-grade output beats frontend polish; stop any build the moment it stops
teaching. Existing specs are reused — do not re-plan them.

## Build 1 (weeks 1–2): Fixed-income calculator — UN-SHELVED as a learning build

**Spec:** `docs/ai/offshore-lab-phase1-fixed-income.md` +
`docs/offshore-lab/00-response.md` §5–8. It was shelved because the desk has
Bloomberg — correct for desk tooling, irrelevant for prep: writing day-count,
accrued, YTM, duration/convexity/DV01 code yourself is the fastest way to make
Block 2 of the syllabus permanent.

**Scope discipline:** `core/quant_core/fixed_income/` (daycount, cashflows,
pricing, riskmeasures, scenarios) + tests. The API router and frontend from the
spec are **optional** — a notebook demo is enough for prep purposes.

**What it must teach you** (write these up as you hit them):
- Why 30E/360 and ACT/ACT-ICMA give different accrued on the same bond
  (eurobonds use ICMA conventions — this *is* your target market's plumbing).
- Clean vs dirty price and why quotes are clean.
- YTM as an internal rate: solver behavior near price 100, semi-annual vs
  annual compounding conversions.
- Duration/DV01 from first principles; verify your Set-A drill approximations
  against exact repricing (the scenarios module does exactly this comparison).

**Acceptance:** textbook vectors pass (Steiner/Fabozzi examples reproduced to
the cent); property tests (price↓ when yield↑, dirty = clean + accrued,
duration approximation error grows with |Δy| and convexity fixes most of it);
optional QuantLib cross-check. **Exit interview with yourself:** price a bond
by hand, then defend every number your code produces.

## Build 2 (weeks 2–6): FX carry + TSM, G10 — the flagship

**Spec:** `docs/ai/cross-asset-lab-slice1.md` /
`docs/offshore-lab/01-cross-asset-research-lab.md`, **FX sleeve only**.
Commodities stay fixture/import-path (per the plan's own §22 recommendation);
do not stall the FX result waiting on contract data.

**Locked choices** (from the plan's open decisions — resolved for prep speed):
G10 universe (USD, EUR, JPY, GBP, CHF, AUD, CAD, NZD, NOK, SEK); monthly
rebalance (matches MOP/carry literature); base ccy USD; FRED OIS-style proxies
for the rate legs.

**What it must teach you:**
- FX excess return = spot return + (r_base − r_quote)·τ — the same CIP identity
  as drill Set B, now with real data and day counts.
- Carry as a strategy: sort G10 by rate differential, long high-yielders /
  short low-yielders — then look at 2008 in your own equity curve and explain
  the crash-risk/short-vol character in one paragraph.
- TSM: sign of own 12m excess return; why lagged execution and lagged vol
  estimates matter (show the look-ahead version and quantify the inflation).
- Costs and turnover; gross vs net; deflated Sharpe with variant count.

**Acceptance:** sign/shape sanity vs published MOP 2012 / Koijen et al. stylized
facts (a band, not a golden number); no-look-ahead shift test passes; a
**five-page writeup** (methodology → results → robustness → limitations →
"what I would trade and what I wouldn't, and why") — this document *is* the
interview artifact; the code is its appendix.

## Build 3 (weeks 6–8): Curve lab

**Spec:** `docs/offshore-lab/00-response.md` §5 Phase 3. Ingest UST par yields
(FRED `DGS*`), ECB euro-area AAA curve, BAM MAD reference curve via the
existing macro-ingestion pattern; snapshots, 2s10s/5s30s history,
steepener/flattener classification, roll-down, DV01-neutral curve-trade
simulator.

**What it must teach you:** reading a curve like a trader (what's priced for
policy vs term premium), the four steepener/flattener regimes on *your own
historical data* (label 2022–2026 episodes yourself), roll-down as carry, and
the Morocco angle (BAM curve vs UST/Bund — feeds the blotter's Morocco row).

**Acceptance:** the blotter's rates section fills itself from this lab; you can
pull up any month since 2022 and narrate what the US curve did and why.

## Explicitly deferred

- Paper-trading desk (`docs/plans/paper-trading-desk.md`) and US port
  (`docs/plans/multi-market-port.md`) — after the job hunt.
- Eurobond RV engine (Phase 4) — data-blocked without Bloomberg; the *market
  knowledge* is covered in `01` week 8 and `05` instead.
- Any cross-asset frontend beyond a minimal results view.
