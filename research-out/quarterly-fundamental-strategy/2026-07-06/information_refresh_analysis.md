# Information Refresh Analysis (Phase 6)

Using the actual current (quarterly-blended) PIT panel, 3,104 stock-months across 71 symbols: **87.7% of monthly book-equity observations are a repeat of the immediately preceding month's value; only 12.3% represent a genuine new numerator.** This is the direct, quantified answer to the brief's central question: **monthly formation is mostly re-ranking stale fundamentals as prices move, not reacting to new information, the overwhelming majority of the time.**

This is not specific to including or excluding quarterly data — the annual-only ablation shows almost the identical repeat rate (87.9%), confirming the effect is about the underlying filing cadence (most companies file once or twice a year) rather than a pipeline choice.

## Practical implication for rebalance-frequency design

Since ~88% of monthly formations use the same numerator as the prior month, a monthly rebalance is mostly a monthly *re-rank of the market-cap denominator* (price movement), with a genuinely new numerator arriving roughly once every 8 months on average per symbol (12.3% of ~1 per month ≈ 1 new value per 8 months) — consistent with a mostly-annual, sometimes-semiannual filing cadence. This does **not** mean monthly rebalancing is wrong — re-ranking on price movement alone is still economically meaningful for a value strategy (cheaper stocks becoming cheaper or more expensive relative to peers is real information) — but it does mean **the "6 overlapping monthly vintages" design is not being fed 6x more fundamental information than a quarterly design would be; it is fed essentially the same fundamental information, just resampled onto a finer price-driven rank grid.**

## Not done this session

A per-symbol, per-metric breakdown of median months-between-genuine-updates (as opposed to the aggregate 87.7%/12.3% split) was not computed — this would sharpen the answer (e.g., confirming the ~5 symbols found in `quarterly_bm_comparison.md` update more frequently than the rest) but was judged lower priority than completing the strategy-level comparison in the time available.
