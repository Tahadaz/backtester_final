# 69 - Fundamental methodology

Methodology version: `sfc_core_v2_2026_07_06`
Evaluation / held-out-by-original-design period start: `2023-07-31`

## Raw/PIT fundamentals

The layer starts from point-in-time annual and period metrics joined only after publication date or the configured fallback lag. Consensus rows, where present, are joined as-of their own observation date. The output is a cross-sectional scored panel, not a valuation target sheet.

## Normalization and robust preprocessing

Each raw pillar component is MAD-winsorized within date, then z-scored within date and within the two peer buckets already used in production: financials versus non-financials. This keeps the preprocessing robust without pretending the market has enough names per date for fragile fine-grained neutralization.

## Peer/bucket-relative scoring

The peer step is intentionally two-bucket, not 19-sector. Financial statements for banks and insurers are structurally different from industrial names, so they are separated. Going further to 19-sector regression is rejected because the cross-sections are too thin; many date-sector cells would be too small for stable estimates.

## Pillar construction

VAL is the cross-sectional value pillar. QUAL is the quality pillar assembled from the existing Piotroski-lite, DuPont, accrual, and dividend-sustainability machinery. FMOM is the fundamental-momentum pillar built from revenue, earnings-growth, acceleration, and consensus-related metrics already in the scored panel. PMOM is still computed, unchanged, but it is now explicitly classified as a price-momentum market signal rather than a fundamental pillar.

## Composite construction

The production fundamental score is now `sfc = mean(VAL, QUAL, FMOM)` over available core pillars, requiring at least 2 of 3. `coverage_ratio` is therefore over the 3 core pillars. `sfc_legacy` is retained only for continuity and comparison as the prior 4-pillar mean. Leave-one-out in 70 shows QUAL and FMOM currently dilute in-sample IC at 6m, while removing VAL collapses the core IC from 0.0647 to 0.0198 and leaves it insignificant; QUAL and FMOM are still retained as economically motivated diversifiers because fitting pillar weights to a single roughly 3-year regime would overfit. Equal weights remain a hard design choice; nothing is fitted. Current diagnostics should be read as value-dominated disclosure rather than as evidence for fitted reweighting.

## Valuation context

Intrinsic valuation and fair value stay where they belong: per-name anchors for desk discussion. They are not used to rank the cross-section here, and this pass does not redesign the valuation engine.

## Predictive validation

D1 shows the evaluation / held-out-by-original-design period remains one regime, beginning on 2023-07-31. In this window the core `sfc` posts mean rank ICs of 0.0647 at 6m (HAC t 2.26, BH q 0.0516, n_dates 28, median N 67.0) and 0.1254 at 12m (HAC t 6.36, BH q 0.0000, n_dates 22, median N 67.0). The corresponding 6m VAL row is 0.1275 with HAC t 3.54; the 6m legacy composite row is 0.0919. Read this honestly: the current sample is still value-dominated, and the non-value pillars are diversification inputs rather than independently validated standalone engines here.

D2 is descriptive only. It measures the overlap between PMOM and the technical score and then checks PMOM IC after per-date rank residualization on the technical signal. It is included to keep the layer honest about cross-signal reuse, not to claim PMOM 'belongs' to either side.

D3 is the robustness check. It reruns VAL and core SFC at 6m and 12m under date jackknife, 3-date block jackknife, influential-name drops, financials removal, and median size splits, all on the same evaluation window and with the same HAC framing. Those rows are descriptive bounds, not a license to tune toward the most flattering variant.

## Portfolio interpretation

Claim C stays bounded: the score ranks names, but IC is not the same as harvestable alpha. The construction ladder reports proof-period active return, tracking error, and information ratio under equal-weight top tercile, benchmark-active uncapped, and benchmark-active +/-3%. The predictive edge concentrates in small-cap, non-financial names: VAL 6m IC is 0.1926 in the small-cap half versus 0.0747 in the large-cap half, where it is statistically insignificant, and the financials-removed row is higher than the baseline. That concentration is the mechanism behind the negative benchmark-relative IR: the equal-weight top-tercile ladder harvests the small-cap value premium (IR 0.8427), while float-weighting toward a mega-cap-dominated benchmark cannot (uncapped IR -0.3728, +/-3% IR -0.2462); the +/-3% cap is therefore not the binding cause. The bounded desk construction row currently shows active return -0.0034, tracking error 0.0551, and IR -0.2462. That is the right place to discuss transfer-coefficient limits, not to backfill causal stories.

## Limitations

- Single reused regime: the effective evidence window is still one market regime.
- Adaptive-reuse honesty: the same market history is reused across design, diagnostics, and desk interpretation, so all claims stay bounded to evaluation / held-out-by-original-design evidence rather than stronger language.
- 88% fallback-PIT: most panel rows still arrive via fallback availability lags, not observed publication dates.
- Value-domination: current evidence is led by VAL; equal weights remain a robustness choice, not a fitted optimum.
- Harvestability concentration: the predictive edge is concentrated in small-cap, non-financial names, which is harder to carry into benchmark-relative long-only implementations.
- Thin financials: financial and insurer subsets are small, so financials-specific diagnostics are descriptive.
- IC != alpha: predictive rank evidence does not guarantee long-only benchmark-relative harvestability.
