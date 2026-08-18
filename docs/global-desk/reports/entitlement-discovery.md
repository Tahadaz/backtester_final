# W1 — Bloomberg Entitlement Discovery Report

**Status: AWAITING TERMINAL RUN.** This file is a skeleton generated from the
security master. The three right-hand columns are empty until a discovery job
runs on the Bloomberg machine — nothing here should be read as a known result.

Regenerate the skeleton with:

```bash
python tools/global_desk/build_entitlement_report.py
```

## How to produce the data

On the Bloomberg terminal machine, with the listener running (see
`tools/bloomberg_bridge/FIELD_VISIT_RUNBOOK.md` steps 1-6), queue from **Data →
Bloomberg**:

```text
Job:       Discovery
Universe:  global_all
Mode:      Discovery only
Frequency: Daily
Fields:    PX_LAST
```

Start with `Universe: g10_fx` as a smaller smoke test before `global_all`, the
same way the MASI runbook tests one stock before the full index.

Then fill the columns below from the job result:

* **Status** — `available` / `partial` / `unavailable` / `not_entitled`
* **Earliest** — first date the terminal actually returns
* **Notes** — which candidate ticker resolved, field gaps, anything surprising

## Why this report gates W4 and W5

Two workstreams are scoped from these results rather than in advance:

* **Credit (`CDX_IG`, `CDX_HY`, `ITRAXX_MAIN`, `ITRAXX_XOVER`)** — the highest
  entitlement risk in the registry, and the tickers are unverified candidates. If
  credit is not entitled, W4's eurobond RV layer ships against ETF proxies with
  mixed duration/spread exposure, which is a materially weaker claim and must be
  labelled as such.
* **Commodities** — the question is whether *per-contract chains* are available,
  not just prices. Real chains are what turn the engine's roll accounting from
  illustrative into tradable (decision G7). Price-only means commodities stay on
  the non-tradable label.

Also confirm, for anything that will size a real trade: **contract multipliers and
tick sizes in the registry are taken from public specifications, not from the
terminal.** Verify against `DES` / `CT` before live use — `unverified_for_live_sizing()`
currently returns every instrument.

## What goes dark without Bloomberg

Program decision G9 requires that no sleeve *assume* Bloomberg. These instruments
have no free fallback and are the exception — they are unavailable, not degraded,
if the terminal is absent:

* `DU` — Euro-Schatz (German 2y) future. No wired free source for German yields; ECB/Bundesbank feed is not ingested.
* `OE` — Euro-Bobl (German 5y) future. No wired free source for German yields.
* `RX` — Euro-Bund (German 10y) future. No wired free source for German yields.
* `UB` — Euro-Buxl (German 30y) future. No wired free source for German yields.
* `G` — Long Gilt future. No wired free source for gilt yields.
* `JB` — Japanese Government Bond 10y future. No wired free source for JGB yields.
* `IK` — Italian BTP 10y future. No wired free source for BTP yields.
* `OAT` — French OAT 10y future. No wired free source for OAT yields.

Everything else (39 of 47 instruments) has a
documented free path and degrades in data quality rather than disappearing.

## Instruments

### FX (9)

| Id | Description | Bloomberg candidates | Free fallback | Requested from | Status | Earliest | Notes |
|---|---|---|---|---|---|---|---|
| `EURUSD` | Euro / US dollar | `EURUSD Curncy` / `EUR Curncy` | `EURUSD=X` | 1999-01-04 | | | |
| `USDJPY` | US dollar / Japanese yen | `USDJPY Curncy` / `JPY Curncy` | `JPY=X` | 1990-01-01 | | | |
| `GBPUSD` | Sterling / US dollar | `GBPUSD Curncy` / `GBP Curncy` | `GBPUSD=X` | 1993-01-01 | | | |
| `USDCHF` | US dollar / Swiss franc | `USDCHF Curncy` / `CHF Curncy` | `CHF=X` | 1990-01-01 | | | |
| `AUDUSD` | Australian dollar / US dollar | `AUDUSD Curncy` / `AUD Curncy` | `AUDUSD=X` | 1990-01-01 | | | |
| `USDCAD` | US dollar / Canadian dollar | `USDCAD Curncy` / `CAD Curncy` | `CAD=X` | 1990-01-01 | | | |
| `NZDUSD` | New Zealand dollar / US dollar | `NZDUSD Curncy` / `NZD Curncy` | `NZDUSD=X` | 1990-01-01 | | | |
| `USDNOK` | US dollar / Norwegian krone | `USDNOK Curncy` / `NOK Curncy` | `NOK=X` | 1990-01-01 | | | |
| `USDSEK` | US dollar / Swedish krona | `USDSEK Curncy` / `SEK Curncy` | `SEK=X` | 1993-01-01 | | | |

### Sovereign rates (12)

| Id | Description | Bloomberg candidates | Free fallback | Requested from | Status | Earliest | Notes |
|---|---|---|---|---|---|---|---|
| `TU` | US 2-year Treasury note future | `TU1 Comdty` / `TU1 Index` | `DGS2` | 1990-06-01 | | | |
| `FV` | US 5-year Treasury note future | `FV1 Comdty` / `FV1 Index` | `DGS5` | 1988-05-01 | | | |
| `TY` | US 10-year Treasury note future | `TY1 Comdty` / `TY1 Index` | `DGS10` | 1990-01-01 | | | |
| `US` | US long bond future | `US1 Comdty` / `US1 Index` | `DGS30` | 1990-01-01 | | | |
| `DU` | Euro-Schatz (German 2y) future | `DU1 Comdty` / `DU1 Index` | **none** | 1999-01-04 | | | |
| `OE` | Euro-Bobl (German 5y) future | `OE1 Comdty` / `OE1 Index` | **none** | 1999-01-04 | | | |
| `RX` | Euro-Bund (German 10y) future | `RX1 Comdty` / `RX1 Index` | **none** | 1999-01-04 | | | |
| `UB` | Euro-Buxl (German 30y) future | `UB1 Comdty` / `UB1 Index` | **none** | 2005-09-01 | | | |
| `G` | Long Gilt future | `G 1 Comdty` / `G1 Comdty` | **none** | 1990-01-01 | | | |
| `JB` | Japanese Government Bond 10y future | `JB1 Comdty` / `JB1 Index` | **none** | 1990-01-01 | | | |
| `IK` | Italian BTP 10y future | `IK1 Comdty` / `IK1 Index` | **none** | 2009-09-01 | | | |
| `OAT` | French OAT 10y future | `OAT1 Comdty` / `OAT1 Index` | **none** | 2012-04-01 | | | |

### Credit (4)

| Id | Description | Bloomberg candidates | Free fallback | Requested from | Status | Earliest | Notes |
|---|---|---|---|---|---|---|---|
| `CDX_IG` | Markit CDX North America Investment Grade | `IBOXUMAE Index` / `CDX IG CDSI GEN 5Y Corp` | `LQD` | 2004-01-01 | | | |
| `CDX_HY` | Markit CDX North America High Yield | `IBOXHYSE Index` / `CDX HY CDSI GEN 5Y Corp` | `HYG` | 2004-01-01 | | | |
| `ITRAXX_MAIN` | Markit iTraxx Europe Main | `ITRXEBE Index` / `ITRAXX EUROPE CDSI GEN 5Y Corp` | `IEAC.L` | 2004-06-01 | | | |
| `ITRAXX_XOVER` | Markit iTraxx Europe Crossover | `ITRXEXE Index` / `ITRAXX XOVER CDSI GEN 5Y Corp` | `IHYG.L` | 2004-06-01 | | | |

### Commodities (14)

| Id | Description | Bloomberg candidates | Free fallback | Requested from | Status | Earliest | Notes |
|---|---|---|---|---|---|---|---|
| `CL` | WTI crude oil | `CL1 Comdty` | `CL=F` | 1990-01-01 | | | |
| `CO` | Brent crude oil | `CO1 Comdty` | `BZ=F` | 1990-01-01 | | | |
| `NG` | Henry Hub natural gas | `NG1 Comdty` | `NG=F` | 1993-01-01 | | | |
| `HO` | NY Harbor ULSD (heating oil) | `HO1 Comdty` | `HO=F` | 1990-01-01 | | | |
| `XB` | RBOB gasoline | `XB1 Comdty` | `RB=F` | 2006-01-01 | | | |
| `GC` | COMEX gold | `GC1 Comdty` | `GC=F` | 1990-01-01 | | | |
| `SI` | COMEX silver | `SI1 Comdty` | `SI=F` | 1990-01-01 | | | |
| `HG` | COMEX copper | `HG1 Comdty` | `HG=F` | 1990-01-01 | | | |
| `PL` | NYMEX platinum | `PL1 Comdty` | `PL=F` | 1990-01-01 | | | |
| `C` | CBOT corn | `C 1 Comdty` / `C1 Comdty` | `ZC=F` | 2000-01-01 | | | |
| `S` | CBOT soybeans | `S 1 Comdty` / `S1 Comdty` | `ZS=F` | 2000-01-01 | | | |
| `W` | CBOT wheat | `W 1 Comdty` / `W1 Comdty` | `ZW=F` | 2000-01-01 | | | |
| `SB` | ICE sugar no. 11 | `SB1 Comdty` | `SB=F` | 2000-01-01 | | | |
| `KC` | ICE coffee C | `KC1 Comdty` | `KC=F` | 2000-01-01 | | | |

### Equity index (8)

| Id | Description | Bloomberg candidates | Free fallback | Requested from | Status | Earliest | Notes |
|---|---|---|---|---|---|---|---|
| `ES` | E-mini S&P 500 future | `ES1 Index` / `ES1 Comdty` | `ES=F` | 1997-09-01 | | | |
| `NQ` | E-mini Nasdaq 100 future | `NQ1 Index` / `NQ1 Comdty` | `NQ=F` | 1999-06-01 | | | |
| `VG` | Euro Stoxx 50 future | `VG1 Index` / `VG1 Comdty` | `^STOXX50E` | 1999-01-04 | | | |
| `GX` | DAX future | `GX1 Index` / `GX1 Comdty` | `^GDAXI` | 1999-01-04 | | | |
| `CF` | CAC 40 future | `CF1 Index` / `CF1 Comdty` | `^FCHI` | 1999-01-04 | | | |
| `Z` | FTSE 100 future | `Z 1 Index` / `Z1 Index` | `^FTSE` | 1990-01-01 | | | |
| `NK` | Nikkei 225 future | `NK1 Index` / `NK1 Comdty` | `^N225` | 1990-01-01 | | | |
| `HI` | Hang Seng future | `HI1 Index` / `HI1 Comdty` | `^HSI` | 1990-01-01 | | | |

## Universe summary

| Universe | Instruments |
|---|---|
| `g10_fx` | 9 |
| `sovereign_rates` | 12 |
| `credit` | 4 |
| `commodities` | 14 |
| `equity_index` | 8 |
| `global_all` | 47 |
