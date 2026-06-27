# Methodology and sources

**v3 status:** the implementation now includes the valuation/scoring corrections previously referenced as V1-V12 and S1-S9. Historical notes below that say "current" may refer to the pre-v3 implementation unless explicitly updated.

Academic references for the formulas in this layer, with citations and notes on where the implementation deviates from the source.

## Valuation models

### Discounted Cash Flow

**Damodaran, A. (2012).** *Investment Valuation: Tools and Techniques for Determining the Value of Any Asset.* 3rd ed., Wiley Finance.

- Chapters 14-15 cover FCFF and FCFE DCF.
- Chapter 12 covers WACC computation.
- Chapter 17 covers terminal value choice.

**Implementation deviations:**
- `_fcff_dcf` uses linear growth fade (not flat or two-stage) — see `_dcf_cash_flows` at `valuation.py:289`. Damodaran's standard 3-stage model (high → transition → stable) is more flexible; the linear fade is a simplification that's mathematically equivalent to a 2-stage average.
- `_fcfe_dcf` now uses debt-flow-adjusted FCF when interest and borrowing/repayment inputs exist; otherwise it explicitly marks raw FCF as a capped proxy. See [V1](12-known-issues-and-limitations.md#-v1).

### Dividend Discount Model

**Gordon, M. J., and E. Shapiro (1956).** *Capital Equipment Analysis: The Required Rate of Profit.* Management Science 3(1): 102-110.

- The single-stage Gordon model: `V = D₁ / (k - g)`.

**Implementation note:**
- `_ddm` uses sustainable growth `g = ROE × (1-payout)` as the above-terminal growth input, then applies the Fuller-Hsia H-model so the excess growth fades to terminal growth instead of being treated as a perpetuity.

### Residual Income

**Ohlson, J. A. (1995).** *Earnings, Book Values, and Dividends in Equity Valuation.* Contemporary Accounting Research 11(2): 661-687.

The seminal residual income paper. Formula:
```
V₀ = BV₀ + Σ_{t=1}^∞ (E[ROE_t - r] × BV_{t-1}) / (1 + r)^t
```

**Implementation note:**
- `_residual_income` projects residual income explicitly, keeps year 1 at full ROE, then fades the ROE-COE spread to zero over the competitive-erosion horizon.

### Justified Multiples

**Damodaran, A. (2006).** *Damodaran on Valuation.* 2nd ed., Wiley Finance.

- Chapter 7 covers justified P/E and P/B from fundamentals.
- Justified P/E = `(payout × (1+g)) / (k-g)`.
- Justified P/B = `(ROE - g) / (k - g)`.

**Implementation note:**
- `_justified_multiples` uses a finite fade from sustainable growth to terminal growth rather than clipping immediately to terminal growth. Aggregation remains the median of available justified P/B and P/E implied prices.

### Relative Multiples

Standard market practice. No single canonical source; relative valuation against peer medians is a discipline taught in CFA Level II.

**Implementation note:** the sector → market fallback at `peer_min_count=3` is a discipline against thin sectors that one would NOT find in introductory textbooks but is essential for emerging markets like Morocco.

### Banks and Insurers

Banks and insurers are valued equity-side. The engine suppresses industrial fields for financial issuers (`EBITDA`, `EV_to_EBITDA`, `EV_to_Sales`, `Price_to_Sales`, `Capex`, `Free_Cash_Flow`, FCF yield/margin, enterprise value, and net debt) and keeps FCFF, FCFE, reverse DCF, and EV bridges ineligible.

**Implementation note:**
- Banks use PNB growth, RBE margin, cost of risk, net income, dividends, and book-equity rollforward when those drivers are observed or peer-derived. Missing RBE margin or cost of risk makes the bank projection unavailable rather than using a constant.
- If a bank has no PNB history in the local feed, residual income may use a flagged P/B-ROE fallback based only on observed snapshot P/B and ROE.
- Insurers use a flagged ROE/book-equity projection when premium and combined-ratio data are absent.
- Financial relative multiples are P/B and P/E, with P/PNB only when own and peer observations exist.

### Source Data Verification

Brief 38 adds a source-data verification layer ahead of display-facing
valuation. Official BVC-hosted filings are the primary source for curated
remediation. Each hand-extracted correction records document URL, page/line
reference, and the verbatim filing label. `stockanalysis.com` is used only as an
independent secondary source or fallback where it covers the symbol; it does not
override a cited official filing.

The verifier recomputes ratios from raw lines:
- `assets = liabilities + equity`
- group-basis `BVPS = group equity / shares`; when minorities are absent or immaterial, group equity is total equity by definition
- `NetIncome = Resultat_net`, with `RNPG <= consolidated net income`
- group-basis `ROE = RNPG / group equity` for material-minority issuers; if minority interests/group-equity gaps are absent or <= `minority_materiality_epsilon`, `t4_basis=no_minority_total_equity` and ROE is `NetIncome / Total_Equity`
- one annual fiscal vintage per snapshot
- existing three-statement integrity checks
- plausibility bands for ROE and P/B

Stored ROE, BVPS, and P/B are treated as observed ratios to compare against the
recomputed formulas, never as valuation inputs of record. If a symbol/year cannot
tie out from a real source, it is persisted as `data_unverified` and valuation
returns NR with a human-readable reason.

For the FY2025 priority reingestion, the source of record is the committed
proof-of-read artifact in `data/corrections/fy2025/`. These files are curated
from the official filing itself, not from the automated Gemini/BVC extractor.
`stockanalysis.com` remains an independent cross-check only; disagreements are
flagged, not averaged. The apply path replaces canonical FY2025 statement rows
for the cohort with cited observed figures plus derived formulas. A filing line
that is genuinely absent is kept as `unavailable` in the proof artifact, and any
tie-out-critical absence or contradiction routes the symbol to
`data_unverified`/NR.

## Scoring methodology

### Rating gates and coverage

`derive_recommendation` is intentionally gated by both upside and ensemble confidence:

- `BUY`: `upside_pct > 12%` and `confidence_score >= 45%`.
- `SELL`: `upside_pct < -10%` and `confidence_score >= 45%`.
- `HOLD`: any rated case that does not cross the BUY/SELL gates.
- `NR`: target is withheld (`withheld_*` ensemble warning), no usable valuation models, missing target/current price, or missing confidence.

Conviction is a 1-5 ladder from ensemble confidence and model breadth:

```text
conviction = clamp(round(confidence_score * usable_model_count / 7 * 5), 1, 5)
```

The tear sheet surfaces `overall_coverage_pct`, per-pillar score scope (`sector`, `market`, or `insufficient`), `model_dispersion_cv`, `dispersion_factor`, and ensemble warnings so a PM can tell whether a rating is model-supported, thinly covered, or not rated.

### Piotroski-Lite F-Score

**Piotroski, J. D. (2000).** *Value Investing: The Use of Historical Financial Statement Information to Separate Winners from Losers.* Journal of Accounting Research 38: 1-41.

Original F-score has 9 binary tests across profitability (4), leverage / liquidity / source of funds (3), and operating efficiency (2). Score = 0-9.

**Implementation deviations:**
- `_piotroski_lite` adapts the 9 tests to the available metric vocabulary in this engine. Some original tests (e.g., "no equity issuance") are dropped because share-count change data isn't reliably present.
- Output is scaled 0-100 instead of 0-9 for UI consistency.
- See `scoring.py:174`.

### DuPont Analysis

**Bauman, M. P. (2014).** *Forecasting Operating Profitability with DuPont Analysis: Further Evidence.* Review of Accounting and Finance 13(2): 191-205. [for the forecasting evidence]

**Original framework: DuPont Corporation (1920s).** Decomposes ROE into Net Margin × Asset Turnover × Equity Multiplier.

**Implementation note:** `_dupont` doesn't forecast — it uses the DuPont bridge as a data-quality probe (reported vs implied ROE gap). This is non-standard; the typical use of DuPont is decomposition for trend analysis. The gap-as-quality-probe is a novel angle and aligns with this engine's emphasis on input reliability.

### Accrual Quality

**Sloan, R. G. (1996).** *Do Stock Prices Fully Reflect Information in Accruals and Cash Flows About Future Earnings?* The Accounting Review 71(3): 289-315.

The seminal accrual anomaly paper. Sloan defines accruals as (Net Income − CFO) / Total Assets and shows that high-accrual firms underperform.

**Implementation deviations:**
- `_accrual_quality` uses cash_conversion = FCF / |NI| as the headline metric (Sloan uses CFO; we use FCF for simplicity). Scaled to 0-100.
- Sloan emphasizes the anomaly's predictive power for future returns; we use it only as a quality signal, not a return predictor.

## Default assumptions

### Risk-free rate, ERP, country risk premium

**Damodaran, A. (annual).** *Country Risk Premiums and Equity Risk Premiums.* NYU Stern.

- Damodaran publishes annual updates with country-specific risk premia.
- Morocco-specific: mature ERP ~5.5-6%, country risk premium ~1.5%.
- The default `cost_of_equity = 0.105` reflects MAD market consensus as of model design (~2024).

**Periodic review:** these defaults should be re-validated annually against the latest Damodaran tables.

### Tax rate

Default 30% reflects standard Moroccan corporate income tax (IS) for industrial firms. Banks and insurance have different rates; sector overrides handle this.

### Terminal growth

3% reflects long-term Moroccan GDP + inflation expectation. International best practice is to set terminal growth at or below long-run GDP growth — using 3% errs on the conservative side.

### Growth cap

8% is a discipline against analyst optimism. Firms can grow above 8% temporarily but Damodaran's empirical work (and others) shows that fewer than 1% of firms sustain >8% growth over 10-year horizons.

## Quality / accrual signals — secondary literature

**Penman, S. H. (2013).** *Financial Statement Analysis and Security Valuation.* 5th ed., McGraw-Hill Education.
- Chapters 11-14 cover quality of earnings, accruals, and residual income.

**Mohanram, P. S. (2005).** *Separating Winners from Losers among Low Book-to-Market Stocks Using Financial Statement Analysis.* Review of Accounting Studies 10: 133-170.
- Companion to Piotroski's F-score, focused on growth stocks. Worth referencing if a "G-score" variant is ever added.

**Beneish, M. D. (1999).** *The Detection of Earnings Manipulation.* Financial Analysts Journal 55(5): 24-36.
- M-score for fraud detection. Not implemented; potential future diagnostic.

## Implementation philosophy references

**Lakonishok, J., A. Shleifer, and R. W. Vishny (1994).** *Contrarian Investment, Extrapolation, and Risk.* Journal of Finance 49(5): 1541-1578.
- Foundation for value investing as a quantifiable strategy.

**Graham, B., and D. L. Dodd (1934).** *Security Analysis.*
- The original value investing text. Treats fundamental analysis as the bedrock of investment.

**Asness, C., A. Frazzini, and L. H. Pedersen (2019).** *Quality Minus Junk.* Review of Accounting Studies 24(1): 34-112.
- The "Quality" pillar concept and metrics largely derive from this paper's framework.

## A note on Moroccan-market specifics

**Casablanca Stock Exchange (Bourse de Casablanca) characteristics:**
- ~80 listed firms (mostly large-cap industrial + financial).
- Thin sector cohorts → percentile rankings often degenerate at sector level.
- Strong financial sector representation (banks, insurers).
- Notable disclosure standards: French / IFRS hybrid; some metrics require canonical mapping (e.g., `Chiffre_daffaires` for Revenue, `Resultat_net` for Net Income).
- MAD currency, fixed peg to a EUR/USD basket — minimal FX volatility within the universe.

**Implication for this engine:** the percentile-rank approach (vs z-score) is appropriate for the thin universe. Sector bucketing (S2 fix) will help but won't fully solve thin-sector problems for niches like agriculture or specialty industrials.

## See also

- [04-pillars-and-scoring.md](04-pillars-and-scoring.md) — concrete pillar definitions.
- [06-valuation-models.md](06-valuation-models.md) — concrete model formulas.
- [12-known-issues-and-limitations.md](12-known-issues-and-limitations.md) — gaps between implementation and source.
