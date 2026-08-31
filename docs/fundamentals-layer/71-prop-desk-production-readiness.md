# Fundamental factor model: prop-desk production-readiness review

**Review date:** 2026-08-31

**Decision:** **NO-GO FOR LIVE CAPITAL**

**Permitted use:** research only

**Candidate retained for reconstruction:** Structural Value, measured by point-in-time book-to-market (B/M)
**Not approved:** the legacy SFC composite, CF/P as a production sleeve, the saved historical performance, paper orders, or live orders

This is a model-risk decision, not a view that value investing is invalid. The repository contained a model-invalidating B/M denominator defect. Structural Value v2.1 fixes that formula, rejects unverified publication dates, and completes a deterministic liquidity-constrained run, but strict PIT coverage leaves only four monthly observations. Effective-share, corporate-action, universe, total-return, execution, concentration, impact, and governance evidence remains incomplete.

The application now exposes a versioned, fail-closed readiness report. Live authorization is false unless every evidence gate passes; missing evidence can never count as a pass. See `core/quant_core/fundamentals/cross_section/production_readiness.py`.

## 1. Executive decision

| Question | Answer |
|---|---|
| Is the economic idea established enough to keep researching? | **Yes.** B/M is established in the literature and is the simplest repository candidate. |
| Does the existing test establish a Moroccan live strategy? | **No.** The saved B/M series often divides book equity by a stale stored market-cap value. |
| Is the accounting history strictly as-published PIT? | **Not yet.** The v2 path is strict, 194 metric rows were exactly reconciled, and six missing source-document dates were recovered from the official archive; unmatched history remains ineligible. |
| Is the universe survivorship-safe? | **Not demonstrated.** Many listing records are unverified and missing listing dates; absent issuers cannot be recovered by code. |
| Are realized returns, benchmark, fills, and costs executable? | **No.** Total-return and corporate-action treatment, next-session fills, liquidity, and desk-calibrated costs are not complete. |
| Is the evidence independent? | **No.** No corrected v2 backtest or untouched holdout exists; the earlier result is withdrawn. |
| Can any saved Sharpe, IC, alpha, or drawdown be presented as validated performance? | **No.** Those figures are research artifacts pending a corrected end-to-end rerun. |
| Can the model send paper or live orders? | **No.** `live_trading_authorized` is fail-closed to `false`. |

## 2. Model-invalidating defect and repair status

The withdrawn v1 B/M code first took `MarketCap_Calc` or `Market_Cap` from a fundamental filing snapshot and only calculated `close × shares` when stored market cap was absent:

- `core/quant_core/fundamentals/cross_section/characteristic_study.py`
- `core/quant_core/fundamentals/cross_section/methodology_bakeoff.py`
- `services/api/app/services/value_signal.py`
- `services/api/app/services/value_strategy_snapshot.py`

This means an accounting-vintage market cap can remain fixed while the security price changes. The repaired saved panel provides a direct falsification:

| ATW panel evidence | Observed value |
|---|---:|
| Monthly rows | 111 |
| Distinct closes | 97 |
| Distinct stored market caps | 10 |
| Close on 2025-03-31 | 699.8 |
| Close on 2025-08-31 | 781.0 |
| Close on 2025-12-31 | 730.1 |
| Stored market cap throughout those dates | 109,270,032,128.1 |
| Saved B/M throughout those dates | 0.6635213570 |

Evidence file: `research-out/data-quality-forensic-repair/2026-07-06/characteristic-study-after-repair/20260706-194324/panel_characteristics.csv`.

The correct denominator at decision time is market equity derived from the price and shares effective at that time, with all relevant corporate actions reconciled. The repository's share history cannot currently repair the error safely: many annual `Shares_Outstanding` rows repeat a current share count across historical years or carry present-dated backfills. Replacing one unvintaged field with another would preserve the PIT defect.

Structural Value v2 now uses only `decision-date close × PIT shares`; stored workbook market cap is ignored. It also requires a trustworthy source-document publication date in validation and API paths. This repairs the code defect, not the historical evidence: all v1 B/M ranks, ICs, selections, returns, Sharpe ratios, alphas, drawdowns, and attribution remain withdrawn until the v2 pipeline is rerun on certified effective-share and corporate-action data.

### 2.1 Remediation completed on 2026-08-30

- Parsed the official Bourse issuer-publication HTML as a dated document catalog, with no missing-date fallback.
- Browser and parser inspection confirmed server-rendered publication date, type, title, and PDF URL fields. The deterministic crawl collected 1,939 unique financial-statement/annual-report assets and stops when Drupal repeats its final page instead of relying on an arbitrary page limit.
- The Bourse site migration changed PDF parent folders, so no stored URL had an identical full path. A fallback is allowed only for an exact filename that is globally unique in both the official archive and the local official-document set. Through verified system-TLS transport, six missing source-document dates were filled with archive URL and match-kind lineage. Four conflicting dates and six ambiguous filenames were not overwritten or matched.
- Added exact StockAnalysis-to-BVC reconciliation on symbol, fiscal year, canonical metric, and decimal value. No tolerance, fuzzy title match, or inferred lag is permitted.
- Applied 194 exact links across 38 issuers and five StockAnalysis imports; every changed row has prior/new lineage recorded in import metadata. A repeat audit reported zero changes and 194 already-exact rows.
- Of those 194 links, seven are `Total_Equity`; none of the new matches are `Shares_Outstanding`.
- After archive reconciliation, the strict cross-section at 2026-05-31 contains 66 rows and 20 B/M-eligible issuers. Ineligibility is preserved where verified shares or book equity are absent.
- Removed the stochastic bootstrap from the fundamental IC study's primary result and replaced it with deterministic Newey-West HAC mean inference.
- Changed Bourse price ingestion to reject rows without an observed session date and stopped manufacturing `Adj Close` from raw `Close`.
- Structural Value v2 snapshot recomputation now requires an explicit cost value and source; the legacy unsourced 33 bps convention is rejected.

These counts are implementation evidence, not performance evidence and not a release approval.

## 3. Economic model retained after the audit

### 3.1 Frozen research candidate

For issuer *i* at decision timestamp *d*:

`B/M(i,d) = latest positive group-share book equity actually published by d / market equity observable at d`

where:

- the accounting value comes from an immutable as-published filing vintage;
- the numerator's publication timestamp is observed from an official filing record, not inferred from a generic delay;
- market equity is the traded decision-date price times total shares outstanding effective at the same timestamp; price adjustment belongs in the return series, not the market-cap identity;
- splits, rights, share issues, cancellations, mergers, suspensions, and delistings are explicitly represented;
- negative or missing book equity is ineligible rather than imputed;
- the score is the deterministic cross-sectional rank among securities that were genuinely investable at *d*;
- no random input, fitted blend weight, estimated consensus revision, or valuation forecast enters the production signal.

This is a candidate specification, not an order rule. A portfolio breakpoint, rebalance calendar, capacity rule, and risk limit must be predeclared and approved before the corrected test is run. A threshold is not justified merely because it improves the backtest.

### 3.2 Rejected production candidates

**Legacy SFC:** reject as a production selector. Its final repository validation found that value dominated; quality and fundamental momentum were not robust. Its fundamental-momentum implementation also selects forecast-year keys using the machine's current calendar year and combines consensus levels with realized growth ratios. That is neither a stable historical definition nor an estimate-revision signal.

**CF/P:** retain only as secondary research. The repository has unresolved cash-flow mapping and economic-applicability gaps, including leasing/financing exclusions. It cannot be a live sleeve until those fields receive the same PIT and document-level controls as B/M.

**Intrinsic valuation:** keep as an analyst diagnostic. Assumption-heavy fair-value estimates should not be silently mixed into a systematic rank.

## 4. A-to-Z methodology review

| Phase | Current status | Audit conclusion | Evidence required to pass |
|---|---|---|---|
| Economic hypothesis | Partial pass | B/M has a trusted research foundation; Morocco-specific harvestability is unproven. | Frozen hypothesis and mechanism stated before rerun. |
| Candidate inventory | Fail | Earlier SFC research reused and combined weak components; the factor search creates multiple-testing risk. | Dated research registry containing every attempted signal and sign. |
| Formula definition | Partial pass | Structural Value v2 B/M now tracks decision-date price and ignores stored market cap; legacy SFC/FMoM remains rejected. | Preserve v2 tests and keep the legacy composite out of the production candidate. |
| Accounting source | Fail | Corrected extracts are not an append-only as-published archive. | Filing document, page/table, issuer, period, publication timestamp, extraction version, and restatement linkage for every value. |
| PIT availability | Partial pass | Strict code rejects fallback dates; 194 exact metric links and six official archive dates were applied with lineage. Most StockAnalysis history remains unmatched, while four date conflicts and six ambiguous filenames remain quarantined. | Complete official value-level reconciliation and manually adjudicate conflicts; unmatched rows stay ineligible. |
| Duplicate/conflict resolution | Fail | 6,964 generic conflicts remain; about 20 symbols have factor-critical scale/sign conflicts. | Conflict quarantine, document-level adjudication, and independent reconciliation. |
| Accounting comparability | Fail | Net-income aliases mix consolidated total and group-share income; CF/P applicability remains incomplete. | Canonical accounting policy by issuer type and test coverage for every alias. |
| Market equity | **Critical data fail** | Formula is repaired, but the historical share ledger is not corporate-action certified. | Corporate-action-aware effective shares and traded prices, reconciled to official records. |
| Historical universe | Fail | Listing dates/statuses are mostly unverified; never-ingested securities remain absent. | Official security master with listing, suspension, relisting, delisting, and terminal outcome dates. |
| Returns | Fail | `Close` adjustment is not certified; dividends and delisting proceeds are not fully modeled. | Verified security total-return series and cash-flow ledger. |
| Benchmark | Fail | MASI comparison is price-only and therefore not like-for-like with an equity strategy. | Official or independently reconstructed total-return benchmark with constituent history. |
| Cross-sectional tests | Rejected pending rerun | Reported positive IC/HAC results were calculated on the faulty denominator. | Corrected PIT rerun, rank IC, spreads, controlled tests, coverage, turnover, and all exclusions. |
| Multiple testing | Fail | No complete trial registry protects against the factor zoo. | Predeclared family of hypotheses and false-discovery control across all attempted variants. |
| Dependence/inference | Partial pass | Primary IC inference is now deterministic HAC, but no corrected v2 result or non-overlapping validation has been produced. | HAC and non-overlapping evidence with lags implied by the holding construction. |
| Holdout | Fail | The 2022-2026 interval is short, one-regime, and repeatedly reused. | Locked, untouched data/time holdout or genuinely prospective shadow record. |
| Portfolio construction | Fail | No approved capacity, liquidity, sector, or concentration policy. | Rules approved before rerun, plus exposure and constraint attribution. |
| Execution | Fail | `execution_lag_days` exists but is not applied; month-end close-to-close prices are used. | Next-session decision/fill convention, no-fill and suspension logic, settlement, and rejected-order ledger. |
| Costs | Fail | A fixed 33 bps convention lacks a linked broker schedule or impact calibration. | Dated statutory fees, broker charges, spread, impact, taxes, and order-size calibration. |
| Robustness | Fail | The result is concentrated in ADH, ADI, and JET; liquidity was not tested. | Leave-cluster-out, sector-neutral/exposure attribution, liquidity/capacity, alternative valid dates, and missing-data stress tests. |
| Paper trading | Fail | No reconciled shadow track record exists. | Orders-to-fills-to-holdings/cash reconciliation under the exact production code path. |
| Operations and risk | Fail | The research snapshot is not an OMS or live risk system. | Stale-data rejection, pre-trade limits, duplicate-order guard, kill switch, monitoring, recovery test, and named owners. |
| Governance | Fail | Earlier documents call incompatible architectures “production.” | Versioned model card, independent validation, sign-offs, change control, and rollback policy. |

## 5. Existing research: what may and may not be said

The repository's own July 2026 live-like review classified the strategy **“RESEARCH STRATEGY — PROMISING,” not ready for paper trading**. It also recorded:

- only 51 invested months for S1 B/M, from March 2022 through May 2026;
- effective independent evidence closer to 6–9 observations because adjacent months share five of six vintages;
- no ADV-based liquidity screen;
- about 36% of S1 exposure in ADH, ADI, and JET;
- an i.i.d. bootstrap that likely understates uncertainty;
- a price-index, not total-return, benchmark;
- execution lag present in configuration but absent from price lookup.

Those limitations were already sufficient for a no-go. The newly identified market-equity defect is stronger: it withdraws the factor and performance estimates themselves until reconstruction.

Operationally, the latest persisted snapshot observed during this review was computed on 2026-07-07, had an as-of date of 2026-05-31, and still carried the research-only classification. On 2026-08-30 it was not a current trading input.

## 6. Deterministic validation protocol for the rebuild

The following sequence is fixed. Do not look at later-stage performance to decide how to repair an earlier stage.

1. **Freeze the research protocol.** Record the B/M definition, expected sign, universe, rebalance timestamp, selection rule, risk limits, costs, primary horizon, tests, and all rejection criteria. Register every later change.
2. **Build immutable source vintages.** Preserve the original filing, observed publication timestamp, extraction, correction, and restatement chain. Do not overwrite history.
3. **Reconstruct the security master.** Verify listing/delisting/suspension windows and corporate actions from official sources. Define terminal proceeds and unavailable-price behavior.
4. **Reconstruct market equity.** Maintain effective-dated total shares and traded price. Reconcile sampled dates to exchange notices and published market capitalization. Maintain a separate adjusted total-return series for performance. Reject rather than impute uncertain observations.
5. **Generate PIT panels.** At every decision timestamp, join only records whose observed availability time is earlier than the decision cutoff. Produce a row-level provenance manifest and fail on unavailable timestamps.
6. **Run deterministic data tests.** Accounting identity checks, units, signs, source conflicts, stale-field detection, price/share/market-cap reconciliation, universe continuity, and corporate-action continuity must pass.
7. **Run the predeclared factor tests.** Report coverage, rank IC by date, top-minus-bottom economics, controls, influence, sector/name attribution, and the full trial count. Apply dependence-aware inference and multiple-testing control.
8. **Open the locked holdout once.** Preserve the decision, code hash, data hash, and result. A failed holdout does not authorize a new specification on the same holdout.
9. **Run the executable portfolio simulation.** Use next-session attainable prices, total returns, explicit no-fill rules, point-in-time liquidity, capacity, concentration, all costs, cash, and delisting/corporate-action handling.
10. **Shadow trade and reconcile.** Compare every intended order, accepted order, fill, fee, position, cash movement, and corporate action. No research-only branch may differ from the prospective path.
11. **Obtain independent approvals.** Research, data, trading, risk/model validation, operations, and compliance owners sign the exact version. Only then may the readiness evidence record change.

### No-random/no-magic-number policy

“No numbers” is not literally possible in a quantitative strategy. The enforceable standard is **no unsourced, hindsight-selected, or stochastic production input**:

- production scores and orders are deterministic for identical versioned inputs;
- every numerical parameter has a source, owner, effective date, rationale, unit, and permitted range;
- statutory fees come from dated rules; broker fees from the executed agreement; spread and impact from observed executable data;
- thresholds are fixed before the holdout and receive sensitivity analysis that does not redefine the winner;
- random resampling is never part of the signal or authorization decision; if used as research diagnostics, the method and seed are disclosed and deterministic HAC/non-overlapping results remain primary;
- missing data, failed provenance, and unverified dates cause rejection, never an optimistic default.

## 7. Release gates

The release rule is conjunctive: **every gate must pass**. There is no weighted readiness score and no compensating a data failure with a high Sharpe ratio.

1. Deterministic frozen signal.
2. Observed PIT filing vintages.
3. PIT market equity.
4. Verified historical universe.
5. Total-return and corporate-action coverage.
6. Executable timing and fill rules.
7. Liquidity, capacity, and concentration controls.
8. Verified transaction costs.
9. Independent out-of-sample validation.
10. Reconciled paper/shadow record.
11. Live risk controls and signed ownership.

The machine-readable implementation is `current_repository_readiness()`. As reviewed, only the first gate passes.

## 8. Trusted methodological sources

| Topic | Primary source | Use in this review |
|---|---|---|
| B/M research basis | [Fama and French, *The Cross-Section of Expected Stock Returns* (1992)](https://doi.org/10.1111/j.1540-6261.1992.tb04398.x) | Economic hypothesis and cross-sectional testing; not proof that it works in Morocco. |
| Reproducible B/M construction | [Kenneth French Data Library — B/M portfolio details](https://mba.tuck.dartmouth.edu/pages/Faculty/ken.french/Data_Library/det_form_btm.html) | Positive book equity, explicitly dated book equity and market equity, price-times-shares denominator. |
| Serial-correlation-robust inference | [Newey and West, NBER Technical Working Paper 55](https://www.nber.org/papers/t0055) | HAC covariance for dependent/heteroskedastic observations. |
| Multiple testing | [Harvey, Liu, and Zhu, *…and the Cross-Section of Expected Returns* (2016)](https://academic.oup.com/rfs/article-abstract/29/1/5/1843824?login=false) | Factor-zoo discipline and higher evidentiary hurdle than an isolated conventional t-statistic. |
| Backtest selection bias | [Bailey et al., *The Probability of Backtest Overfitting*](https://escholarship.org/uc/item/4w1110bb) | Pre-registration, trial accounting, and protection against selecting the best historical variant. |
| Official Moroccan filings | [AMMC issuer financial-statement archive](https://www.ammc.ma/fr/liste-etats-financiers-emetteurs) | Publication documents and observed availability dates. |
| Official Bourse publication catalog | [Casablanca Bourse issuer publications](https://www.casablanca-bourse.com/apropos/publications/emetteurs) | Document-date catalog and PDF lineage; matched by exact normalized official path or a filename globally unique on both sides, never by issuer/year/title guess. |
| Investability/index operations | [MSCI Global Investable Market Index Methodology, March 2026](https://www.msci.com/indexes/documents/methodology/1_MSCI_Global_Investable_Market_Indexes_Methodology_20260331.pdf) | Free float, liquidity, number-of-shares changes, and corporate-event governance as institutional reference practices. |
| Moroccan fees and market rules | [Casablanca Stock Exchange — investing and commissions](https://www.casablanca-bourse.com/fr/pourquoi-et-comment-investir?csrt=50272177136811359) and [official legal/regulatory texts](https://www.casablanca-bourse.com/fr/textes-legislatifs-reglementaires?csrt=17188767355795525311) | Replace the unsupported cost constant with the complete dated fee/tax/broker/impact stack. |

These sources define research and control standards. They do not certify this repository, its data, or a future return.

## 9. Repository evidence

- `research-out/data-quality-forensic-repair/2026-07-06/final_data_quality_verdict.md`
- `research-out/data-quality-forensic-repair/2026-07-06/pit_fallback_audit.md`
- `research-out/data-quality-forensic-repair/2026-07-06/provenance_and_quality_rules.md`
- `research-out/live-like-value-strategy/20260706-202635/final_strategy_verdict.md`
- `research-out/live-like-value-strategy/20260706-202635/execution_and_holding_rules.md`
- `research-out/live-like-value-strategy/20260706-202635/benchmark_audit.md`
- `research-out/live-like-value-strategy/20260706-202635/statistical_uncertainty.md`
- `research-out/final-fundamental-model-validation/20260706-154326/final_production_recommendation.md`
- `docs/fundamentals-layer/70-sfc-final-validation.md`

## 10. Tomorrow's decision request

Ask the desk to approve **a controlled model rebuild and shadow-validation programme, not a capital allocation**. The immediate deliverables are the immutable filing archive, effective-dated shares/corporate actions, official security master, verified total-return data, and desk cost/execution specification. Once those exist, rerun the single frozen B/M candidate from zero and submit the resulting audit pack to independent validation.
