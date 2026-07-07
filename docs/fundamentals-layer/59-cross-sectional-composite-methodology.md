# 59 — Cross-sectional fundamental composite: methodology & rationale

**Status**: approved methodology, 2026-07-05. Implementation brief: [`60-codex-cross-sectional-composite-implementation.md`](60-codex-cross-sectional-composite-implementation.md).
**Supersedes**: the *strategy* role of the IC-weighted valuation ensemble (briefs 48, 54–56). The ensemble
survives as a single-name diagnostic anchor (§7); it is no longer the layer that generates portfolio signals.

---

## 1. The problem this methodology solves

The fundamental layer today produces **absolute fair values** (DCF / DDM / RI / relative multiples →
ensemble → upside %). Two internal findings show this cannot be the trading signal:

1. **The perfect-foresight IC study (brief 55) and the 2026-07-02 coverage audit found zero real IC
   spread between valuation methods** across 73 covered names: ~50 names sit at 100%
   `relative_multiples` weight, and `fcff_dcf` receives ~zero ensemble weight almost everywhere.
   The "IC weighting" is decorative; the ensemble is a multiples monoculture.
2. **Absolute valuation errors are large and shared.** WACC, terminal growth, and normalization
   assumptions move every model's fair value for every symbol in the same direction. An error you
   share across the whole universe cancels in a *ranking* but fully contaminates an *upside %*.

This is not an implementation bug — it is the known difference between the **sell-side use of
valuation** (price targets as a communication device for single-name coverage) and the **buy-side
systematic use of fundamentals** (cross-sectional relative ranking). Systematic managers
(AQR, Robeco, DFA style) do not trade DCF upside. They score every stock on the same
characteristics, standardize *across the universe at one date*, and overweight the top of the rank
against the benchmark. Ranking differences out the shared errors: we never need IAM's true fair
value, only whether IAM is cheaper than Attijariwafa per unit of quality.

**Decision**: the fundamental trading signal becomes a **cross-sectional composite rank**
("Score Fondamental Croisé", SFC). The valuation ensemble is demoted to a per-name anchor (§7).

---

## 2. Market constraints the design must respect (BVC / MASI)

| Constraint | Consequence for design |
|---|---|
| No practical short-selling mechanism | Long-only, benchmark-relative. "Shorts" = zero-weight avoid list + index underweights. |
| ~75 listed names, ~40–60 investable after liquidity filter | Tiny breadth → no capacity to fit weights; composite must be assumption-light (equal-weight pillars). |
| Semiannual statements + quarterly revenue indicators ("indicateurs trimestriels") | ~4 fundamental information events per name per year → event-anchored rebalancing, not monthly. |
| Thin analyst coverage (BKGR stock guide + a few brokers) | Statement information diffuses slowly → exactly the regime where financial-statement signals (F-score) earn their premium (§3.3). |
| Opening-auction execution, thin books on small caps | Costs = fees (33 bps/side, desk-confirmed) + impact bounded by ADV participation cap; turnover is the only real cost lever. |
| MASI concentration (banks + Maroc Telecom dominate) | Active weights must be bounded per name and per sector or the "portfolio" is three bets. |

**Fundamental law framing** ([Grinold; Clarke, de Silva & Thorley on the transfer coefficient][10][11]):
IR = TC × IC × √BR. Breadth here is ~60 names × ~2–4 independent fundamental bets/year — tiny.
The long-only constraint further cuts TC well below 1 (an underweight in a mega-cap is capped at its
index weight). Implications, stated honestly:

- We cannot manufacture IR through breadth. We maximize **IC** by combining several *independent*
  slow signals into one composite, and protect it with **low turnover**.
- Expected outcome is a modest-IR, patient, benchmark-relative tilt strategy — not high-frequency
  alpha. Claims beyond that are not supported by the math.

---

## 3. Evidence review (why these pillars)

### 3.1 Value — the strongest documented effect on the CSE itself
- [Fundamental anomalies on the Casablanca Stock Exchange, *Modern Finance* 2024][2]
  (2001–2020, 50 non-financials): significant B/M, low-P/E and low-P/CF effects; size and
  leverage insignificant. (Reported spread magnitudes look implausibly large — treat direction,
  not magnitude, as the finding.)
- [CAPM / FF3 / FF5 on the Moroccan exchange, *IJFS* 2023][3] (2002–2020): value is the most
  pronounced non-market factor; profitability and investment factors weak *as FF factors*.
- [de Groot, Pang & Swinkels, *J. Empirical Finance* 2012][1] (1,400 stocks, 24 frontier markets,
  survivorship-bias-free): value and momentum effects are economically and statistically
  significant **and survive conservative transaction-cost assumptions**; not explained by global
  risk factors.

### 3.2 Price momentum — works locally, diversifies value
- [Momentum strategies in Moroccan industries, *Cogent Business & Management* 2022][4]
  (59 CSE firms, 2008–2017): solid momentum evidence with ~6-month formation periods.
- Same frontier-market study as above ([de Groot et al.][1]) confirms momentum in frontier
  markets with liquidity-conscious implementation.
- Value and momentum are negatively correlated ([Asness, Moskowitz & Pedersen, *Value and
  Momentum Everywhere*, JF 2013][9]) — combining them raises composite IC even when each
  pillar's IC is modest.

### 3.3 Quality / financial-statement analysis — highest-conviction pillar for this market
- [Piotroski 2000][5]: F-score returns concentrate in **small firms, low share turnover, no
  analyst following** — a literal description of most MASI names. Mechanism: the market fails
  to impound statement information promptly where coverage is thin.
- [Emerging-markets F-score evidence][6]: high-F-score minus low-F-score premium on the order of
  10%/yr, **unrelated to size, value and momentum premia**.
- [Asness, Frazzini & Pedersen, *Quality Minus Junk*][7]: profitability + low accruals + safety
  earns robust risk-adjusted returns across 24 countries; quality is underpriced everywhere.
- Accruals specifically: Sloan 1996 — cash-backed earnings outperform accrual-heavy earnings.
  `scoring.py` already computes `_accrual_quality` and `_piotroski_lite`; this pillar reuses them.
- BVC-specific addition: **dividend sustainability**. Local institutional demand (OPCVM) is
  yield-driven; a dividend covered by FCF with a stable track record is both a quality marker and
  a local flow catalyst.

### 3.4 Fundamental momentum / drift — the event-driven pillar
- [PEAD review, *J. Behavioral & Experimental Finance* 2021][8]: post-earnings-announcement drift
  is one of the oldest, most persistent anomalies; drift is **larger and longer where forecast
  revisions are slow** — again the BVC regime. PEAD subsumes price momentum in factor
  regressions but is not subsumed by it.
- Morocco's disclosure calendar gives us the events: semiannual results (vs consensus where
  covered) + quarterly revenue indicators (YoY growth and acceleration, universally available).

### 3.5 Why equal-weighted pillars (not fitted weights, not ML)
- With ≤60 names × ≤10 usable annual cross-sections, any fitted weighting scheme is dominated by
  estimation error; bounded/equal combinations are the robust choice (the 1/N result of
  DeMiguel, Garlappi & Uppal 2009; [bounded multi-factor tilts][12]). Averaging correlated
  signals also provides noise reduction that orthogonalization destroys.
- IC-weighting *across pillars* may be revisited **only after** ≥3 years of live out-of-sample
  pillar ICs exist. Until then, equal weights are a design commitment, not a placeholder.

---

## 4. The methodology — Score Fondamental Croisé (SFC)

### 4.1 Universe and data
- Universe: MASI equities passing the existing liquidity screen (ADV20 threshold as in the
  dashboard), including delisted names for backtests (`bvc_pit_universe.csv`, already used by
  `pit_ic_backtest.py`).
- **Point-in-time discipline** (non-negotiable, same standard as `pit_ic_backtest.py`):
  - Fundamentals join as-of **`publication_date`** (`fundamental_annual_metric.publication_date`),
    never statement date. Where `publication_date` is null, apply a conservative availability lag:
    statement date + 90 days (annual) / + 60 days (semiannual) / + 45 days (quarterly indicators).
  - Consensus estimates join on `FundamentalConsensusEstimate.as_of_date`.
  - Prices: close on or before the as-of date; forward returns from price series only.
  - An `_assert_no_lookahead`-style guard must run in every backtest path.

### 4.2 Pillar definitions
All raw metrics are winsorized cross-sectionally at ±3 MAD-based z (median absolute deviation),
then z-scored **within the date's cross-section**. Financials/insurers and non-financials are
**demeaned separately** (two-bucket neutralization; full sector neutralization is infeasible with
sectors of 2–5 names). Higher z = more attractive.

**VAL — Value** (non-financials: E/P, B/P, CFO/P, EBITDA/EV; financials & insurers: E/P, B/P
— reuse the archetype split from `cgnc_mapping` / `tiering`). Trailing published figures; roll in
semiannual data where available.

**QUAL — Quality** (reuse `scoring.py` primitives):
- `_piotroski_lite` score (ROA > 0, CFO > 0, ΔROA, CFO > NI (accruals), Δleverage, Δliquidity,
  Δmargin, Δturnover — as implemented),
- DuPont ROE level and trend (`_dupont`),
- accrual quality (`_accrual_quality`),
- dividend sustainability: payout covered by FCF (non-financials) / by earnings (financials),
  and ≥3-year non-cut track record.
Pillar score = mean of available component z-scores.

**FMOM — Fundamental momentum**:
- semiannual earnings & revenue surprise vs consensus (where covered),
- consensus FY-estimate revision over the trailing 3–6 months (sign and magnitude),
- quarterly revenue indicator YoY growth and its acceleration (universal — no consensus needed).

**PMOM — Price momentum**:
- 6-1 month total return (skip most recent month, mitigates reversal/illiquidity bounce),
  computed only on liquidity-filtered names. The 12-1 alternative is evaluated **on the selection
  half only** (§5); whichever wins there is frozen for the proof half.

### 4.3 Composite
- `SFC = mean(available pillar z-scores)`, requiring **≥ 2 pillars** present; otherwise the name
  is `uncovered` (displayed as such, never silently scored).
- Each score carries `coverage_ratio` (pillars present / 4) and per-pillar attribution — the UI
  must always be able to answer *"why is this name ranked here?"* in one click.
- No optimizer. No fitted pillar weights (§3.5).

### 4.4 Portfolio construction
- Long-only, benchmark-relative vs MASI (or the app's custom index):
  - top tercile of SFC → overweight, bounded active weight per name (default ±3%),
  - middle tercile → benchmark weight,
  - bottom tercile → **zero weight** (the avoid list — this is where untradable "short" signals
    become useful),
  - existing sector caps and ADV-participation caps from the blotter apply unchanged.
- **Rebalance on the information calendar, not the clock**: after each publication window
  (annual, semiannual, quarterly indicators) → ~4 rebalances/year. Between events, only
  liquidity/risk exits.
- Turnover budget: ~50–80%/yr one-way expected; every backtest reports net-of-cost at
  33 bps/side **and stressed at 75 bps/side**.

### 4.5 What this strategy honestly claims
The exploitable inefficiency is **slow diffusion of financial-statement information in a
low-coverage, long-only market**, harvested through value + quality + fundamental-momentum
ranks with turnover discipline. It does not claim market timing, does not claim short alpha,
and does not claim precision in any single name's fair value.

---

## 5. Validation protocol (gates before any UI exposure)

Reuses the app's existing rigor standards (selection/proof separation as in
`core/quant_core/research/edge.py`, HAC t-stats as in `factor_selection/direct.py`).

1. **Rank IC study**: Spearman IC of SFC (and each pillar) vs 3/6/12-month forward returns,
   monthly cross-sections, Newey-West t-statistics (lag = horizon overlap).
2. **Selection/proof split**: all definitional choices (6-1 vs 12-1 PMOM, winsorization level,
   pillar component sets) are made on the **first half** of the sample; the **second half** is
   touched once, with the frozen configuration.
3. **Multiplicity control**: every variant evaluated on the selection half is counted; the
   proof-half pillar/composite p-values get Benjamini–Hochberg FDR at 10% across all variants.
4. **Portfolio backtest**: tercile long-only spread (top tercile vs universe), net of costs,
   block-bootstrap significance (existing `significance.py` machinery), max-drawdown and
   turnover reported.
5. **Pass criteria** (composite, proof half): mean rank IC > 0 with NW t ≥ 2.0 at ≥ 1 horizon,
   **and** positive net tercile spread at 33 bps that remains ≥ 0 at 75 bps. Pillars are
   reported individually but only the composite is gated — pillars are diversifiers, not
   standalone strategies.
6. **Failure handling**: if the composite fails the proof half, the result is published in the
   app as a negative finding (same policy as the technical proven-edge gates showing ~zero
   passes). No threshold shopping.

---

## 6. Known failure modes and mitigations

| Failure mode | Mitigation |
|---|---|
| Look-ahead via statement dates | Publication-date joins + conservative lags + assertion guard (§4.1). |
| Survivorship bias | PIT universe file including delisted names (already exists). |
| Tiny cross-sections make z-scores unstable | MAD winsorization; ≥ 8 names required per cross-section bucket or the bucket is skipped that date. |
| Two-bucket neutralization hides a financials bet | Report financials-vs-non-financials active exposure at every rebalance. |
| Consensus coverage is partial → FMOM biased to covered names | FMOM's universal component (revenue indicators) is mandatory; consensus components are optional add-ons. |
| Backtest overfitting via variant search | Selection/proof split + BH-FDR (§5.2–5.3). |
| Costs understate impact on small caps | ADV participation cap; 75 bps stress; auction-execution assumption documented in `EDGE_METHOD.md`. |

---

## 7. Role of the existing valuation ensemble after this change

- The triangulation band + football field remain the **single-name deep-dive anchor**: "is this
  name cheap vs its own history and peers", price-target framing for desk conversations.
- DCF / DDM / RI move to the **diagnostic family** (sanity anchors on the band, zero ensemble
  weight by construction) unless/until a method demonstrates real PIT IC (brief 55 machinery).
- The "IC" weighting toggle is removed or disabled-with-explanation wherever the underlying IC
  spread is degenerate — no decorative statistics anywhere in the app.
- Dashboard "Fondamental" mode ranks by **SFC**, not by ensemble upside. Upside % remains
  visible in the per-name drill-down, clearly labeled as an anchor, not a signal.

---

## Sources

[1]: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1600023 "de Groot, Pang & Swinkels — The Cross-Section of Stock Returns in Frontier Emerging Markets, J. Empirical Finance 19(5), 2012"
[2]: https://mf-journal.com/article/view/192 "Exploring fundamental anomalies: Evidence from the Moroccan stock market, Modern Finance, 2024"
[3]: https://www.mdpi.com/2227-7072/11/1/47 "The Empirical Explanatory Power of CAPM and the Fama and French Three-Five Factor Models in the Moroccan Stock Exchange, IJFS 11(1), 2023"
[4]: https://www.tandfonline.com/doi/full/10.1080/23311975.2022.2135217 "Momentum strategies and market state in Moroccan industries, Cogent Business & Management, 2022"
[5]: https://www.quant-investing.com/blog/piotroski-f-score-complete-guide "Piotroski (2000) — Value Investing: The Use of Historical Financial Statement Information to Separate Winners from Losers (summary & guide)"
[6]: https://www.researchgate.net/publication/251354092_An_Emerging_Markets_Analysis_of_the_Piotroski_F_Score "An Emerging Markets Analysis of the Piotroski F-Score"
[7]: https://www.aqr.com/Insights/Research/Working-Paper/Quality-Minus-Junk "Asness, Frazzini & Pedersen — Quality Minus Junk, AQR working paper / Review of Accounting Studies 2019"
[8]: https://www.sciencedirect.com/science/article/pii/S2214635020303750 "A review of the Post-Earnings-Announcement Drift, J. Behavioral and Experimental Finance, 2021"
[9]: https://onlinelibrary.wiley.com/doi/10.1111/jofi.12021 "Asness, Moskowitz & Pedersen — Value and Momentum Everywhere, Journal of Finance 68(3), 2013"
[10]: https://www.sciencedirect.com/science/article/pii/S0927539817300543 "The fundamental law of active management: Redux, J. Empirical Finance, 2017"
[11]: https://www.researchgate.net/publication/228182902_Portfolio_Constraints_and_the_Fundamental_Law_of_Active_Management "Clarke, de Silva & Thorley — Portfolio Constraints and the Fundamental Law of Active Management, FAJ 2002"
[12]: https://arxiv.org/pdf/2601.05428 "Dynamic Inclusion and Bounded Multi-Factor Tilts for Robust Portfolio Construction, 2026"

Additional canonical references (no stable open link): Sloan (1996) — *Do Stock Prices Fully
Reflect Information in Accruals and Cash Flows about Future Earnings?*, The Accounting Review;
DeMiguel, Garlappi & Uppal (2009) — *Optimal Versus Naive Diversification*, RFS; Grinold &
Kahn — *Active Portfolio Management*, 2nd ed.
