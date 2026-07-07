# Holdings Attribution (Phase 13)

Computed cumulative weight-time exposure and top-tercile membership frequency for S1 (B/M) across its 51 invested vintages (`stock_contribution_S1_bm.csv`).

## Key finding: material concentration in the top 3 names

| Symbol | Sector | Cumulative weight-time | Share of total S1 exposure | Dates in top tercile (of 51) |
|---|---|---|---|---|
| ADH | Immobilier (real estate) | 6.18 | 12.1% | 51 (100%) |
| ADI | Immobilier (real estate) | 6.05 | 11.9% | 48 (94%) |
| JET | BTP (construction) | 6.05 | 11.9% | 48 (94%) |
| ARD | Immobilier (real estate) | 1.85 | 3.6% | 38 |
| ... 26 more symbols | mixed sectors | — | — | 38 each |

**Top 3 symbols alone account for ~36% of total S1 exposure; top 5 (adding ARD, BCI) account for ~43%.** ADH (Douja Promotion Addoha) and ADI (Alliances Développement Immobilier) are both real-estate developers, and appeared in the B/M top tercile for essentially every single invested date (100% and 94% respectively) — meaning **B/M's "value" signal in this universe is, to a material degree, a persistent real-estate/construction sector bet**, not a broadly diversified cross-sectional value premium. This is a real, structural characteristic of Moroccan real-estate developers (large land-bank book values against depressed post-2010s-slump market caps), not obviously a data error — but it means **the strategy's strong Sharpe is materially exposed to whether Moroccan real estate specifically continued recovering over 2022-2026**, not a diversified bet across many sectors and stories.

## Is one sector dominating?

Yes, partially — real estate/construction (ADH, ADI, JET, ARD, RDS) together represent a meaningfully outsized share of the persistent core holdings, even though the full 30-name holdings list spans banks, mining, agrifood, financing, chemicals, and IT as well (the broader tail is diversified; the persistent, highest-weighted core is not).

## Not done this session

A full leave-one-stock-out recomputation of S1's Sharpe (removing ADH, ADI, JET one at a time and rerunning the engine) was not performed given time constraints — this is the natural, concrete next step to quantify exactly how much of the 1.62 Sharpe survives without the real-estate cluster, and is flagged as the top priority for the next research iteration (see `final_strategy_verdict.md` item 20). Sector-level and market-cap-bucket contribution tables (as opposed to symbol-level) were also not separately computed.
